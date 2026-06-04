"""Reusable background poller: run a callable on a daemon thread at a fixed interval."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class PeriodicWorker:
    """Run ``tick`` on a daemon thread every ``interval_s`` until stopped.

    Exceptions raised by ``tick`` are logged and the loop continues, so one bad
    tick never kills the worker. ``start()`` and ``stop()`` are both idempotent.
    """

    def __init__(
        self, tick: Callable[[], None], *, interval_s: float, name: str
    ) -> None:
        self._tick = tick
        self._interval_s = interval_s
        self._name = name
        self._thread: threading.Thread | None = None
        self._stop: threading.Event | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        stop = threading.Event()

        def _run() -> None:
            while not stop.wait(self._interval_s):
                try:
                    self._tick()
                except Exception:
                    log.exception("%s tick failed", self._name)

        thread = threading.Thread(target=_run, name=self._name, daemon=True)
        self._stop = stop
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._stop = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
