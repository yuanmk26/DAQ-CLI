from __future__ import annotations

import datetime
import multiprocessing
import queue
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.tcp_sent_decode import (
    DecodedTcpSentEvent,
    decode_tcp_sent_file,
    write_decoded_event_json,
)
from daq_cli.infrastructure.tcp_sent_protocol import (
    ADC_LENGTH,
    FEATURE_BYTES,
    FRAME_PREFIX,
    HEADER_BYTES,
    MODE2_MAGIC,
    frame_total_size,
)


DEFAULT_PACKET_QUEUE_SIZE = 128
DEFAULT_DECODE_QUEUE_SIZE = 128
DEFAULT_WATCH_QUEUE_SIZE = 1


@dataclass(slots=True)
class LegacySingleCaptureResult:
    run_output_dir: Path | None
    captured_events: int | None
    send_mode: int
    decode_enabled: bool
    decoded_output_dir: Path | None
    decoded_events: int
    decode_errors: int
    watch_enabled: bool
    watch_every: int | None
    watched_frames: int
    log_output: str


@dataclass(slots=True)
class LegacySingleCaptureProgress:
    captured_events: int
    packet_bytes: int | None
    hit_mask: int | None
    output_dir: Path | None


@dataclass(slots=True)
class RawCapturePacket:
    event_idx: int
    packet: bytes
    hit_mask: int


@dataclass(slots=True)
class DecodeWorkItem:
    raw_event_path: Path
    output_path: Path
    expected_send_mode: int
    adc_length: int


@dataclass(slots=True)
class DecodeWorkerResult:
    success: bool
    error_message: str | None = None


@dataclass(slots=True)
class WatchWorkItem:
    raw_event_path: Path
    expected_send_mode: int
    adc_length: int


@dataclass(slots=True)
class WatchWorkerResult:
    success: bool
    error_message: str | None = None


@dataclass(slots=True)
class ParallelCaptureStats:
    requested_events: int
    captured_events: int = 0
    writer_errors: int = 0
    decode_enabled: bool = False
    decode_submitted: int = 0
    decoded_events: int = 0
    decode_errors: int = 0
    watch_enabled: bool = False
    watch_every: int | None = None
    watched_frames: int = 0


@dataclass(slots=True)
class DecodeBackendRuntime:
    task_queue: Any
    result_queue: Any
    process: multiprocessing.Process


@dataclass(slots=True)
class WatchBackendRuntime:
    task_queue: Any
    result_queue: Any
    process: multiprocessing.Process


