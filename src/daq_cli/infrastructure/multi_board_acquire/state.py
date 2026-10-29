"""Shared run state and the run log."""

from __future__ import annotations

import threading
from pathlib import Path

from daq_cli.infrastructure.multi_board_acquire.clock import MultiBoardClock, SYSTEM_CLOCK
from daq_cli.infrastructure.multi_board_acquire.config import MultiBoardConfig
from daq_cli.infrastructure.multi_board_acquire.constants import (
    EVENT_FLAG_EVENT_COUNT_MISMATCH,
)
from daq_cli.infrastructure.multi_board_acquire.frames import MultiBoardFrame

# Keys of the per-board stat dict. ``fps`` and ``warn_no_data_latched`` existed
# in the legacy state but were never read for output (fps is recomputed by the
# monitor from frames_since_last), so they are not carried over.
_BOARD_STAT_DEFAULTS = {
    "connected": False,
    "reconnects": 0,
    "desyncs": 0,
    "frames_total": 0,
    "frames_since_last": 0,
    "last_event_count": None,
    "last_recv_unix_ns": None,
    "last_connect_unix_ns": None,
    "last_disconnect_unix_ns": None,
    "recv_errors": 0,
}


class EventLog:
    """Run log: every line goes to stdout and to ``<run_dir>/log.txt``."""

    def __init__(self, log_path: str | Path, *, clock: MultiBoardClock = SYSTEM_CLOCK) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._fh = open(log_path, "a", encoding="utf-8")
        self._closed = False

    def log(self, level: str, message: str) -> None:
        line = "%s [%s] %s" % (self._clock.iso_now(), level, message)
        with self._lock:
            print(line)
            if not self._closed:
                self._fh.write(line + "\n")
                self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._fh.flush()
            self._fh.close()
            self._closed = True


class MultiBoardSharedState:
    """Counters and per-board statistics read by the monitor thread."""

    def __init__(
        self,
        boards: list[MultiBoardConfig],
        *,
        clock: MultiBoardClock = SYSTEM_CLOCK,
    ) -> None:
        self.lock = threading.Lock()
        self._clock = clock
        self.start_monotonic_s = clock.monotonic()
        self.run_started_unix_ns = clock.unix_ns()

        self.complete_events = 0
        self.partial_events = 0
        self.event_count_mismatches = 0
        self.last_complete_timestamp = 0
        self.last_complete_aggregation_value = 0
        self.last_partial_missing: list[int] = []
        self.open_bucket_count = 0

        self.board_stats: dict[int, dict[str, object]] = {}
        for board in boards:
            self.board_stats[board.board_id] = {
                "board_id": board.board_id,
                "name": board.name,
                "ip": board.ip,
                **_BOARD_STAT_DEFAULTS,
            }

    # ------------------------------------------------------------ board stats

    def mark_connected(self, board_id: int) -> None:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["connected"] = True
            stat["last_connect_unix_ns"] = self._clock.unix_ns()

    def mark_disconnected(self, board_id: int) -> None:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["connected"] = False
            stat["last_disconnect_unix_ns"] = self._clock.unix_ns()

    def mark_reconnect(self, board_id: int) -> int:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["reconnects"] = int(stat["reconnects"]) + 1
            return int(stat["reconnects"])

    def mark_desync(self, board_id: int) -> None:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["desyncs"] = int(stat["desyncs"]) + 1

    def mark_recv_error(self, board_id: int) -> None:
        with self.lock:
            stat = self.board_stats[board_id]
            stat["recv_errors"] = int(stat["recv_errors"]) + 1

    def record_frame(self, frame: MultiBoardFrame) -> None:
        with self.lock:
            stat = self.board_stats[frame.board_id]
            stat["frames_total"] = int(stat["frames_total"]) + 1
            stat["frames_since_last"] = int(stat["frames_since_last"]) + 1
            stat["last_event_count"] = frame.event_count
            stat["last_recv_unix_ns"] = frame.recv_unix_ns

    # ------------------------------------------------------- aggregate counters

    def update_open_bucket_count(self, count: int) -> None:
        with self.lock:
            self.open_bucket_count = count

    def record_complete_event(self, event) -> None:
        with self.lock:
            self.complete_events += 1
            self.last_complete_timestamp = event.timestamp
            self.last_complete_aggregation_value = event.aggregation_value
            if event.status_flags & EVENT_FLAG_EVENT_COUNT_MISMATCH:
                self.event_count_mismatches += 1

    def record_partial_event(self, event) -> None:
        with self.lock:
            self.partial_events += 1
            self.last_partial_missing = list(event.missing_board_ids)
            if event.status_flags & EVENT_FLAG_EVENT_COUNT_MISMATCH:
                self.event_count_mismatches += 1

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            board_stats_copy = {
                board_id: dict(stat) for board_id, stat in self.board_stats.items()
            }
            return {
                "start_monotonic_s": self.start_monotonic_s,
                "run_started_unix_ns": self.run_started_unix_ns,
                "complete_events": self.complete_events,
                "partial_events": self.partial_events,
                "event_count_mismatches": self.event_count_mismatches,
                "last_complete_timestamp": self.last_complete_timestamp,
                "last_complete_aggregation_value": self.last_complete_aggregation_value,
                "last_partial_missing": list(self.last_partial_missing),
                "open_bucket_count": self.open_bucket_count,
                "board_stats": board_stats_copy,
            }

    def reset_interval_counters(self) -> None:
        with self.lock:
            for stat in self.board_stats.values():
                stat["frames_since_last"] = 0


__all__ = ["EventLog", "MultiBoardSharedState"]
