from __future__ import annotations

import importlib
import io
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_runtime import clear_legacy_modules, temporary_sys_path


@dataclass(slots=True)
class LegacySingleCaptureResult:
    run_output_dir: Path | None
    captured_events: int | None
    log_output: str


class LegacySingleCaptureRunner:
    """Wrapper for the single-board TCP_SENT mode-2 capture script."""

    def __init__(self, legacy_project_root: Path | str) -> None:
        self._project_root = Path(legacy_project_root)
        self._script_dir = self._project_root / "script"

    def capture_single(
        self,
        device: DeviceConfig,
        output_base_dir: Path,
        events: int,
        timeout_s: float,
    ) -> LegacySingleCaptureResult:
        output_base_dir = Path(output_base_dir)
        output_base_dir.mkdir(parents=True, exist_ok=True)
        before = {path.resolve() for path in output_base_dir.iterdir()}

        with temporary_sys_path(self._script_dir):
            clear_legacy_modules()
            module = importlib.import_module("capture_tcp_sent_mode2")
            module.TCP_IP = device.ip
            module.TCP_PORT = device.tcp_port
            module.EVENTS = events
            module.TCP_TIMEOUT = timeout_s
            module.OUTPUT_BASE_DIR = str(output_base_dir)
            captured = io.StringIO()
            with redirect_stdout(captured):
                module.capture()

        after = {path.resolve() for path in output_base_dir.iterdir()}
        created = sorted(after - before, key=lambda item: item.stat().st_mtime)
        run_output_dir = created[-1] if created else None
        captured_events = self._read_captured_events(run_output_dir)
        return LegacySingleCaptureResult(
            run_output_dir=run_output_dir,
            captured_events=captured_events,
            log_output=captured.getvalue(),
        )

    def _read_captured_events(self, run_output_dir: Path | None) -> int | None:
        if run_output_dir is None:
            return None
        info_path = run_output_dir / "capture_info.txt"
        if not info_path.is_file():
            return None
        for line in info_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("captured_events="):
                return int(line.split("=", 1)[1])
        return None
