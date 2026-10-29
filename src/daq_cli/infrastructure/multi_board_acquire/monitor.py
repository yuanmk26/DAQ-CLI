"""Periodic monitor thread: console/log status lines plus monitor.jsonl."""

from __future__ import annotations

import threading
from typing import Any

from daq_cli.infrastructure.multi_board_acquire.clock import MultiBoardClock, SYSTEM_CLOCK
from daq_cli.infrastructure.multi_board_acquire.config import MultiBoardAppConfig
from daq_cli.infrastructure.multi_board_acquire.constants import pretty_secs


class MultiBoardMonitorThread(threading.Thread):
    def __init__(
        self,
        config: MultiBoardAppConfig,
        state: Any,
        writer: Any,
        logger: Any,
        stop_event: threading.Event,
        *,
        clock: MultiBoardClock = SYSTEM_CLOCK,
    ) -> None:
        super().__init__(daemon=True, name="monitor")
        self.config = config
        self.state = state
        self.writer = writer
        self.logger = logger
        self.stop_event = stop_event
        self._clock = clock
        self._last_jsonl_s = 0.0

    def run(self) -> None:
        last_tick = self._clock.monotonic()
        while not self.stop_event.is_set():
            self._clock.sleep(self.config.monitor_interval_s)
            if self.stop_event.is_set():
                return
            now_s = self._clock.monotonic()
            snapshot = self.state.snapshot()
            interval_s = max(now_s - last_tick, 1e-6)
            last_tick = now_s
            self.emit(snapshot, interval_s, now_s)
            self.state.reset_interval_counters()

    def emit(self, snapshot: dict, interval_s: float, now_s: float) -> dict:
        """Render one status tick; returns the JSON snapshot that was emitted.

        Pure with respect to threads: it only reads ``snapshot`` and writes via
        the injected logger/writer.
        """
        elapsed_s = now_s - float(snapshot["start_monotonic_s"])
        complete = int(snapshot["complete_events"])
        partial = int(snapshot["partial_events"])
        total = complete + partial
        partial_ratio = (float(partial) / float(total)) if total else 0.0
        open_buckets = int(snapshot["open_bucket_count"])
        last_complete_timestamp = int(snapshot["last_complete_timestamp"])
        last_complete_aggregation_value = int(
            snapshot["last_complete_aggregation_value"]
        )
        last_partial_missing = snapshot["last_partial_missing"]
        board_stats = snapshot["board_stats"]

        self.logger.log(
            "INFO",
            (
                "[MON] elapsed=%s complete=%d partial=%d partial_ratio=%.2f%% "
                "open_buckets=%d last_complete_key=%d last_complete_ts=%d"
                % (
                    pretty_secs(elapsed_s),
                    complete,
                    partial,
                    partial_ratio * 100.0,
                    open_buckets,
                    last_complete_aggregation_value,
                    last_complete_timestamp,
                )
            ),
        )
        if last_partial_missing:
            self.logger.log(
                "INFO",
                "[MON] last_partial_missing=%s"
                % ",".join(str(item) for item in last_partial_missing),
            )

        now_ns = self._clock.unix_ns()
        json_snapshot = {
            "ts": self._clock.iso_now(),
            "elapsed_s": elapsed_s,
            "complete_events": complete,
            "partial_events": partial,
            "partial_ratio": partial_ratio,
            "aggregation_key": self.config.aggregation_key,
            "timestamp_match_window_ticks": self.config.timestamp_match_window_ticks,
            "open_bucket_count": open_buckets,
            "last_complete_aggregation_value": last_complete_aggregation_value,
            "last_complete_timestamp": last_complete_timestamp,
            "last_partial_missing": last_partial_missing,
            "event_count_mismatches": int(snapshot["event_count_mismatches"]),
            "boards": {},
        }

        for board_id in sorted(board_stats.keys()):
            stat = board_stats[board_id]
            frames_since_last = int(stat["frames_since_last"])
            fps = float(frames_since_last) / interval_s
            name = str(stat["name"])
            connected = bool(stat["connected"])
            last_recv_ns = stat["last_recv_unix_ns"]
            silent_s = None
            if last_recv_ns is not None:
                silent_s = max(0.0, (now_ns - int(last_recv_ns)) / 1.0e9)
            warn_tokens = []
            if silent_s is not None and silent_s >= self.config.board_warn_no_data_s:
                warn_tokens.append("NO_DATA")
            if int(stat["reconnects"]) >= self.config.reconnect_warn_count:
                warn_tokens.append("RECONNECT")
            if partial_ratio >= self.config.partial_warn_ratio:
                warn_tokens.append("PARTIAL_RATIO")

            warn_suffix = ""
            if warn_tokens:
                warn_suffix = " warn=%s" % ",".join(warn_tokens)

            self.logger.log(
                "INFO",
                (
                    "[MON] %s conn=%s fps=%.1f total=%d last_ev=%s desync=%d "
                    "reconnect=%d silent=%s%s"
                    % (
                        name,
                        "up" if connected else "down",
                        fps,
                        int(stat["frames_total"]),
                        str(stat["last_event_count"]),
                        int(stat["desyncs"]),
                        int(stat["reconnects"]),
                        "n/a" if silent_s is None else pretty_secs(silent_s),
                        warn_suffix,
                    )
                ),
            )

            json_snapshot["boards"][name] = {
                "board_id": board_id,
                "connected": connected,
                "fps": fps,
                "frames_total": int(stat["frames_total"]),
                "last_event_count": stat["last_event_count"],
                "desyncs": int(stat["desyncs"]),
                "reconnects": int(stat["reconnects"]),
                "recv_errors": int(stat["recv_errors"]),
                "silent_s": silent_s,
                "warn_tokens": warn_tokens,
            }

        if now_s - self._last_jsonl_s >= self.config.monitor_jsonl_interval_s:
            self.writer.write_monitor_snapshot(json_snapshot)
            self._last_jsonl_s = now_s

        return json_snapshot


__all__ = ["MultiBoardMonitorThread"]