class LegacySingleCaptureRunner:
    """Native single-board TCP_SENT mode-2 capture with parallel receive/write."""

    def __init__(self, legacy_project_root: Path | str) -> None:
        self._project_root = Path(legacy_project_root)

    def capture_single(
        self,
        device: DeviceConfig,
        output_base_dir: Path,
        events: int,
        timeout_s: float,
        send_mode: int,
        decode_json: bool = False,
        decoded_output_dir: Path | None = None,
        watch_every: int | None = None,
        progress_callback: Callable[[LegacySingleCaptureProgress], None] | None = None,
    ) -> LegacySingleCaptureResult:
        output_base_dir = Path(output_base_dir)
        output_base_dir.mkdir(parents=True, exist_ok=True)
        run_output_dir = self._make_output_dir(output_base_dir)
        raw_dir = run_output_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        resolved_decoded_output_dir = (
            Path(decoded_output_dir) if decoded_output_dir is not None else run_output_dir / "decoded"
        )
        if decode_json:
            resolved_decoded_output_dir.mkdir(parents=True, exist_ok=True)

        packet_queue: queue.Queue[RawCapturePacket | None] = queue.Queue(
            maxsize=DEFAULT_PACKET_QUEUE_SIZE
        )
        exception_queue: queue.Queue[BaseException] = queue.Queue()
        stop_event = threading.Event()
        stats = ParallelCaptureStats(
            requested_events=events,
            decode_enabled=decode_json,
            watch_enabled=watch_every is not None,
            watch_every=watch_every,
        )
        deferred_decode_tasks: list[DecodeWorkItem] = []
        log_lines = [
            f"Connecting TCP {device.ip}:{device.tcp_port}",
            f"Capture send_mode: {send_mode}",
            f"Capture directory: {run_output_dir}",
        ]
        if decode_json:
            log_lines.append(f"Decoded output directory: {resolved_decoded_output_dir}")
        if watch_every is not None:
            log_lines.append(f"Wave watch every: {watch_every}")
        decode_backend = (
            self._start_decode_backend()
            if decode_json
            else None
        )
        watch_backend = (
            self._start_watch_backend(device_name=getattr(device, "name", "acquire"))
            if watch_every is not None
            else None
        )

        sock = self._open_socket(device=device, timeout_s=timeout_s)
        receiver = threading.Thread(
            target=self._receiver_loop,
            name="single_capture_receiver",
            daemon=True,
            args=(
                sock,
                packet_queue,
                stop_event,
                exception_queue,
                events,
                send_mode,
            ),
        )
        writer = threading.Thread(
            target=self._writer_loop,
            name="single_capture_writer",
            daemon=True,
            args=(
                raw_dir,
                run_output_dir,
                packet_queue,
                stop_event,
                exception_queue,
                stats,
                decode_json,
                resolved_decoded_output_dir,
                send_mode,
                decode_backend.task_queue if decode_backend is not None else None,
                deferred_decode_tasks,
                watch_every,
                watch_backend.task_queue if watch_backend is not None else None,
                progress_callback,
            ),
        )

        receiver.start()
        writer.start()
        receiver.join()
        writer.join()
        if decode_backend is not None:
            self._flush_deferred_decode_tasks(
                task_queue=decode_backend.task_queue,
                deferred_decode_tasks=deferred_decode_tasks,
            )
            self._put_decode_sentinel(task_queue=decode_backend.task_queue)
            self._wait_for_decode_backend(
                decode_backend=decode_backend,
                stats=stats,
            )
            if decode_backend.process.exitcode not in (0, None):
                missing = max(
                    0,
                    stats.decode_submitted - stats.decoded_events - stats.decode_errors,
                )
                stats.decode_errors += max(1, missing)
                log_lines.append(
                    f"Decode worker exited abnormally with code {decode_backend.process.exitcode}"
                )
        if watch_backend is not None:
            self._put_watch_sentinel(task_queue=watch_backend.task_queue)
            self._wait_for_watch_backend(
                watch_backend=watch_backend,
                stats=stats,
            )
        sock.close()

        first_error = self._pop_first_exception(exception_queue)
        self._write_capture_info(
            run_output_dir=run_output_dir,
            device=device,
            requested_events=events,
            captured_events=stats.captured_events,
            send_mode=send_mode,
            queue_maxsize=DEFAULT_PACKET_QUEUE_SIZE,
            writer_errors=stats.writer_errors,
            decode_enabled=decode_json,
            decoded_events=stats.decoded_events,
            decode_errors=stats.decode_errors,
            watch_enabled=watch_every is not None,
            watch_every=watch_every,
            watched_frames=stats.watched_frames,
        )
        log_lines.append(f"Captured events: {stats.captured_events}")
        if decode_json:
            log_lines.append(f"Decoded events: {stats.decoded_events}")
            log_lines.append(f"Decode errors: {stats.decode_errors}")
        if watch_every is not None:
            log_lines.append(f"Watched frames: {stats.watched_frames}")
        log_output = "\n".join(log_lines) + "\n"

        if first_error is not None:
            raise first_error

        return LegacySingleCaptureResult(
            run_output_dir=run_output_dir,
            captured_events=stats.captured_events,
            send_mode=send_mode,
            decode_enabled=decode_json,
            decoded_output_dir=resolved_decoded_output_dir if decode_json else None,
            decoded_events=stats.decoded_events,
            decode_errors=stats.decode_errors,
            watch_enabled=watch_every is not None,
            watch_every=watch_every,
            watched_frames=stats.watched_frames,
            log_output=log_output,
        )

    def _receiver_loop(
        self,
        sock: socket.socket,
        packet_queue: queue.Queue[RawCapturePacket | None],
        stop_event: threading.Event,
        exception_queue: queue.Queue[BaseException],
        events: int,
        expected_send_mode: int,
    ) -> None:
        reader = _TcpSentRawStreamReader(
            sock=sock,
            expected_send_mode=expected_send_mode,
        )
        try:
            for event_idx in range(events):
                if stop_event.is_set():
                    return
                packet = reader.read_packet()
                hit_mask = _u16_be(packet, 16)
                self._put_packet(
                    packet_queue=packet_queue,
                    packet=RawCapturePacket(
                        event_idx=event_idx,
                        packet=packet,
                        hit_mask=hit_mask,
                    ),
                    stop_event=stop_event,
                )
        except BaseException as exc:
            stop_event.set()
            exception_queue.put(exc)
        finally:
            self._put_sentinel(packet_queue=packet_queue, stop_event=stop_event)

    def _writer_loop(
        self,
        raw_dir: Path,
        run_output_dir: Path,
        packet_queue: queue.Queue[RawCapturePacket | None],
        stop_event: threading.Event,
        exception_queue: queue.Queue[BaseException],
        stats: ParallelCaptureStats,
        decode_json: bool,
        decoded_output_dir: Path,
        send_mode: int,
        decode_task_queue: Any,
        deferred_decode_tasks: list[DecodeWorkItem],
        watch_every: int | None,
        watch_task_queue: queue.Queue[WatchWorkItem | None] | None,
        progress_callback: Callable[[LegacySingleCaptureProgress], None] | None,
    ) -> None:
        try:
            while True:
                item = packet_queue.get()
                if item is None:
                    return
                raw_event_path = self._write_packet_file(raw_dir=raw_dir, packet=item)
                stats.captured_events += 1
                if decode_json:
                    decode_item = DecodeWorkItem(
                        raw_event_path=raw_event_path,
                        output_path=decoded_output_dir / f"{raw_event_path.stem}.json",
                        expected_send_mode=send_mode,
                        adc_length=ADC_LENGTH,
                    )
                    if not self._try_publish_decode_item(
                        task_queue=decode_task_queue,
                        item=decode_item,
                    ):
                        deferred_decode_tasks.append(decode_item)
                    stats.decode_submitted += 1
                if (
                    watch_every is not None
                    and watch_task_queue is not None
                    and stats.captured_events % watch_every == 0
                ):
                    self._try_publish_watch_item(
                        task_queue=watch_task_queue,
                        item=WatchWorkItem(
                            raw_event_path=raw_event_path,
                            expected_send_mode=send_mode,
                            adc_length=ADC_LENGTH,
                        ),
                    )
                if progress_callback is not None:
                    progress_callback(
                        LegacySingleCaptureProgress(
                            captured_events=stats.captured_events,
                            packet_bytes=len(item.packet),
                            hit_mask=item.hit_mask,
                            output_dir=run_output_dir,
                        )
                    )
        except BaseException as exc:
            stats.writer_errors = 1
            stop_event.set()
            exception_queue.put(exc)

    def _write_packet_file(self, raw_dir: Path, packet: RawCapturePacket) -> Path:
        path = raw_dir / f"event_{packet.event_idx:05d}.bin"
        with path.open("wb") as fh:
            fh.write(packet.packet)
        return path

    def _put_packet(
        self,
        packet_queue: queue.Queue[RawCapturePacket | None],
        packet: RawCapturePacket,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.is_set():
            try:
                packet_queue.put(packet, timeout=0.1)
                return
            except queue.Full:
                continue

    def _put_sentinel(
        self,
        packet_queue: queue.Queue[RawCapturePacket | None],
        stop_event: threading.Event,
    ) -> None:
        while True:
            try:
                packet_queue.put(None, timeout=0.1)
                return
            except queue.Full:
                if stop_event.is_set():
                    try:
                        packet_queue.get_nowait()
                    except queue.Empty:
                        continue

    def _put_decode_sentinel(self, task_queue: Any) -> None:
        while True:
            try:
                task_queue.put(None, timeout=0.1)
                return
            except queue.Full:
                continue

    def _try_publish_decode_item(
        self,
        task_queue: Any,
        item: DecodeWorkItem,
    ) -> bool:
        try:
            task_queue.put_nowait(item)
            return True
        except queue.Full:
            return False

    def _start_decode_backend(self) -> DecodeBackendRuntime:
        context = multiprocessing.get_context("spawn")
        task_queue = context.Queue(maxsize=DEFAULT_DECODE_QUEUE_SIZE)
        result_queue = context.Queue()
        process = context.Process(
            target=_decode_worker_main,
            name="single_capture_decode_worker",
            args=(task_queue, result_queue),
        )
        process.start()
        return DecodeBackendRuntime(
            task_queue=task_queue,
            result_queue=result_queue,
            process=process,
        )

    def _start_watch_backend(self, device_name: str) -> WatchBackendRuntime:
        context = multiprocessing.get_context("spawn")
        task_queue = context.Queue(maxsize=DEFAULT_WATCH_QUEUE_SIZE)
        result_queue = context.Queue()
        process = context.Process(
            target=_watch_backend_main,
            name="single_capture_watch_viewer",
            args=(task_queue, result_queue, device_name),
        )
        process.start()
        return WatchBackendRuntime(
            task_queue=task_queue,
            result_queue=result_queue,
            process=process,
        )

    def _flush_deferred_decode_tasks(
        self,
        task_queue: Any,
        deferred_decode_tasks: list[DecodeWorkItem],
    ) -> None:
        for item in deferred_decode_tasks:
            while True:
                try:
                    task_queue.put(item, timeout=0.1)
                    break
                except queue.Full:
                    continue

    def _collect_decode_results(
        self,
        result_queue: Any,
        stats: ParallelCaptureStats,
    ) -> None:
        while True:
            try:
                result = result_queue.get_nowait()
            except queue.Empty:
                return
            if result.success:
                stats.decoded_events += 1
            else:
                stats.decode_errors += 1

    def _collect_watch_results(
        self,
        result_queue: queue.Queue[WatchWorkerResult],
        stats: ParallelCaptureStats,
    ) -> None:
        while True:
            try:
                result = result_queue.get_nowait()
            except queue.Empty:
                return
            if result.success:
                stats.watched_frames += 1

    def _wait_for_decode_backend(
        self,
        decode_backend: DecodeBackendRuntime,
        stats: ParallelCaptureStats,
    ) -> None:
        process = decode_backend.process
        result_queue = decode_backend.result_queue
        while process.is_alive():
            process.join(timeout=0.05)
            self._collect_decode_results(
                result_queue=result_queue,
                stats=stats,
            )
        process.join()
        self._collect_decode_results(
            result_queue=result_queue,
            stats=stats,
        )

    def _put_watch_sentinel(
        self,
        task_queue: Any,
    ) -> None:
        while True:
            try:
                task_queue.put_nowait(None)
                return
            except queue.Full:
                try:
                    task_queue.get_nowait()
                except queue.Empty:
                    return

    def _try_publish_watch_item(
        self,
        task_queue: Any,
        item: WatchWorkItem,
    ) -> bool:
        try:
            task_queue.put_nowait(item)
            return True
        except queue.Full:
            try:
                task_queue.get_nowait()
            except queue.Empty:
                return False
            try:
                task_queue.put_nowait(item)
                return True
            except queue.Full:
                return False

    def _wait_for_watch_backend(
        self,
        watch_backend: WatchBackendRuntime,
        stats: ParallelCaptureStats,
    ) -> None:
        process = watch_backend.process
        while process.is_alive():
            process.join(timeout=0.05)
            self._collect_watch_results(
                result_queue=watch_backend.result_queue,
                stats=stats,
            )
        process.join()
        self._collect_watch_results(
            result_queue=watch_backend.result_queue,
            stats=stats,
        )

    def _open_socket(self, device: DeviceConfig, timeout_s: float) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_s)
        sock.connect((device.ip, device.tcp_port))
        return sock

    def _make_output_dir(self, base_dir: Path) -> Path:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = base_dir / timestamp
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_capture_info(
        self,
        run_output_dir: Path,
        device: DeviceConfig,
        requested_events: int,
        captured_events: int,
        send_mode: int,
        queue_maxsize: int,
        writer_errors: int,
        decode_enabled: bool,
        decoded_events: int,
        decode_errors: int,
        watch_enabled: bool,
        watch_every: int | None,
        watched_frames: int,
    ) -> None:
        info_path = run_output_dir / "capture_info.txt"
        info_path.write_text(
            "\n".join(
                [
                    f"tcp_ip={device.ip}",
                    f"tcp_port={device.tcp_port}",
                    f"requested_events={requested_events}",
                    f"captured_events={captured_events}",
                    f"send_mode={send_mode}",
                    f"adc_length={ADC_LENGTH}",
                    f"feature_bytes={FEATURE_BYTES}",
                    f"queue_maxsize={queue_maxsize}",
                    f"writer_errors={writer_errors}",
                    f"decode_enabled={1 if decode_enabled else 0}",
                    f"decoded_events={decoded_events}",
                    f"decode_errors={decode_errors}",
                    f"watch_enabled={1 if watch_enabled else 0}",
                    f"watch_every={watch_every if watch_every is not None else 0}",
                    f"watched_frames={watched_frames}",
                    "capture_mode=parallel",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def _pop_first_exception(
        self, exception_queue: queue.Queue[BaseException]
    ) -> BaseException | None:
        try:
            return exception_queue.get_nowait()
        except queue.Empty:
            return None


class _TcpSentRawStreamReader:
    def __init__(self, sock: socket.socket, expected_send_mode: int | None = None) -> None:
        self.sock = sock
        self.buffer = bytearray()
        self.expected_send_mode = expected_send_mode

    def _recv_more(self) -> None:
        chunk = self.sock.recv(4096)
        if not chunk:
            raise EOFError("TCP connection closed while waiting for data")
        self.buffer.extend(chunk)

    def _fill(self, size: int) -> None:
        while len(self.buffer) < size:
            self._recv_more()

    def _sync_to_magic(self) -> None:
        while True:
            pos = bytes(self.buffer).find(FRAME_PREFIX)
            if pos >= 0:
                if pos:
                    del self.buffer[:pos]
                self._fill(len(MODE2_MAGIC))
                return

            keep = max(0, len(FRAME_PREFIX) - 1)
            if len(self.buffer) > keep:
                del self.buffer[: len(self.buffer) - keep]
            self._recv_more()

    def read_packet(self) -> bytes:
        self._sync_to_magic()
        self._fill(HEADER_BYTES)

        header = bytes(self.buffer[:HEADER_BYTES])
        mode = header[3]
        if self.expected_send_mode is not None and mode != self.expected_send_mode:
            del self.buffer[0]
            raise ValueError(
                f"synced packet mode {mode} does not match expected send_mode "
                f"{self.expected_send_mode}"
            )

        hit_mask = _u16_be(header, 16)
        feature_size = header[18]
        if mode in (2, 3) and feature_size != FEATURE_BYTES:
            del self.buffer[0]
            raise ValueError(
                f"send_mode {mode} feature size is {feature_size}, expected "
                f"{FEATURE_BYTES}"
            )
        if mode in (0, 1) and feature_size != 0:
            del self.buffer[0]
            raise ValueError(
                f"send_mode {mode} feature size is {feature_size}, expected 0"
            )

        hit_count = _bit_count(hit_mask)
        total_size = frame_total_size(
            send_mode=mode,
            hit_count=hit_count,
            adc_length=ADC_LENGTH,
            feature_bytes=FEATURE_BYTES,
        )
        self._fill(total_size)
        packet = bytes(self.buffer[:total_size])
        del self.buffer[:total_size]
        return packet


_Mode2RawStreamReader = _TcpSentRawStreamReader
_frame_total_size = frame_total_size


def _bit_count(value: int) -> int:
    count = 0
    while value:
        count += value & 1
        value >>= 1
    return count


def _u16_be(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def _decode_worker_main(task_queue: Any, result_queue: Any) -> None:
    while True:
        item = task_queue.get()
        if item is None:
            return
        try:
            event = decode_tcp_sent_file(
                item.raw_event_path,
                expected_send_mode=item.expected_send_mode,
                adc_length=item.adc_length,
            )
            write_decoded_event_json(event, item.output_path)
            result_queue.put(DecodeWorkerResult(success=True))
        except Exception as exc:
            result_queue.put(
                DecodeWorkerResult(success=False, error_message=str(exc))
            )


def _watch_worker_main(
    task_queue: Any,
    result_queue: Any,
    frame_queue: queue.Queue[object],
    stop_event: threading.Event,
    device_name: str,
) -> None:
    while True:
        if stop_event.is_set() and task_queue.empty():
            return
        try:
            item = task_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if item is None:
            return
        try:
            decoded = decode_tcp_sent_file(
                item.raw_event_path,
                expected_send_mode=item.expected_send_mode,
                adc_length=item.adc_length,
            )
            _publish_watch_frame(
                frame_queue=frame_queue,
                frame=_decoded_event_to_wave_monitor_frame(
                    event=decoded,
                    device_name=device_name,
                ),
            )
            result_queue.put(WatchWorkerResult(success=True))
        except Exception as exc:
            result_queue.put(
                WatchWorkerResult(success=False, error_message=str(exc))
            )


def _watch_backend_main(
    task_queue: Any,
    result_queue: Any,
    device_name: str,
) -> None:
    from daq_cli.presentation.wave_monitor_viewer import run_wave_monitor_viewer

    frame_queue: queue.Queue[object] = queue.Queue(maxsize=1)
    stop_event = threading.Event()
    worker_thread = threading.Thread(
        target=_watch_worker_main,
        name="single_capture_watch_worker",
        daemon=True,
        args=(task_queue, result_queue, frame_queue, stop_event, device_name),
    )
    worker_thread.start()
    try:
        run_wave_monitor_viewer("capture-watch", frame_queue, stop_event)
    finally:
        stop_event.set()
        worker_thread.join(timeout=2.0)


def _decoded_event_to_wave_monitor_frame(
    event: DecodedTcpSentEvent,
    device_name: str,
):
    from daq_cli.infrastructure.wave_monitor import WaveMonitorFrame

    return WaveMonitorFrame(
        device_name=device_name,
        event_count=event.event_count,
        timestamp=event.timestamp,
        hit_mask=event.hit_mask,
        send_mode=event.send_mode,
        channels=[
            list(channel) if channel is not None else []
            for channel in event.channels
        ],
    )


def _publish_watch_frame(
    frame_queue: queue.Queue[object],
    frame: object,
) -> None:
    while True:
        try:
            frame_queue.put_nowait(frame)
            return
        except queue.Full:
            try:
                frame_queue.get_nowait()
            except queue.Empty:
                return
