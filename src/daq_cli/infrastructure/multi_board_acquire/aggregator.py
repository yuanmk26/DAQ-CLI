"""Event aggregation by timestamp or event_count."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from daq_cli.infrastructure.multi_board_acquire.clock import MultiBoardClock, SYSTEM_CLOCK
from daq_cli.infrastructure.multi_board_acquire.config import (
    MultiBoardAppConfig,
    MultiBoardConfig,
)
from daq_cli.infrastructure.multi_board_acquire.constants import (
    EVENT_FLAG_COMPLETE,
    EVENT_FLAG_EVENT_COUNT_MISMATCH,
    EVENT_FLAG_PARTIAL,
    EVENT_FLAG_TIMEOUT_FLUSH,
    mask_from_board_ids,
)
from daq_cli.infrastructure.multi_board_acquire.frames import MultiBoardFrame


@dataclass(slots=True)
class AggregatedEvent:
    aggregate_seq: int
    aggregation_value: int
    timestamp: int
    created_unix_ns: int
    first_recv_unix_ns: int
    flush_unix_ns: int
    frames: dict[int, MultiBoardFrame]
    boards_present_mask: int
    boards_missing_mask: int
    status_flags: int
    event_count_min: int
    event_count_max: int
    missing_board_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class _Bucket:
    aggregation_value: int
    timestamp: int
    created_monotonic_s: float
    first_recv_unix_ns: int
    frames: dict[int, MultiBoardFrame] = field(default_factory=dict)


class MultiBoardEventAggregator(threading.Thread):
    """Merge per-board frames into complete/partial events, writing as it goes."""

    def __init__(
        self,
        boards: list[MultiBoardConfig],
        config: MultiBoardAppConfig,
        frame_queue: "queue.Queue[MultiBoardFrame]",
        writer: Any,
        state: Any,
        logger: Any,
        stop_event: threading.Event,
        *,
        clock: MultiBoardClock = SYSTEM_CLOCK,
    ) -> None:
        super().__init__(daemon=True, name="event_aggregator")
        self.boards = boards
        self.config = config
        self.frame_queue = frame_queue
        self.writer = writer
        self.state = state
        self.logger = logger
        self.stop_event = stop_event
        self._clock = clock
        self.expected_board_ids = [board.board_id for board in boards]
        self.expected_board_mask = mask_from_board_ids(self.expected_board_ids)
        self.event_timeout_s = config.event_timeout_ms / 1000.0
        self.next_seq = 1
        self.buckets: dict[int, _Bucket] = {}

    # ------------------------------------------------------------------- keys

    def _frame_key(self, frame: MultiBoardFrame) -> int:
        if self.config.aggregation_key == "event_count":
            return frame.event_count
        return frame.timestamp

    def _find_timestamp_bucket_key(self, timestamp: int) -> Optional[int]:
        for bucket_key in self.buckets.keys():
            if abs(bucket_key - timestamp) <= self.config.timestamp_match_window_ticks:
                return bucket_key
        return None

    # -------------------------------------------------------------------- run

    def run(self) -> None:
        while not self.stop_event.is_set() or not self.frame_queue.empty():
            self._flush_expired(force=False)
            try:
                frame = self.frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            self._handle_frame(frame)

        self._flush_expired(force=True)
        self.state.update_open_bucket_count(0)

    # -------------------------------------------------------------- handling

    def _handle_frame(self, frame: MultiBoardFrame) -> None:
        bucket_key = self._frame_key(frame)
        if self.config.aggregation_key == "timestamp":
            matched_key = self._find_timestamp_bucket_key(frame.timestamp)
            if matched_key is not None:
                bucket_key = matched_key
        bucket = self.buckets.get(bucket_key)
        if bucket is None:
            bucket = _Bucket(
                aggregation_value=self._frame_key(frame),
                timestamp=frame.timestamp,
                created_monotonic_s=self._clock.monotonic(),
                first_recv_unix_ns=frame.recv_unix_ns,
                frames={frame.board_id: frame},
            )
            self.buckets[bucket_key] = bucket
        else:
            previous = bucket.frames.get(frame.board_id)
            if previous is not None:
                self.logger.log(
                    "WARN",
                    "duplicate frame aggregation=%d board=%s old_event=%s new_event=%s"
                    % (
                        bucket_key,
                        frame.board_name,
                        str(previous.event_count),
                        str(frame.event_count),
                    ),
                )
            bucket.frames[frame.board_id] = frame

        self.state.update_open_bucket_count(len(self.buckets))
        if self._bucket_complete(bucket):
            event = self._finalize_bucket(bucket_key, complete=True)
            self.writer.write_event(event)
            self.state.record_complete_event(event)

    def _bucket_complete(self, bucket: _Bucket) -> bool:
        return len(bucket.frames) == len(self.expected_board_ids)

    def _flush_expired(self, force: bool) -> None:
        now_s = self._clock.monotonic()
        expired_keys = [
            bucket_key
            for bucket_key, bucket in self.buckets.items()
            if force or (now_s - bucket.created_monotonic_s) >= self.event_timeout_s
        ]

        for bucket_key in sorted(expired_keys):
            event = self._finalize_bucket(bucket_key, complete=False)
            self.writer.write_event(event)
            self.state.record_partial_event(event)
            self.logger.log(
                "WARN",
                "partial event aggregation=%d timestamp=%d missing=%s"
                % (
                    event.aggregation_value,
                    event.timestamp,
                    ",".join(str(item) for item in event.missing_board_ids),
                ),
            )

        if expired_keys:
            self.state.update_open_bucket_count(len(self.buckets))

    def _finalize_bucket(self, bucket_key: int, complete: bool) -> AggregatedEvent:
        bucket = self.buckets.pop(bucket_key)
        frames = bucket.frames
        present_ids = sorted(frames.keys())
        missing_ids = [
            board_id for board_id in self.expected_board_ids if board_id not in frames
        ]
        present_mask = mask_from_board_ids(present_ids)
        missing_mask = self.expected_board_mask & (~present_mask)
        status_flags = (
            EVENT_FLAG_COMPLETE
            if complete
            else (EVENT_FLAG_PARTIAL | EVENT_FLAG_TIMEOUT_FLUSH)
        )
        event_counts = {frame.event_count for frame in frames.values()}
        if len(event_counts) > 1:
            status_flags |= EVENT_FLAG_EVENT_COUNT_MISMATCH
        timestamps = [frame.timestamp for frame in frames.values()]

        event = AggregatedEvent(
            aggregate_seq=self.next_seq,
            aggregation_value=bucket_key,
            timestamp=min(timestamps) if timestamps else 0,
            created_unix_ns=bucket.first_recv_unix_ns,
            first_recv_unix_ns=bucket.first_recv_unix_ns,
            flush_unix_ns=self._clock.unix_ns(),
            frames=dict(frames),
            boards_present_mask=present_mask,
            boards_missing_mask=missing_mask,
            status_flags=status_flags,
            event_count_min=min(event_counts) if event_counts else 0,
            event_count_max=max(event_counts) if event_counts else 0,
            missing_board_ids=missing_ids,
        )
        self.next_seq += 1
        return event


__all__ = ["AggregatedEvent", "MultiBoardEventAggregator"]
