"""Injectable time source.

Every wall-clock read in the native multi-board pipeline goes through a
:class:`MultiBoardClock`. Production uses :data:`SYSTEM_CLOCK`; tests inject a
fake so capture output (which embeds ``recv_unix_ns``, ``flush_unix_ns``,
monitor timestamps, ...) is byte-comparable against the vendored
implementation.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol


class MultiBoardClock(Protocol):
    def unix_ns(self) -> int:
        """Wall-clock nanoseconds since the Unix epoch."""

    def iso_now(self) -> str:
        """Local time formatted as ``%Y-%m-%dT%H:%M:%S%z``."""

    def monotonic(self) -> float:
        """Monotonic seconds, used for timeouts and interval pacing."""

    def sleep(self, seconds: float) -> None:
        """Sleep on the same timeline :meth:`monotonic` reports."""

    def local_timestamp(self) -> str:
        """Local time formatted as ``%Y%m%d_%H%M%S`` (run directory names)."""


class _SystemClock:
    __slots__ = ()

    def unix_ns(self) -> int:
        return time.time_ns()

    def iso_now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def local_timestamp(self) -> str:
        return time.strftime("%Y%m%d_%H%M%S", time.localtime())


SYSTEM_CLOCK: MultiBoardClock = _SystemClock()


class FakeClock:
    """Deterministic clock for tests.

    ``sleep`` advances the monotonic timeline, so timeout-driven behaviour
    (monitor ticks, bucket expiry) is reproducible without real waiting.
    """

    def __init__(
        self,
        *,
        start_unix_ns: int = 1_700_000_000_000_000_000,
        start_monotonic_s: float = 0.0,
        iso_now: str = "2026-01-01T00:00:00+0000",
        local_timestamp: str = "20260101_000000",
    ) -> None:
        self._unix_ns = int(start_unix_ns)
        self._monotonic_s = float(start_monotonic_s)
        self._iso_now = iso_now
        self._local_timestamp = local_timestamp
        self.sleeps: list[float] = []
        # Optional hook invoked after each sleep, e.g. to stop a thread.
        self.on_sleep: Callable[[float], None] | None = None

    def unix_ns(self) -> int:
        return self._unix_ns

    def iso_now(self) -> str:
        return self._iso_now

    def monotonic(self) -> float:
        return self._monotonic_s

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self._monotonic_s += float(seconds)
        self._unix_ns += int(float(seconds) * 1e9)
        if self.on_sleep is not None:
            self.on_sleep(float(seconds))

    def local_timestamp(self) -> str:
        return self._local_timestamp

    def advance(self, seconds: float) -> None:
        """Advance the timeline without recording a sleep."""
        self._monotonic_s += float(seconds)
        self._unix_ns += int(float(seconds) * 1e9)


__all__ = ["FakeClock", "MultiBoardClock", "SYSTEM_CLOCK"]
