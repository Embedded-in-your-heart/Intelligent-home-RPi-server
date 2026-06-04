"""Unit tests for PeriodicWorker."""

import time

from home_server.core.periodic import PeriodicWorker


def test_start_then_stop_lifecycle() -> None:
    worker = PeriodicWorker(lambda: None, interval_s=0.01, name="test-worker")
    worker.start()
    time.sleep(0.05)
    assert worker.is_running()
    worker.stop()
    assert not worker.is_running()
    assert worker._thread is None


def test_tick_actually_runs() -> None:
    counter: list[int] = [0]

    def tick() -> None:
        counter[0] += 1

    worker = PeriodicWorker(tick, interval_s=0.01, name="test-counter")
    worker.start()
    time.sleep(0.1)
    worker.stop()
    assert counter[0] >= 1


def test_start_is_idempotent() -> None:
    worker = PeriodicWorker(lambda: None, interval_s=0.01, name="test-idempotent")
    worker.start()
    thread_before = worker._thread
    worker.start()  # second call must be a no-op
    assert worker._thread is thread_before
    worker.stop()


def test_stop_without_start_is_safe() -> None:
    worker = PeriodicWorker(lambda: None, interval_s=0.01, name="test-no-start")
    worker.stop()  # must not raise
    assert not worker.is_running()


def test_stop_twice_is_safe() -> None:
    worker = PeriodicWorker(lambda: None, interval_s=0.01, name="test-double-stop")
    worker.start()
    worker.stop()
    worker.stop()  # must not raise
    assert not worker.is_running()


def test_tick_exception_does_not_kill_worker() -> None:
    """A tick that raises on the first call must not stop subsequent ticks."""
    calls: list[int] = [0]

    def tick() -> None:
        calls[0] += 1
        if calls[0] == 1:
            raise ValueError("simulated tick error")

    worker = PeriodicWorker(tick, interval_s=0.01, name="test-resilient")
    worker.start()
    time.sleep(0.15)
    worker.stop()
    # Worker survived the first-tick exception and ran more ticks.
    assert calls[0] >= 2
