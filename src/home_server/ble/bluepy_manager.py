"""Thread-safe BLEManager facade backed by ``bluepy`` (Linux only).

Each peripheral is driven by its own worker thread (see ``bluepy_worker``);
the public methods enqueue commands and block on the worker's ``Future``.
Reconnect logic lives in the service layer, not here.
"""

from __future__ import annotations

import logging
import sys
import threading

from .address import infer_addr_type
from .bluepy_worker import _PeripheralWorker
from .interface import ConnectionHandle, DiscoveredDevice, NotifyCallback

if sys.platform != "linux":
    raise ImportError("bluepy_manager is only supported on Linux")

from bluepy import btle  # noqa: E402  (import after platform check)

log = logging.getLogger(__name__)

# --- Public facade ---


class BluepyManager:
    """Thread-safe BLEManager. Methods block on the per-peripheral worker."""

    def __init__(self, default_op_timeout_s: float = 10.0) -> None:
        self._workers: dict[str, _PeripheralWorker] = {}
        self._lock = threading.Lock()
        self._op_timeout_s = default_op_timeout_s

    # ---- BLEManager protocol ----

    def start_scan(self, duration_s: float) -> list[DiscoveredDevice]:
        # Even with peripherals disconnected for the scan window, bluepy's
        # Scanner.stop() (mgmt "scanend") can intermittently observe a stale
        # disconnect event and raise. Retry once before giving up; the caller
        # turns a second failure into a recoverable message, not a 500.
        try:
            entries = btle.Scanner().scan(duration_s)
        except btle.BTLEDisconnectError:
            log.warning("BLE scan interrupted by a disconnect event; retrying once")
            entries = btle.Scanner().scan(duration_s)
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
        worker = self._ensure_worker(address, addr_type)
        # Block until the link is up (or raise on failure/timeout) so callers
        # like activate() can subscribe immediately afterwards.
        worker.wait_until_connected(timeout=self._op_timeout_s)
        return address

    def ensure_connecting(self, address: str, addr_type: str = "public") -> None:
        # Non-blocking: spin up (or reuse) the worker and return at once. The
        # reconnect monitor polls is_connected() instead of waiting here, so a
        # slow/unreachable peer never stalls it.
        self._ensure_worker(address, addr_type)

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

    def _ensure_worker(self, address: str, addr_type: str) -> _PeripheralWorker:
        """Return the live worker for ``address``, creating+starting one if
        none is currently alive."""
        with self._lock:
            existing = self._workers.get(address)
            if existing is not None and existing.is_alive():
                return existing
            worker = _PeripheralWorker(address, addr_type)
            worker.start()
            self._workers[address] = worker
            return worker

    def _require_worker(self, handle: ConnectionHandle) -> _PeripheralWorker:
        with self._lock:
            worker = self._workers.get(handle)
        if worker is None or not worker.is_connected():
            raise ConnectionError(f"Not connected: {handle}")
        return worker
