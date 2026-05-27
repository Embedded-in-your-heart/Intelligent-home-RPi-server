"""Production BLEManager backed by ``bluepy`` (Linux only).

Each connected peripheral runs in its own worker thread, because a bluepy
``Peripheral`` owns a ``bluepy-helper`` subprocess and isn't safe to share
across threads. The public methods enqueue commands onto the per-peripheral
queue and block on a ``Future`` for the result. Notify callbacks fire from
inside the worker thread.

Reconnect logic lives in the service layer, not here — this class just
exposes a clean BLE API and reports connection state.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from .interface import ConnectionHandle, DiscoveredDevice, NotifyCallback

if sys.platform != "linux":
    raise ImportError("bluepy_manager is only supported on Linux")

from bluepy import btle  # noqa: E402  (import after platform check)

log = logging.getLogger(__name__)

_NOTIFY_POLL_INTERVAL_S = 0.5


# --- Commands sent to per-peripheral worker thread ---


@dataclass
class _Cmd:
    op: str  # "read" | "write" | "subscribe" | "unsubscribe" | "shutdown"
    args: tuple[Any, ...] = ()
    future: Future[Any] | None = None


# --- Notify delegate: bluepy calls handleNotification on this object ---


class _NotifyDelegate(btle.DefaultDelegate):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        # handle (int from bluepy) -> (char_uuid, user callback)
        self._by_handle: dict[int, tuple[str, NotifyCallback]] = {}

    def register(self, ble_handle: int, char_uuid: str, callback: NotifyCallback) -> None:
        self._by_handle[ble_handle] = (char_uuid, callback)

    def unregister(self, ble_handle: int) -> None:
        self._by_handle.pop(ble_handle, None)

    def handleNotification(self, cHandle: int, data: bytes) -> None:  # noqa: N803
        entry = self._by_handle.get(cHandle)
        if entry is None:
            log.debug("Notify on unregistered handle %d", cHandle)
            return
        _uuid, callback = entry
        try:
            callback(bytes(data))
        except Exception:
            log.exception("Notify callback raised")


# --- One worker thread per peripheral ---


class _PeripheralWorker(threading.Thread):
    def __init__(self, address: str) -> None:
        super().__init__(name=f"ble-worker-{address}", daemon=True)
        self.address = address
        self._queue: queue.Queue[_Cmd] = queue.Queue()
        self._peripheral: btle.Peripheral | None = None
        self._delegate = _NotifyDelegate()
        self._char_cache: dict[str, btle.Characteristic] = {}
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._connect_future: Future[None] = Future()

    # ---- Public (called from facade) ----

    def wait_until_connected(self, timeout: float = 30.0) -> None:
        self._connect_future.result(timeout=timeout)

    def is_connected(self) -> bool:
        return self._connected.is_set()

    def submit(self, op: str, *args: Any) -> Future[Any]:
        fut: Future[Any] = Future()
        self._queue.put(_Cmd(op=op, args=args, future=fut))
        return fut

    def shutdown(self) -> Future[Any]:
        return self.submit("shutdown")

    # ---- Worker loop ----

    def run(self) -> None:
        try:
            self._peripheral = btle.Peripheral(self.address, addrType=btle.ADDR_TYPE_PUBLIC)
            self._peripheral.withDelegate(self._delegate)
            self._connected.set()
            self._connect_future.set_result(None)
            log.info("Connected to %s", self.address)
        except Exception as e:
            log.warning("Connect to %s failed: %s", self.address, e)
            self._connect_future.set_exception(e)
            return

        try:
            self._loop()
        finally:
            self._connected.clear()
            if self._peripheral is not None:
                try:
                    self._peripheral.disconnect()
                except Exception:
                    log.debug("Disconnect cleanup raised", exc_info=True)
            log.info("Worker for %s exited", self.address)

    def _loop(self) -> None:
        assert self._peripheral is not None
        while not self._stop.is_set():
            # Process pending commands first.
            try:
                cmd = self._queue.get_nowait()
            except queue.Empty:
                cmd = None

            if cmd is not None:
                self._handle_command(cmd)
                continue

            # Poll for notifications. waitForNotifications returns True if one
            # was handled; either way we loop again.
            try:
                self._peripheral.waitForNotifications(_NOTIFY_POLL_INTERVAL_S)
            except btle.BTLEDisconnectError:
                log.warning("Peripheral %s disconnected", self.address)
                self._stop.set()
                # Fail any remaining queued commands.
                self._drain_with_error(ConnectionError("peripheral disconnected"))
                return

    def _handle_command(self, cmd: _Cmd) -> None:
        assert self._peripheral is not None
        try:
            if cmd.op == "shutdown":
                self._stop.set()
                result: Any = None
            elif cmd.op == "read":
                (char_uuid,) = cmd.args
                result = bytes(self._char(char_uuid).read())
            elif cmd.op == "write":
                char_uuid, data = cmd.args
                self._char(char_uuid).write(data, withResponse=True)
                result = None
            elif cmd.op == "subscribe":
                char_uuid, callback = cmd.args
                self._enable_notify(char_uuid, callback)
                result = None
            elif cmd.op == "unsubscribe":
                (char_uuid,) = cmd.args
                self._disable_notify(char_uuid)
                result = None
            else:
                raise ValueError(f"Unknown op: {cmd.op}")
        except Exception as e:
            if cmd.future is not None:
                cmd.future.set_exception(e)
            return
        if cmd.future is not None:
            cmd.future.set_result(result)

    def _char(self, uuid: str) -> btle.Characteristic:
        assert self._peripheral is not None
        cached = self._char_cache.get(uuid)
        if cached is not None:
            return cached
        chars = self._peripheral.getCharacteristics(uuid=uuid)
        if not chars:
            raise ValueError(f"Characteristic {uuid} not found on {self.address}")
        self._char_cache[uuid] = chars[0]
        return chars[0]

    def _enable_notify(self, char_uuid: str, callback: NotifyCallback) -> None:
        assert self._peripheral is not None
        char = self._char(char_uuid)
        # Write 0x0001 to the CCCD (handle = char value handle + 1) to turn on Notify.
        cccd_handle = char.getHandle() + 1
        self._peripheral.writeCharacteristic(cccd_handle, b"\x01\x00", withResponse=True)
        self._delegate.register(char.getHandle(), char_uuid, callback)

    def _disable_notify(self, char_uuid: str) -> None:
        assert self._peripheral is not None
        char = self._char(char_uuid)
        cccd_handle = char.getHandle() + 1
        try:
            self._peripheral.writeCharacteristic(cccd_handle, b"\x00\x00", withResponse=True)
        except btle.BTLEException:
            log.debug("Disabling notify on %s raised", char_uuid, exc_info=True)
        self._delegate.unregister(char.getHandle())

    def _drain_with_error(self, exc: Exception) -> None:
        while True:
            try:
                cmd = self._queue.get_nowait()
            except queue.Empty:
                return
            if cmd.future is not None:
                cmd.future.set_exception(exc)


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
            out.append(DiscoveredDevice(address=e.addr, name=name, rssi=e.rssi))
        return out

    def connect(self, address: str) -> ConnectionHandle:
        with self._lock:
            existing = self._workers.get(address)
            if existing is not None and existing.is_alive():
                return address
            worker = _PeripheralWorker(address)
            worker.start()
            self._workers[address] = worker
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

    def _require_worker(self, handle: ConnectionHandle) -> _PeripheralWorker:
        with self._lock:
            worker = self._workers.get(handle)
        if worker is None or not worker.is_connected():
            raise ConnectionError(f"Not connected: {handle}")
        return worker
