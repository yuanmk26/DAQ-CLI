"""GUI background-task helpers.

This module is deliberately tkinter-free: the caller injects a `schedule`
callback (typically ``root.after``) so the marshalling logic can be unit
tested without a display.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_Result = tuple[str, object]  # ("ok", value) | ("error", exception)


def run_in_background(
    *,
    fn: Callable[[], T],
    on_done: Callable[[T], None],
    on_error: Callable[[BaseException], None],
    schedule: Callable[[Callable[[], None]], None],
) -> threading.Thread:
    """Run ``fn`` on a daemon thread and marshal its outcome back to the
    GUI thread.

    - ``schedule`` must run its argument on the GUI thread at some later
      point (pass ``root.after(50, cb)``-style callables).
    - ``on_done(result)`` / ``on_error(exception)`` are invoked exactly once,
      on the GUI thread.
    - The returned thread is informational (e.g. for join on shutdown); the
      callbacks are the actual delivery mechanism.
    """

    result_queue: "queue.Queue[_Result]" = queue.Queue(maxsize=1)

    def poll_once() -> None:
        try:
            kind, payload = result_queue.get_nowait()
        except queue.Empty:
            schedule(poll_once)
            return
        if kind == "error":
            on_error(payload)  # type: ignore[arg-type]
        else:
            on_done(payload)  # type: ignore[arg-type]

    def worker() -> None:
        try:
            result = fn()
        except BaseException as exc:  # noqa: BLE001 - marshalled to the GUI
            result_queue.put(("error", exc))
        else:
            result_queue.put(("ok", result))
        finally:
            schedule(poll_once)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def drain_queue(queue_: "queue.Queue[Any]") -> list[Any]:
    """Non-blocking drain of a queue into a list (oldest first)."""
    items: list[Any] = []
    while True:
        try:
            items.append(queue_.get_nowait())
        except queue.Empty:
            return items
