"""Waveform watch publisher and viewer backend process.

The publisher samples every Nth frame per board, buckets sampled frames into
logical aggregate events, and forwards each sampled frame as a wire packet. It
is invoked synchronously from the owning receiver thread (via
:class:`~daq_cli.infrastructure.multi_board_acquire.receiver.FrameSink`).

Two delivery modes:

* embedded — a ``frame_callback`` receives :class:`MultiBoardSampledPacket`
  directly (used by the GUI, no subprocess);
* viewer — packets go to a spawn ``multiprocessing.Queue`` consumed by
  :func:`run_multi_board_watch_backend`, which decodes them and drives
  :func:`run_multi_board_wave_viewer`.
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from daq_cli.infrastructure.multi_board_acquire.constants import WAVEFORM_MODES
from daq_cli.infrastructure.tcp_sent_decode import decode_tcp_sent_packet
from daq_cli.infrastructure.wave_monitor import compute_multi_board_viewer_queue_size

# Bursts from several boards can queue up while the viewer catches up,
# especially with watch_every=1.
DEFAULT_MULTI_WATCH_QUEUE_SIZE = 1024

FrameCallback = Callable[["MultiBoardSampledPacket"], None]


@dataclass(slots=True)
class MultiBoardSampledPacket:
    board_name: str
    board_index: int
    aggregate_event_id: int
    aggregate_timestamp: int
    board_event_count: int
    board_timestamp: int
    packet: bytes


@dataclass(slots=True)
class _ViewerAggregateBucket:
    aggregate_event_id: int
    aggregate_timestamp: int
    created_monotonic_s: float
    sampled_frames: dict[int, Any]


@dataclass(slots=True)
class MultiBoardWatchRuntime:
    task_queue: Any
    result_queue: Any
    process: multiprocessing.Process


@dataclass(slots=True)
class WatchResult:
    success: bool
    error_message: str | None = None


@dataclass(slots=True)
class WatchControlMessage:
    kind: str


class MultiBoardWatchPublisher:
    """Sample frames per board and forward them, bucketed by aggregate event."""

    def __init__(
        self,
        *,
        board_order: dict[int, tuple[str, int]],
        watch_every: int,
        aggregation_key: str,
        timestamp_match_window_ticks: int,
        event_timeout_ms: int,
        task_queue: Any = None,
        frame_callback: FrameCallback | None = None,
    ) -> None:
        self._board_order = board_order
        self._watch_every = max(int(watch_every), 1)
        self._aggregation_key = aggregation_key
        self._timestamp_match_window_ticks = max(int(timestamp_match_window_ticks), 0)
        self._event_timeout_s = max(float(event_timeout_ms) / 1000.0, 0.001)
        self._task_queue = task_queue
        self._frame_callback = frame_callback
        self._board_counts: dict[int, int] = {board_id: 0 for board_id in board_order}
        self._next_aggregate_event_id = 1
        self._buckets: dict[int, _ViewerAggregateBucket] = {}
        # Frames arrive from every receiver thread; the legacy publisher mutated
        # these dicts unlocked, which could raise mid-iteration in
        # _find_timestamp_bucket_key. Serialize the publisher instead.
        self._lock = threading.Lock()

    # --------------------------------------------------------------- publish

    def on_frame(self, frame: Any) -> None:
        board_id = int(frame.board_id)
        board_info = self._board_order.get(board_id)
        if board_info is None:
            return
        with self._lock:
            # Counters advance for every frame, including non-waveform modes, so
            # the sampling phase matches the legacy publisher exactly.
            self._board_counts[board_id] = self._board_counts.get(board_id, 0) + 1
            if self._board_counts[board_id] % self._watch_every != 0:
                return
            if int(frame.mode) not in WAVEFORM_MODES:
                return
            (
                bucket_key,
                aggregate_event_id,
                aggregate_timestamp,
                sampled_frames,
                should_close,
            ) = self._assign_viewer_aggregate(frame)

            packets = []
            for sampled_frame in sampled_frames:
                sampled_board_info = self._board_order.get(int(sampled_frame.board_id))
                if sampled_board_info is None:
                    continue
                packets.append(
                    MultiBoardSampledPacket(
                        board_name=sampled_board_info[0],
                        board_index=sampled_board_info[1],
                        aggregate_event_id=aggregate_event_id,
                        aggregate_timestamp=aggregate_timestamp,
                        board_event_count=int(sampled_frame.event_count),
                        board_timestamp=int(sampled_frame.timestamp),
                        packet=sampled_frame.raw_packet,
                    )
                )
            if should_close:
                self._buckets.pop(bucket_key, None)

        for sampled_packet in packets:
            self._enqueue_sampled_packet(sampled_packet)

    def _enqueue_sampled_packet(self, sampled_packet: MultiBoardSampledPacket) -> None:
        if self._frame_callback is not None:
            self._frame_callback(sampled_packet)
            return
        if self._task_queue is None:
            return
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

    # ---------------------------------------------------------------- buckets

    def _assign_viewer_aggregate(
        self, frame: Any
    ) -> tuple[int, int, int, list[Any], bool]:
        self._cleanup_stale_buckets()
        bucket_key = self._frame_key(frame)
        if self._aggregation_key == "timestamp":
            matched_key = self._find_timestamp_bucket_key(int(frame.timestamp))
            if matched_key is not None:
                bucket_key = matched_key
        bucket = self._buckets.get(bucket_key)
        if bucket is None:
            bucket = _ViewerAggregateBucket(
                aggregate_event_id=self._next_aggregate_event_id,
                aggregate_timestamp=int(frame.timestamp),
                created_monotonic_s=time.monotonic(),
                sampled_frames={},
            )
            self._buckets[bucket_key] = bucket
            self._next_aggregate_event_id += 1

        previous_timestamp = bucket.aggregate_timestamp
        bucket.aggregate_timestamp = min(bucket.aggregate_timestamp, int(frame.timestamp))
        bucket.sampled_frames[int(frame.board_id)] = frame
        timestamp_changed = bucket.aggregate_timestamp != previous_timestamp
        sampled_frames = (
            list(bucket.sampled_frames.values()) if timestamp_changed else [frame]
        )
        should_close = len(bucket.sampled_frames) >= len(self._board_order)
        return (
            bucket_key,
            bucket.aggregate_event_id,
            bucket.aggregate_timestamp,
            sampled_frames,
            should_close,
        )

    def _frame_key(self, frame: Any) -> int:
        if self._aggregation_key == "event_count":
            return int(frame.event_count)
        return int(frame.timestamp)

    def _find_timestamp_bucket_key(self, timestamp: int) -> int | None:
        for bucket_key in self._buckets:
            if abs(bucket_key - timestamp) <= self._timestamp_match_window_ticks:
                return bucket_key
        return None

    def _cleanup_stale_buckets(self) -> None:
        now_s = time.monotonic()
        expired_keys = [
            bucket_key
            for bucket_key, bucket in self._buckets.items()
            if now_s - bucket.created_monotonic_s >= self._event_timeout_s
        ]
        for bucket_key in expired_keys:
            self._buckets.pop(bucket_key, None)


# ---------------------------------------------------------------- viewer process


def watch_backend_main(
    task_queue: Any,
    result_queue: Any,
    group_label: str,
    board_names: list[str],
) -> None:
    """Spawn-process target: decode sampled packets and run the viewer."""
    from queue import Queue

    from daq_cli.infrastructure.wave_monitor import MultiBoardWaveUpdate, WaveMonitorFrame
    from daq_cli.presentation.wave_monitor_viewer import run_multi_board_wave_viewer

    viewer_queue: Queue[object] = Queue(
        maxsize=compute_multi_board_viewer_queue_size(len(board_names))
    )
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
                _publish_view_update(
                    viewer_queue,
                    MultiBoardWaveUpdate(
                        board_name=item.board_name,
                        board_index=item.board_index,
                        aggregate_event_id=item.aggregate_event_id,
                        aggregate_timestamp=item.aggregate_timestamp,
                        board_event_count=item.board_event_count,
                        board_timestamp=item.board_timestamp,
                        frame=frame,
                    ),
                )
                result_queue.put(WatchResult(success=True))
            except Exception as exc:  # noqa: BLE001 - reported to the runner
                result_queue.put(WatchResult(success=False, error_message=str(exc)))

    worker_thread = threading.Thread(
        target=worker, name="multi_wave_watch_worker", daemon=True
    )
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
            result_queue.put(WatchControlMessage(kind="viewer_closed"))
        except Exception:
            pass


def _publish_view_update(frame_queue: Any, update: Any) -> None:
    """Drop-oldest publish (the viewer only needs the latest updates)."""
    while True:
        try:
            frame_queue.put_nowait(update)
            return
        except queue.Full:
            try:
                frame_queue.get_nowait()
            except queue.Empty:
                return


__all__ = [
    "DEFAULT_MULTI_WATCH_QUEUE_SIZE",
    "MultiBoardSampledPacket",
    "MultiBoardWatchPublisher",
    "MultiBoardWatchRuntime",
    "WatchControlMessage",
    "WatchResult",
    "watch_backend_main",
]
