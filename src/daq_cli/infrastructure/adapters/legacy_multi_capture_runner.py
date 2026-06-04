from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_runtime import (
    clear_legacy_modules,
    temporary_sys_path,
)


@dataclass(slots=True)
class LegacyMultiCaptureConfig:
    run_name_prefix: str
    output_base_dir: Path
    tcm_ip: str
    tcm_rbcp_port: int
    adc_length: int
    aggregation_key: str
    timestamp_match_window_ticks: int
    event_timeout_ms: int
    tcp_timeout_s: float
    allow_start_without_ack: bool
    boards: list[DeviceConfig]


@dataclass(slots=True)
class LegacyMultiCaptureResult:
    config_path: Path
    run_output_dir: Path | None
    status: str | None
    log_path: Path | None
    meta_path: Path | None


class LegacyMultiCaptureRunner:
    """Wrapper for the legacy multi-board acquisition script."""

    def __init__(self, legacy_project_root: Path | str) -> None:
        self._project_root = Path(legacy_project_root)
        self._script_dir = self._project_root / "script"

    def capture_multi(
        self,
        config: LegacyMultiCaptureConfig,
    ) -> LegacyMultiCaptureResult:
        payload = self._build_payload(config)
        config_path = self._write_temp_config(payload)

        with temporary_sys_path(self._script_dir):
            clear_legacy_modules()
            module = importlib.import_module("multi_board_acquire")
            app_config = module.AppConfig.from_json_file(str(config_path))
            app = module.AcquisitionApp(app_config, str(config_path))
            try:
                app.start()
                while not app.stop_event.is_set():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                app.logger.log("INFO", "keyboard interrupt")
            finally:
                app.stop()

        run_output_dir = self._read_run_dir(config_path)
        meta_path = run_output_dir / "run_meta.json" if run_output_dir else None
        log_path = run_output_dir / "log.txt" if run_output_dir else None
        status = self._read_status(meta_path)
        return LegacyMultiCaptureResult(
            config_path=config_path,
            run_output_dir=run_output_dir,
            status=status,
            log_path=log_path if log_path and log_path.is_file() else None,
            meta_path=meta_path if meta_path and meta_path.is_file() else None,
        )

    def _build_payload(self, config: LegacyMultiCaptureConfig) -> dict[str, object]:
        return {
            "run_name_prefix": config.run_name_prefix,
            "output_base_dir": str(config.output_base_dir),
            "adc_length": config.adc_length,
            "aggregation_key": config.aggregation_key,
            "timestamp_match_window_ticks": config.timestamp_match_window_ticks,
            "event_timeout_ms": config.event_timeout_ms,
            "monitor_interval_s": 1.0,
            "monitor_jsonl_interval_s": 5.0,
            "tcp_timeout_s": config.tcp_timeout_s,
            "reconnect_delay_s": 1.0,
            "recv_buffer_bytes": 8192,
            "frame_queue_size": 10000,
            "board_warn_no_data_s": 3.0,
            "partial_warn_ratio": 0.01,
            "reconnect_warn_count": 3,
            "tcm": {
                "ip": config.tcm_ip,
                "rbcp_port": config.tcm_rbcp_port,
                "timeout_ms": 3000,
                "command_delay_s": 0.02,
                "poll_interval_s": 0.05,
                "poll_timeout_s": 2.0,
                "allow_start_without_ack": config.allow_start_without_ack,
            },
            "boards": [
                {
                    "board_id": board.board_id,
                    "name": board.name,
                    "ip": board.ip,
                    "tcp_port": board.tcp_port,
                }
                for board in config.boards
            ],
        }

    def _write_temp_config(self, payload: dict[str, object]) -> Path:
        output_base_dir = Path(str(payload["output_base_dir"]))
        temp_dir = output_base_dir / ".daq_cli_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        config_path = temp_dir / "multi_board_acquire.config.json"
        config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return config_path

    def _read_run_dir(self, config_path: Path) -> Path | None:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        output_base_dir = Path(str(raw["output_base_dir"]))
        run_prefix = str(raw["run_name_prefix"])
        if not output_base_dir.is_dir():
            return None
        candidates = sorted(
            (
                path
                for path in output_base_dir.iterdir()
                if path.is_dir() and path.name.startswith(f"{run_prefix}_")
            ),
            key=lambda item: item.stat().st_mtime,
        )
        return candidates[-1] if candidates else None

    def _read_status(self, meta_path: Path | None) -> str | None:
        if meta_path is None or not meta_path.is_file():
            return None
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        status = raw.get("status")
        return str(status) if status is not None else None
