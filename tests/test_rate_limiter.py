import pytest

from home_server.ble.rate_limiter import RateLimiter


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_first_emit_always_accepted() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock)
    assert limiter.should_emit("ch1") is True


def test_second_emit_within_interval_rejected() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock)
    limiter.should_emit("ch1")
    clock.advance(0.5)
    assert limiter.should_emit("ch1") is False


def test_emit_after_interval_accepted() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock)
    limiter.should_emit("ch1")
    clock.advance(1.0)
    assert limiter.should_emit("ch1") is True


def test_keys_are_independent() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock)
    assert limiter.should_emit("ch1") is True
    assert limiter.should_emit("ch2") is True
    clock.advance(0.1)
    assert limiter.should_emit("ch1") is False
    assert limiter.should_emit("ch2") is False


def test_reset_single_key() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock)
    limiter.should_emit("ch1")
    limiter.reset("ch1")
    assert limiter.should_emit("ch1") is True


def test_reset_all() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock)
    limiter.should_emit("ch1")
    limiter.should_emit("ch2")
    limiter.reset()
    assert limiter.should_emit("ch1") is True
    assert limiter.should_emit("ch2") is True


def test_zero_interval_always_emits() -> None:
    clock = FakeClock()
    limiter = RateLimiter(0.0, clock=clock)
    for _ in range(10):
        assert limiter.should_emit("ch1") is True


def test_negative_interval_rejected() -> None:
    with pytest.raises(ValueError):
        RateLimiter(-0.1)
