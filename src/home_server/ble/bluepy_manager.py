"""Thread-safe BLEManager facade backed by ``bluepy`` (Linux only).

Each peripheral is driven by its own worker thread (see ``bluepy_worker``);
the public methods enqueue commands and block on the worker's ``Future``.
Reconnect logic lives in the service layer, not here.
"""

from __future__ import annotations

import sys
import threading

from .address import infer_addr_type
from .bluepy_worker import _PeripheralWorker
from .interface import ConnectionHandle, DiscoveredDevice, NotifyCallback

if sys.platform != "linux":
    raise ImportError("bluepy_manager is only supported on Linux")

from bluepy import btle  # noqa: E402  (import after platform check)

# --- Public facade ---


class BluepyManager:
    """Thread-safe BLEManager. Methods block on the per-peripheral worker."""

    def __init__(self, default_op_timeout_s: float = 10.0) -> None:
        self._workers: dict[str, _PeripheralWorker] = {}
        self._lock = threading.Lock()
        self._op_timeout_s = default_op_timeout_s

    # ---- BLEManager protocol ----

    def start_scan(self, duration_s: float) -> list[DiscoveredDevice]:
        scanner = btle.Scanner()
        entries = scanner.scan(duration_s)
        out: list[DiscoveredDevice] = []
        for e in entries:
            # ScanEntry.getValueText(9) = Complete Local Name (AD type 0x09).
            name = e.getValueText(9) or e.getValueText(8)
            out.append(
                DiscoveredDevice(
                    address=e.addr,
                    name=name,
                    rssi=e.rssi,
                    addr_type=e.addrType or infer_addr_type(e.addr),
                )
            )
        return out

    def connect(self, address: str, addr_type: str = "public") -> ConnectionHandle:
        worker, created = self._ensure_worker(address, addr_type)
        if created:
            # A new worker is awaited so callers (e.g. activate()) can subscribe
            # once connected. A reused worker returns immediately — the caller
            # polls is_connected() for the authoritative link state.
            worker.wait_until_connected(timeout=self._op_timeout_s)
        return address

    def disconnect(self, handle: ConnectionHandle) -> None:
        with self._lock:
            worker = self._workers.pop(handle, None)
        if worker is None:
            return
        try:
            worker.shutdown().result(timeout=self._op_timeout_s)
        finally:
            worker.join(timeout=self._op_timeout_s)

    def is_connected(self, handle: ConnectionHandle) -> bool:
        with self._lock:
            worker = self._workers.get(handle)
        return worker is not None and worker.is_connected()

    def read(self, handle: ConnectionHandle, char_uuid: str) -> bytes:
        worker = self._require_worker(handle)
        return worker.submit("read", char_uuid).result(timeout=self._op_timeout_s)

    def write(self, handle: ConnectionHandle, char_uuid: str, data: bytes) -> None:
        worker = self._require_worker(handle)
        worker.submit("write", char_uuid, data).result(timeout=self._op_timeout_s)

    def subscribe(
        self,
        handle: ConnectionHandle,
        char_uuid: str,
        callback: NotifyCallback,
    ) -> None:
        worker = self._require_worker(handle)
        worker.submit("subscribe", char_uuid, callback).result(timeout=self._op_timeout_s)

    def unsubscribe(self, handle: ConnectionHandle, char_uuid: str) -> None:
        worker = self._require_worker(handle)
        worker.submit("unsubscribe", char_uuid).result(timeout=self._op_timeout_s)

    # ---- Internal ----

    def _ensure_worker(
        self, address: str, addr_type: str
    ) -> tuple[_PeripheralWorker, bool]:
        """Return the live worker for ``address`` (creating+starting one if
        none is alive). The bool is True when a new worker was created."""
        with self._lock:
            existing = self._workers.get(address)
            if existing is not None and existing.is_alive():
                return existing, False
            worker = _PeripheralWorker(address, addr_type)
            worker.start()
            self._workers[address] = worker
            return worker, True

    def _require_worker(self, handle: ConnectionHandle) -> _PeripheralWorker:
        with self._lock:
            worker = self._workers.get(handle)
        if worker is None or not worker.is_connected():
            raise ConnectionError(f"Not connected: {handle}")
        return worker
