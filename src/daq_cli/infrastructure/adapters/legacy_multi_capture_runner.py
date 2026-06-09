from __future__ import annotations

import importlib
import json
import multiprocessing
import queue
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_runtime import (
    clear_legacy_modules,
    temporary_sys_path,
)
from daq_cli.infrastructure.multi_board_decode import (
    MultiBoardDecodeError,
    MultiBoardTailReadState,
    build_board_context,
    event_to_json_dict,
    load_multi_run_metadata,
    read_available_tail_events,
)
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet


DEFAULT_MULTI_WATCH_QUEUE_SIZE = 8


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
    decode_json: bool = False
    watch_waveforms: bool = False
    watch_every: int | None = None
    stop_capture_on_watch_close: bool = True


@dataclass(slots=True)
class LegacyMultiCaptureResult:
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


@dataclass(slots=True)
class MultiBoardSampledPacket:
    board_name: str
    board_index: int
    packet: bytes


@dataclass(slots=True)
class MultiBoardWatchRuntime:
    task_queue: Any
    result_queue: Any
    process: multiprocessing.Process


@dataclass(slots=True)
class MultiBoardDecodeRuntime:
    task_queue: Any
    result_queue: Any
    process: multiprocessing.Process
    output_dir: Path


@dataclass(slots=True)
class _WatchDrainResult:
    watched_frames: int = 0
    viewer_closed: bool = False


@dataclass(slots=True)
class _DecodeDrainResult:
    decoded_complete_events: int = 0
    decoded_partial_events: int = 0
    decode_errors: int = 0


class _MultiBoardFrameQueueProxy:
    def __init__(self, downstream_queue: Any, publisher: "_MultiBoardWatchPublisher") -> None:
        self._downstream_queue = downstream_queue
        self._publisher = publisher

    def put(self, item: Any, *args, **kwargs) -> None:
        self._downstream_queue.put(item, *args, **kwargs)
        self._publisher.publish(item)


