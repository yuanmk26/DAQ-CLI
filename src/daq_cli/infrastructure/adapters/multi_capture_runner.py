"""Native runner for multi-board acquisition.

Mirrors the lifecycle of the legacy wrapper one-for-one:

    allocate run dir -> build payload -> write temp config -> construct app ->
    attach watch -> app.start() -> release a stuck TCM align controller ->
    poll loop (watch results / lazy decode backend / cancel) -> app.stop() ->
    drain watch + decode -> finalize outputs -> read status

The temp config path is deliberately kept at
``<output_base_dir>/.daq_cli_tmp/multi_board_acquire.config.json`` so the
on-disk artifact (and the CLI output that references it) is unchanged.
"""

from __future__ import annotations

import json
import multiprocessing
import queue
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from daq_cli.application.output_config import (
    AcquireOutputsConfig,
    OutputTargetConfig,
    TextOutputConfig,
)
from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.multi_board_decode_backend import (
    DecodeControlMessage,
    DecodeDrainResult,
    run_multi_board_decode_backend,
)
from daq_cli.infrastructure.adapters.multi_board_watch import (
    DEFAULT_MULTI_WATCH_QUEUE_SIZE,
    MultiBoardSampledPacket,
    MultiBoardWatchPublisher,
    MultiBoardWatchRuntime,
    WatchControlMessage,
    watch_backend_main,
)
from daq_cli.infrastructure.multi_board_acquire import (
    MultiBoardAcquisitionApp,
    MultiBoardAppConfig,
    MultiBoardConfig,
)
from daq_cli.infrastructure.rbcp import RbcpClient
from daq_cli.infrastructure.run_name_allocator import allocate_next_run_dir


@dataclass(slots=True)
class MultiCaptureConfig:
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
    outputs: AcquireOutputsConfig | None = None
    decode_json: bool = False
    text_output_enabled: bool = False
    text_output_dir: Path | None = None
    text_max_events_per_file: int = 100
    text_waveform_layout: str = "channel_blocks"
    watch_waveforms: bool = False
    watch_every: int | None = None
    stop_capture_on_watch_close: bool = True


@dataclass(slots=True)
class MultiCaptureResult:
    config_path: Path
    run_output_dir: Path | None
    status: str | None
    log_path: Path | None
    meta_path: Path | None
    decode_enabled: bool
    decoded_output_dir: Path | None
    decoded_complete_events: int
    decoded_partial_events: int
    decode_errors: int
    watch_waveforms: bool
    watch_every: int | None
    watched_frames: int
    stop_capture_on_watch_close: bool
    raw_output_dir: Path | None = None
    json_output_enabled: bool = False
    json_output_dir: Path | None = None
    log_output_dir: Path | None = None
    text_output_enabled: bool = False
    text_output_dir: Path | None = None
    text_output_complete_events: int = 0
    text_output_partial_events: int = 0
    text_output_files: int = 0


@dataclass(slots=True)
class MultiBoardDecodeRuntime:
    task_queue: Any
    result_queue: Any
    process: multiprocessing.Process
    output_dir: Path | None
    text_output_dir: Path | None = None


@dataclass(slots=True)
class _WatchDrainResult:
    watched_frames: int = 0
    viewer_closed: bool = False


