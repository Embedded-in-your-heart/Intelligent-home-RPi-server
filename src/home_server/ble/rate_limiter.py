"""Per-key minimum interval limiter.

Used to throttle DB writes from BLE Notify callbacks — UI gets every Notify
but persistence gets at most 1 per ``min_interval_s`` per channel.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        min_interval_s: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min_interval_s < 0:
            raise ValueError("min_interval_s must be non-negative")
        self._min_interval_s = min_interval_s
        self._clock = clock
        self._last_emit: dict[str, float] = {}

    def should_emit(self, key: str) -> bool:
        """Return True if enough time has elapsed since the last accepted emit
        for ``key``. Updates the bookkeeping when returning True.
        """
        now = self._clock()
        last = self._last_emit.get(key)
        if last is None or (now - last) >= self._min_interval_s:
            self._last_emit[key] = now
            return True
        return False

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._last_emit.clear()
        else:
            self._last_emit.pop(key, None)
