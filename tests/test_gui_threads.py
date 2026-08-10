import queue
import unittest

from daq_cli.presentation.gui.threads import drain_queue, run_in_background


class FakeScheduler:
    """Captures scheduled callbacks so tests can run them synchronously."""

    def __init__(self) -> None:
        self.pending: list = []

    def __call__(self, callback) -> None:
        self.pending.append(callback)

    def run_pending(self) -> None:
        while self.pending:
            callback = self.pending.pop(0)
            callback()


class BackgroundTaskTests(unittest.TestCase):
    def test_result_is_delivered_on_done(self) -> None:
        scheduler = FakeScheduler()
        done: list = []
        errors: list = []
        thread = run_in_background(
            fn=lambda: 42,
            on_done=done.append,
            on_error=errors.append,
            schedule=scheduler,
        )
        thread.join(timeout=2.0)
        scheduler.run_pending()
        self.assertEqual(done, [42])
        self.assertEqual(errors, [])

    def test_exception_is_delivered_on_error(self) -> None:
        scheduler = FakeScheduler()
        done: list = []
        errors: list = []

        def boom() -> None:
            raise RuntimeError("boom")

        thread = run_in_background(
            fn=boom,
            on_done=done.append,
            on_error=errors.append,
            schedule=scheduler,
        )
        thread.join(timeout=2.0)
        scheduler.run_pending()
        self.assertEqual(done, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(str(errors[0]), "boom")

    def test_callbacks_are_called_exactly_once(self) -> None:
        scheduler = FakeScheduler()
        calls: list = []
        thread = run_in_background(
            fn=lambda: "ok",
            on_done=lambda result: calls.append(result),
            on_error=lambda exc: calls.append(exc),
            schedule=scheduler,
        )
        thread.join(timeout=2.0)
        scheduler.run_pending()
        # poll_once must not be re-scheduled after delivery
        scheduler.run_pending()
        self.assertEqual(calls, ["ok"])

    def test_drain_queue_returns_oldest_first(self) -> None:
        source: "queue.Queue[int]" = queue.Queue()
        source.put(1)
        source.put(2)
        self.assertEqual(drain_queue(source), [1, 2])
        self.assertTrue(source.empty())


if __name__ == "__main__":
    unittest.main()