class _MultiBoardWatchPublisher:
    def __init__(
        self,
        *,
        board_order: dict[int, tuple[str, int]],
        watch_every: int,
        task_queue: Any,
    ) -> None:
        self._board_order = board_order
        self._watch_every = watch_every
        self._task_queue = task_queue
        self._board_counts: dict[int, int] = {board_id: 0 for board_id in board_order}

    def publish(self, frame: Any) -> None:
        board_id = int(frame.board_id)
        board_info = self._board_order.get(board_id)
        if board_info is None:
            return
        self._board_counts[board_id] = self._board_counts.get(board_id, 0) + 1
        if self._board_counts[board_id] % self._watch_every != 0:
            return
        if int(frame.mode) not in (1, 3):
            return
        sampled_packet = MultiBoardSampledPacket(
            board_name=board_info[0],
            board_index=board_info[1],
            packet=_legacy_frame_to_tcp_sent_packet(frame),
        )
        try:
            self._task_queue.put_nowait(sampled_packet)
        except queue.Full:
            try:
                self._task_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._task_queue.put_nowait(sampled_packet)
            except Exception:
                return
        except Exception:
            return


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
        watched_frames = 0
        decoded_output_dir: Path | None = None
        decoded_complete_events = 0
        decoded_partial_events = 0
        decode_errors = 0

        with temporary_sys_path(self._script_dir):
            clear_legacy_modules()
            module = importlib.import_module("multi_board_acquire")
            app_config = module.AppConfig.from_json_file(str(config_path))
            app = module.AcquisitionApp(app_config, str(config_path))
            run_output_dir: Path | None = None
            decode_runtime: MultiBoardDecodeRuntime | None = None
            watch_runtime = (
                self._start_multi_watch_backend(config)
                if config.watch_waveforms
                else None
            )
            if watch_runtime is not None:
                self._attach_multi_watch_proxy(app=app, config=config, watch_runtime=watch_runtime)
            try:
                app.start()
                while not app.stop_event.is_set():
                    if run_output_dir is None:
                        run_output_dir = self._read_run_dir(config_path)
                    if (
                        config.decode_json
                        and decode_runtime is None
                        and run_output_dir is not None
                    ):
                        decode_runtime = self._start_multi_decode_backend(run_output_dir)
                        decoded_output_dir = decode_runtime.output_dir
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
                if run_output_dir is None:
                    run_output_dir = self._read_run_dir(config_path)
                if (
                    config.decode_json
                    and decode_runtime is None
                    and run_output_dir is not None
                ):
                    decode_runtime = self._start_multi_decode_backend(run_output_dir)
                    decoded_output_dir = decode_runtime.output_dir
                if watch_runtime is not None:
                    watched_frames += self._stop_multi_watch_backend(watch_runtime)
                if decode_runtime is not None:
                    decode_drain = self._stop_multi_decode_backend(decode_runtime)
                    decoded_complete_events += decode_drain.decoded_complete_events
                    decoded_partial_events += decode_drain.decoded_partial_events
                    decode_errors += decode_drain.decode_errors
                elif config.decode_json:
                    decode_errors += 1

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
            decode_enabled=config.decode_json,
            decoded_output_dir=decoded_output_dir,
            decoded_complete_events=decoded_complete_events,
            decoded_partial_events=decoded_partial_events,
            decode_errors=decode_errors,
            watch_waveforms=config.watch_waveforms,
            watch_every=config.watch_every,
            watched_frames=watched_frames,
            stop_capture_on_watch_close=config.stop_capture_on_watch_close,
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

    def _start_multi_watch_backend(
        self,
        config: LegacyMultiCaptureConfig,
    ) -> MultiBoardWatchRuntime:
        context = multiprocessing.get_context("spawn")
        task_queue = context.Queue(maxsize=DEFAULT_MULTI_WATCH_QUEUE_SIZE)
        result_queue = context.Queue()
        process = context.Process(
            target=_multi_board_watch_backend_main,
            name="multi_board_wave_watch",
            args=(task_queue, result_queue, config.run_name_prefix, [board.name for board in config.boards]),
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
    ) -> MultiBoardDecodeRuntime:
        context = multiprocessing.get_context("spawn")
        task_queue = context.Queue(maxsize=2)
        result_queue = context.Queue(maxsize=1)
        output_dir = run_output_dir / "decoded"
        process = context.Process(
            target=_multi_board_decode_backend_main,
            name="multi_board_decode",
            args=(task_queue, result_queue, str(run_output_dir), str(output_dir)),
        )
        process.start()
        return MultiBoardDecodeRuntime(
            task_queue=task_queue,
            result_queue=result_queue,
            process=process,
            output_dir=output_dir,
        )

    def _attach_multi_watch_proxy(
        self,
        *,
        app: Any,
        config: LegacyMultiCaptureConfig,
        watch_runtime: MultiBoardWatchRuntime,
    ) -> None:
        board_order = {
            board.board_id: (board.name, index)
            for index, board in enumerate(config.boards)
        }
        publisher = _MultiBoardWatchPublisher(
            board_order=board_order,
            watch_every=int(config.watch_every or 100),
            task_queue=watch_runtime.task_queue,
        )
        for receiver in app.receivers:
            receiver.frame_queue = _MultiBoardFrameQueueProxy(receiver.frame_queue, publisher)

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
        watched_frames += self._drain_watch_results(
            watch_runtime.result_queue
        ).watched_frames
        return watched_frames

    def _stop_multi_decode_backend(
        self,
        decode_runtime: MultiBoardDecodeRuntime,
    ) -> _DecodeDrainResult:
        if decode_runtime.process.is_alive():
            try:
                decode_runtime.task_queue.put_nowait(
                    _DecodeControlMessage(kind="capture_finished")
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

    def _drain_decode_results(self, result_queue: Any) -> _DecodeDrainResult:
        drained = _DecodeDrainResult()
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


def _legacy_frame_to_tcp_sent_packet(frame: Any) -> bytes:
    header = bytearray(20)
    header[0:3] = b"\xFF\xFE\x01"
    header[3] = int(frame.mode) & 0xFF
    header[4:8] = int(frame.event_count).to_bytes(4, byteorder="big", signed=False)
    header[8:16] = int(frame.timestamp).to_bytes(8, byteorder="big", signed=False)
    header[16:18] = int(frame.hit_mask).to_bytes(2, byteorder="big", signed=False)
    header[18] = int(frame.feature_size) & 0xFF
    header[19] = 0
    return bytes(header) + bytes(frame.feature_bytes) + bytes(frame.waveform_bytes)


def _multi_board_watch_backend_main(
    task_queue: Any,
    result_queue: Any,
    group_label: str,
    board_names: list[str],
) -> None:
    import threading
    from queue import Queue

    from daq_cli.infrastructure.wave_monitor import WaveMonitorFrame
    from daq_cli.presentation.wave_monitor_viewer import (
        MultiBoardWaveUpdate,
        run_multi_board_wave_viewer,
    )

    viewer_queue: Queue[object] = Queue(maxsize=1)
    stop_event = threading.Event()

    def worker() -> None:
        while not stop_event.is_set():
            try:
                item = task_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                return
            try:
                decoded = decode_tcp_sent_packet(
                    item.packet,
                    source_file=Path(f"{group_label}_{item.board_name}.bin"),
                )
                frame = WaveMonitorFrame(
                    device_name=item.board_name,
                    event_count=decoded.event_count,
                    timestamp=decoded.timestamp,
                    hit_mask=decoded.hit_mask,
                    send_mode=decoded.send_mode,
                    channels=[
                        list(channel) if channel is not None else []
                        for channel in decoded.channels
                    ],
                )
                _publish_multi_board_view_update(
                    viewer_queue,
                    MultiBoardWaveUpdate(
                        board_name=item.board_name,
                        board_index=item.board_index,
                        frame=frame,
                    ),
                )
                result_queue.put(_WatchResult(success=True))
            except Exception as exc:
                result_queue.put(_WatchResult(success=False, error_message=str(exc)))

    worker_thread = threading.Thread(target=worker, name="multi_wave_watch_worker", daemon=True)
    worker_thread.start()
    try:
        run_multi_board_wave_viewer(
            group_label=group_label,
            board_names=board_names,
            frame_queue=viewer_queue,
            stop_event=stop_event,
        )
    finally:
        stop_event.set()
        worker_thread.join(timeout=2.0)
        try:
            result_queue.put(_WatchControlMessage(kind="viewer_closed"))
        except Exception:
            pass


@dataclass(slots=True)
class _WatchResult:
    success: bool
    error_message: str | None = None


@dataclass(slots=True)
class _WatchControlMessage:
    kind: str


@dataclass(slots=True)
class _DecodeControlMessage:
    kind: str


@dataclass(slots=True)
class _DecodeSummary:
    decoded_complete_events: int
    decoded_partial_events: int
    decode_errors: int


def _publish_multi_board_view_update(frame_queue: Any, update: Any) -> None:
    while True:
        try:
            frame_queue.put_nowait(update)
            return
        except queue.Full:
            try:
                frame_queue.get_nowait()
            except queue.Empty:
                return


def _multi_board_decode_backend_main(
    task_queue: Any,
    result_queue: Any,
    run_output_dir: str,
    decoded_output_dir: str,
) -> None:
    run_dir = Path(run_output_dir)
    output_dir = Path(decoded_output_dir)
    complete_output_dir = output_dir / "complete"
    partial_output_dir = output_dir / "partial"
    complete_output_dir.mkdir(parents=True, exist_ok=True)
    partial_output_dir.mkdir(parents=True, exist_ok=True)

    decode_errors = 0
    decoded_complete_events = 0
    decoded_partial_events = 0
    capture_finished = False
    board_context: dict[int, dict[str, object]] | None = None
    aggregation_key = "unknown"
    complete_state = MultiBoardTailReadState()
    partial_state = MultiBoardTailReadState()
    complete_input_path = run_dir / "complete_events.dat"
    partial_input_path = run_dir / "partial_events.dat"

    try:
        while True:
            while True:
                try:
                    control = task_queue.get_nowait()
                except queue.Empty:
                    break
                if getattr(control, "kind", None) == "capture_finished":
                    capture_finished = True

            if board_context is None:
                try:
                    run_meta = load_multi_run_metadata(run_dir)
                except Exception:
                    if capture_finished:
                        decode_errors += 1
                        break
                    time.sleep(0.05)
                    continue
                board_context = build_board_context(run_meta)
                aggregation_key = str(run_meta.get("aggregation_key", "unknown"))

            made_progress = False
            try:
                complete_batch = read_available_tail_events(
                    path=complete_input_path,
                    event_kind="complete",
                    state=complete_state,
                )
                complete_state = complete_batch.state
                for event in complete_batch.events:
                    output_path = complete_output_dir / f"event_{event.aggregate_seq:05d}.json"
                    payload = event_to_json_dict(
                        event=event,
                        aggregation_key=aggregation_key,
                        board_context=board_context,
                    )
                    output_path.write_text(
                        json.dumps(payload, indent=2),
                        encoding="utf-8",
                    )
                    decoded_complete_events += 1
                    made_progress = True

                partial_batch = read_available_tail_events(
                    path=partial_input_path,
                    event_kind="partial",
                    state=partial_state,
                )
                partial_state = partial_batch.state
                for event in partial_batch.events:
                    output_path = partial_output_dir / f"event_{event.aggregate_seq:05d}.json"
                    payload = event_to_json_dict(
                        event=event,
                        aggregation_key=aggregation_key,
                        board_context=board_context,
                    )
                    output_path.write_text(
                        json.dumps(payload, indent=2),
                        encoding="utf-8",
                    )
                    decoded_partial_events += 1
                    made_progress = True
            except MultiBoardDecodeError:
                decode_errors += 1
                break
            except Exception:
                decode_errors += 1
                break

            if capture_finished and not made_progress:
                break
            if not made_progress:
                time.sleep(0.05)
    finally:
        try:
            result_queue.put(
                _DecodeSummary(
                    decoded_complete_events=decoded_complete_events,
                    decoded_partial_events=decoded_partial_events,
                    decode_errors=decode_errors,
                )
            )
        except Exception:
            pass
