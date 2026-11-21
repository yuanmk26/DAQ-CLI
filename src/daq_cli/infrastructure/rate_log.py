"""Periodic event-rate logging for single-board acquisition.

The rate log is intentionally independent of the event payload storage: it
only samples a counter, so it also works in ``storage_mode="rate"`` where no
waveform files are written.
"""

from __future__ import annotations

import csv
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class RateSample:
    elapsed_s: float
    unix_time: float
    total_events: int
    window_events: int
    rate_hz: float


class RateLogRecorder:
    """Write ``rate.csv`` and ``monitor.jsonl`` at a fixed interval."""

    def __init__(
        self,
        csv_path: Path,
        jsonl_path: Path,
        interval_s: float,
        count_fn: Callable[[], int],
        *,
        metadata: dict[str, object] | None = None,
        log_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.csv_path = Path(csv_path)
        self.jsonl_path = Path(jsonl_path)
        self.log_path = Path(log_path) if log_path is not None else None
        self.interval_s = max(0.1, float(interval_s))
        self.count_fn = count_fn
        self.metadata = dict(metadata or {})
        self._clock = clock
        self._wall_clock = wall_clock

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._start_time = self._clock()
        self._last_time = self._start_time
        self._last_count = int(self.count_fn())
        self._total_events = self._last_count
        self._peak_rate_hz = 0.0
        self._sample_count = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False

        self._csv_fh = self.csv_path.open("w", encoding="utf-8", newline="")
        self._csv = csv.writer(self._csv_fh)
        self._csv.writerow(
            ["elapsed_s", "unix_time", "total_events", "window_events", "rate_hz"]
        )
        self._csv_fh.flush()
        self._jsonl_fh = self.jsonl_path.open("w", encoding="utf-8")
        self._log_fh = (
            self.log_path.open("a", encoding="utf-8")
            if self.log_path is not None
            else None
        )

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        # Emit the t=0 row so a plot starts at the origin.
        self.sample()
        self._thread = threading.Thread(
            target=self._loop, name="single_capture_rate_log", daemon=True
        )
        self._thread.start()

    def stop(self) -> RateSample:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        sample = self.sample()
        self.close()
        return sample

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._csv_fh.flush()
        self._csv_fh.close()
        self._jsonl_fh.close()
        if self._log_fh is not None:
            self._log_fh.close()

    def _loop(self) -> None:
        while not self._stop_event.wait(self.interval_s):
            self.sample()

    # --------------------------------------------------------------- sampling

    def sample(self) -> RateSample:
        now = self._clock()
        total = int(self.count_fn())
        elapsed = max(0.0, now - self._start_time)
        dt = now - self._last_time
        delta = max(0, total - self._last_count)
        rate = (delta / dt) if dt > 0 else 0.0

        sample = RateSample(
            elapsed_s=elapsed,
            unix_time=self._wall_clock(),
            total_events=total,
            window_events=delta,
            rate_hz=rate,
        )
        self._last_time = now
        self._last_count = total
        self._total_events = total
        self._peak_rate_hz = max(self._peak_rate_hz, rate)
        self._sample_count += 1

        self._csv.writerow(
            [
                f"{sample.elapsed_s:.3f}",
                f"{sample.unix_time:.6f}",
                sample.total_events,
                sample.window_events,
                f"{sample.rate_hz:.3f}",
            ]
        )
        self._csv_fh.flush()
        payload = {
            **self.metadata,
            "elapsed_s": round(sample.elapsed_s, 3),
            "unix_time": round(sample.unix_time, 6),
            "total_events": sample.total_events,
            "window_events": sample.window_events,
            "rate_hz": round(sample.rate_hz, 3),
        }
        self._jsonl_fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
        self._jsonl_fh.flush()
        if self._log_fh is not None:
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            suffix = ""
            device = str(self.metadata.get("device", ""))
            storage = str(self.metadata.get("storage_mode", ""))
            if device:
                suffix += f" device={device}"
            if storage:
                suffix += f" storage={storage}"
            self._log_fh.write(
                f"{stamp} [INFO] [MON] elapsed={sample.elapsed_s:.1f}s "
                f"total_events={sample.total_events} "
                f"window_events={sample.window_events} "
                f"rate={sample.rate_hz:.2f}Hz{suffix}\n"
            )
            self._log_fh.flush()
        return sample

    # ---------------------------------------------------------------- summary

    @property
    def duration_s(self) -> float:
        return max(0.0, self._clock() - self._start_time)

    @property
    def total_events(self) -> int:
        return self._total_events

    @property
    def peak_rate_hz(self) -> float:
        return self._peak_rate_hz

    @property
    def average_rate_hz(self) -> float:
        duration = self.duration_s
        return (self._total_events / duration) if duration > 0 else 0.0

    @property
    def sample_count(self) -> int:
        return self._sample_count


__all__ = ["RateLogRecorder", "RateSample"]