class MultiCaptureRunner:
    """Native multi-board acquisition."""

    def capture_multi(
        self,
        config: MultiCaptureConfig,
        watch_update_callback: "Callable[[MultiBoardSampledPacket], None] | None" = None,
        cancel_event: threading.Event | None = None,
        progress_callback: "Callable[[Path, dict], None] | None" = None,
    ) -> MultiCaptureResult:
        run_output_dir = allocate_next_run_dir(
            config.output_base_dir, config.run_name_prefix
        )
        resolved_outputs = config.outputs or AcquireOutputsConfig(
            raw=OutputTargetConfig(enabled=True),
            json=OutputTargetConfig(enabled=config.decode_json),
            text=TextOutputConfig(
                enabled=config.text_output_enabled,
                dir=config.text_output_dir,
                max_events_per_file=config.text_max_events_per_file,
                waveform_layout=config.text_waveform_layout,
            ),
            log=OutputTargetConfig(enabled=True),
        )
        payload = self._build_payload(config, run_output_dir=run_output_dir)
        config_path = self._write_temp_config(payload)

        watched_frames = 0
        decoded_output_dir: Path | None = None
        text_output_dir: Path | None = None
        raw_output_dir: Path | None = None
        log_output_dir: Path | None = None
        decoded_complete_events = 0
        decoded_partial_events = 0
        decode_errors = 0
        text_output_complete_events = 0
        text_output_partial_events = 0
        text_output_files = 0

        app_config = MultiBoardAppConfig.from_payload(payload)
        frame_sink = None
        watch_callback_count = [0]
        watch_runtime: MultiBoardWatchRuntime | None = None
        if config.watch_waveforms:
            board_order = {
                board.board_id: (board.name, index)
                for index, board in enumerate(config.boards)
            }
            if watch_update_callback is not None:
                def wrapped_update(packet: MultiBoardSampledPacket) -> None:
                    watch_callback_count[0] += 1
                    watch_update_callback(packet)

                frame_sink = MultiBoardWatchPublisher(
                    board_order=board_order,
                    watch_every=int(config.watch_every or 100),
                    aggregation_key=config.aggregation_key,
                    timestamp_match_window_ticks=config.timestamp_match_window_ticks,
                    event_timeout_ms=config.event_timeout_ms,
                    task_queue=None,
                    frame_callback=wrapped_update,
                )
            else:
                watch_runtime = self._start_multi_watch_backend(config)
                frame_sink = MultiBoardWatchPublisher(
                    board_order=board_order,
                    watch_every=int(config.watch_every or 100),
                    aggregation_key=config.aggregation_key,
                    timestamp_match_window_ticks=config.timestamp_match_window_ticks,
                    event_timeout_ms=config.event_timeout_ms,
                    task_queue=watch_runtime.task_queue,
                )

        app = MultiBoardAcquisitionApp(
            app_config, config_path, frame_sink=frame_sink
        )
        decode_runtime: MultiBoardDecodeRuntime | None = None
        try:
            app.start()
            self._release_tcm_align_busy_after_start(app=app, config=config)
            while not app.stop_event.is_set():
                if progress_callback:
                    progress_callback(run_output_dir, app.state.snapshot())
                if cancel_event is not None and cancel_event.is_set():
                    app.stop_event.set()
                    break
                if (
                    (resolved_outputs.json.enabled or resolved_outputs.text.enabled)
                    and decode_runtime is None
                ):
                    decode_runtime = self._start_multi_decode_backend(
                        run_output_dir, outputs=resolved_outputs
                    )
                    decoded_output_dir = decode_runtime.output_dir
                    text_output_dir = decode_runtime.text_output_dir
                if watch_runtime is not None:
                    watch_drain = self._drain_watch_results(watch_runtime.result_queue)
                    watched_frames += watch_drain.watched_frames
                    if watch_drain.viewer_closed:
                        if config.stop_capture_on_watch_close:
                            app.logger.log(
                                "INFO",
                                "waveform watch closed; stopping acquisition",
                            )
                            app.stop_event.set()
                            break
                        app.logger.log(
                            "INFO",
                            "waveform watch closed; acquisition continues without monitoring",
                        )
                        watch_runtime = None
                        continue
                time.sleep(0.1)
        except KeyboardInterrupt:
            app.logger.log("INFO", "keyboard interrupt")
            app.stop_event.set()
        finally:
            app.stop()
            if progress_callback:
                progress_callback(run_output_dir, app.state.snapshot())
            if (
                (resolved_outputs.json.enabled or resolved_outputs.text.enabled)
                and decode_runtime is None
            ):
                decode_runtime = self._start_multi_decode_backend(
                    run_output_dir, outputs=resolved_outputs
                )
                decoded_output_dir = decode_runtime.output_dir
                text_output_dir = decode_runtime.text_output_dir
            if watch_runtime is not None:
                watched_frames += self._stop_multi_watch_backend(watch_runtime)
            else:
                watched_frames += watch_callback_count[0]
            if decode_runtime is not None:
                decode_drain = self._stop_multi_decode_backend(decode_runtime)
                decoded_complete_events += decode_drain.decoded_complete_events
                decoded_partial_events += decode_drain.decoded_partial_events
                decode_errors += decode_drain.decode_errors
                text_output_complete_events += decode_drain.text_output_complete_events
                text_output_partial_events += decode_drain.text_output_partial_events
                text_output_files += decode_drain.text_output_files
            elif resolved_outputs.json.enabled or resolved_outputs.text.enabled:
                decode_errors += 1

        meta_path = run_output_dir / "run_meta.json" if run_output_dir else None
        log_path = run_output_dir / "log.txt" if run_output_dir else None
        status = self._read_status(meta_path)
        if run_output_dir is not None:
            raw_output_dir, meta_path = self._finalize_multi_raw_outputs(
                run_output_dir=run_output_dir, outputs=resolved_outputs
            )
            log_output_dir, log_path = self._finalize_multi_log_output(
                run_output_dir=run_output_dir, outputs=resolved_outputs
            )
        return MultiCaptureResult(
            config_path=config_path,
            run_output_dir=run_output_dir,
            status=status,
            log_path=log_path if log_path and log_path.is_file() else None,
            meta_path=meta_path if meta_path and meta_path.is_file() else None,
            decode_enabled=resolved_outputs.json.enabled,
            decoded_output_dir=decoded_output_dir,
            decoded_complete_events=decoded_complete_events,
            decoded_partial_events=decoded_partial_events,
            decode_errors=decode_errors,
            raw_output_dir=raw_output_dir,
            json_output_enabled=resolved_outputs.json.enabled,
            json_output_dir=decoded_output_dir,
            log_output_dir=log_output_dir,
            watch_waveforms=config.watch_waveforms,
            watch_every=config.watch_every,
            watched_frames=watched_frames,
            stop_capture_on_watch_close=config.stop_capture_on_watch_close,
            text_output_enabled=resolved_outputs.text.enabled,
            text_output_dir=text_output_dir,
            text_output_complete_events=text_output_complete_events,
            text_output_partial_events=text_output_partial_events,
            text_output_files=text_output_files,
        )

    # ------------------------------------------------------------- payload

    def _build_payload(
        self, config: MultiCaptureConfig, *, run_output_dir: Path
    ) -> dict[str, object]:
        return {
            "run_name_prefix": config.run_name_prefix,
            "run_name": run_output_dir.name,
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

    # --------------------------------------------------------------- backends

    def _start_multi_watch_backend(
        self, config: MultiCaptureConfig
    ) -> MultiBoardWatchRuntime:
        context = multiprocessing.get_context("spawn")
        task_queue = context.Queue(maxsize=DEFAULT_MULTI_WATCH_QUEUE_SIZE)
        result_queue = context.Queue()
        process = context.Process(
            target=watch_backend_main,
            name="multi_board_wave_watch",
            args=(
                task_queue,
                result_queue,
                config.run_name_prefix,
                [board.name for board in config.boards],
            ),
        )
        process.start()
        return MultiBoardWatchRuntime(
            task_queue=task_queue,
            result_queue=result_queue,
            process=process,
        )

    def _start_multi_decode_backend(
        self,
        run_output_dir: Path,
        *,
        outputs: AcquireOutputsConfig,
    ) -> MultiBoardDecodeRuntime:
        context = multiprocessing.get_context("spawn")
        task_queue = context.Queue(maxsize=2)
        result_queue = context.Queue(maxsize=1)
        output_dir = (
            self._resolve_run_output_dir(
                run_output_dir=run_output_dir,
                configured_dir=outputs.json.dir,
                default_leaf="decoded",
            )
            if outputs.json.enabled
            else None
        )
        resolved_text_output_dir = (
            self._resolve_run_output_dir(
                run_output_dir=run_output_dir,
                configured_dir=outputs.text.dir,
                default_leaf="text",
            )
            if outputs.text.enabled
            else None
        )
        process = context.Process(
            target=run_multi_board_decode_backend,
            name="multi_board_decode",
            args=(
                task_queue,
                result_queue,
                str(run_output_dir),
                str(output_dir) if output_dir is not None else "",
                outputs.json.enabled,
                (
                    str(resolved_text_output_dir)
                    if resolved_text_output_dir is not None
                    else ""
                ),
                outputs.text.enabled,
                max(int(outputs.text.max_events_per_file), 1),
                outputs.text.waveform_layout,
            ),
        )
        process.start()
        return MultiBoardDecodeRuntime(
            task_queue=task_queue,
            result_queue=result_queue,
            process=process,
            output_dir=output_dir,
            text_output_dir=resolved_text_output_dir,
        )

    def _stop_multi_watch_backend(self, watch_runtime: MultiBoardWatchRuntime) -> int:
        if watch_runtime.process.is_alive():
            self._put_watch_sentinel(watch_runtime.task_queue)
        watched_frames = self._drain_watch_results(watch_runtime.result_queue).watched_frames
        process = watch_runtime.process
        while process.is_alive():
            process.join(timeout=0.05)
            watched_frames += self._drain_watch_results(
                watch_runtime.result_queue
            ).watched_frames
        process.join()
        watched_frames += self._drain_watch_results(watch_runtime.result_queue).watched_frames
        return watched_frames

    def _stop_multi_decode_backend(
        self, decode_runtime: MultiBoardDecodeRuntime
    ) -> DecodeDrainResult:
        if decode_runtime.process.is_alive():
            try:
                decode_runtime.task_queue.put_nowait(
                    DecodeControlMessage(kind="capture_finished")
                )
            except Exception:
                pass
        process = decode_runtime.process
        while process.is_alive():
            process.join(timeout=0.05)
        process.join()
        drained = self._drain_decode_results(decode_runtime.result_queue)
        if process.exitcode not in (0, None) and drained.decode_errors == 0:
            drained.decode_errors = 1
        return drained

    def _put_watch_sentinel(self, task_queue: Any) -> None:
        while True:
            try:
                task_queue.put_nowait(None)
                return
            except queue.Full:
                try:
                    task_queue.get_nowait()
                except queue.Empty:
                    return
            except Exception:
                return

    def _drain_watch_results(self, result_queue: Any) -> _WatchDrainResult:
        drained = _WatchDrainResult()
        while True:
            try:
                result = result_queue.get_nowait()
            except queue.Empty:
                return drained
            except Exception:
                return drained
            if getattr(result, "success", False):
                drained.watched_frames += 1
            elif getattr(result, "kind", None) == "viewer_closed":
                drained.viewer_closed = True

    def _drain_decode_results(self, result_queue: Any) -> DecodeDrainResult:
        drained = DecodeDrainResult()
        while True:
            try:
                result = result_queue.get_nowait()
            except queue.Empty:
                return drained
            except Exception:
                drained.decode_errors += 1
                return drained
            drained.decoded_complete_events += int(
                getattr(result, "decoded_complete_events", 0)
            )
            drained.decoded_partial_events += int(
                getattr(result, "decoded_partial_events", 0)
            )
            drained.decode_errors += int(getattr(result, "decode_errors", 0))
            drained.text_output_complete_events += int(
                getattr(result, "text_output_complete_events", 0)
            )
            drained.text_output_partial_events += int(
                getattr(result, "text_output_partial_events", 0)
            )
            drained.text_output_files += int(getattr(result, "text_output_files", 0))

    # ------------------------------------------------------------ TCM unblock

    def _release_tcm_align_busy_after_start(self, *, app, config) -> None:
        """Release a stuck TCM alignment controller after a failed align.

        The align sequence waits for board ACKs; when boards do not ACK, the
        controller can remain ALIGN_BUSY, blocking trigger-link wide-pulse
        broadcasts. The ACK is intentionally not relied on in the lab workflow,
        so clear the controller after the align attempt to unblock broadcasts.
        """
        snapshot = getattr(app, "align_snapshot", None)
        if snapshot is not None and snapshot.status is not None:
            if snapshot.status & 0x02:  # STATUS_DONE_STICKY_BIT
                return
        try:
            client = RbcpClient(
                device_ip=config.tcm_ip,
                udp_port=config.tcm_rbcp_port,
                timeout_ms=max(int(getattr(config, "tcm_timeout_ms", 1000)), 100),
            )
            try:
                client.write(0x18, bytes([0x02]))  # ALIGN_CTRL_CLEAR
            finally:
                client.close()
            app.logger.log(
                "WARN",
                "TCM align ack not relied on; cleared align controller to "
                "unblock trigger broadcasts",
            )
        except Exception as exc:  # noqa: BLE001 - best effort
            app.logger.log("WARN", "failed to clear TCM align controller: %s" % exc)

    # ------------------------------------------------------------- finalizing

    def _resolve_run_output_dir(
        self,
        *,
        run_output_dir: Path,
        configured_dir: Path | None,
        default_leaf: str,
    ) -> Path:
        if configured_dir is None:
            return run_output_dir / default_leaf
        return Path(configured_dir) / run_output_dir.name

    def _finalize_multi_raw_outputs(
        self,
        *,
        run_output_dir: Path,
        outputs: AcquireOutputsConfig,
    ) -> tuple[Path | None, Path | None]:
        meta_path = run_output_dir / "run_meta.json"
        raw_files = [
            run_output_dir / "complete_events.dat",
            run_output_dir / "partial_events.dat",
        ]
        if not outputs.raw.enabled:
            for raw_file in raw_files:
                if raw_file.exists():
                    raw_file.unlink()
            return None, meta_path if meta_path.exists() else None

        raw_output_dir = self._resolve_run_output_dir(
            run_output_dir=run_output_dir,
            configured_dir=outputs.raw.dir,
            default_leaf="raw",
        )
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        for source_path in [*raw_files, meta_path]:
            if source_path.exists():
                shutil.copy2(source_path, raw_output_dir / source_path.name)
        return raw_output_dir, raw_output_dir / "run_meta.json"

    def _finalize_multi_log_output(
        self,
        *,
        run_output_dir: Path,
        outputs: AcquireOutputsConfig,
    ) -> tuple[Path | None, Path | None]:
        source_log_path = run_output_dir / "log.txt"
        if not source_log_path.exists():
            return None, None
        if not outputs.log.enabled:
            source_log_path.unlink()
            return None, None
        log_output_dir = self._resolve_run_output_dir(
            run_output_dir=run_output_dir,
            configured_dir=outputs.log.dir,
            default_leaf="logs",
        )
        log_output_dir.mkdir(parents=True, exist_ok=True)
        target_log_path = log_output_dir / "log.txt"
        if target_log_path != source_log_path:
            shutil.copy2(source_log_path, target_log_path)
        return log_output_dir, target_log_path

    def _read_status(self, meta_path: Path | None) -> str | None:
        if meta_path is None or not meta_path.is_file():
            return None
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        status = raw.get("status")
        return str(status) if status is not None else None


__all__ = [
    "MultiBoardDecodeRuntime",
    "MultiCaptureConfig",
    "MultiCaptureResult",
    "MultiCaptureRunner",
]
