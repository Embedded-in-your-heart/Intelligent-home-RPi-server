"""Per-peripheral bluepy worker thread (Linux only).

Each connected peripheral runs in its own worker thread, because a bluepy
``Peripheral`` owns a ``bluepy-helper`` subprocess and isn't safe to share
across threads. Public methods enqueue commands onto the per-peripheral queue
and block on a ``Future``; notify callbacks fire from inside the worker thread.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from .interface import NotifyCallback

if sys.platform != "linux":
    raise ImportError("bluepy worker is only supported on Linux")

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


class _NotifyDelegate(btle.DefaultDelegate):
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
    def __init__(
        self,
        address: str,
        addr_type: str = "public",
        *,
        adapter_lock: threading.Lock,
    ) -> None:
        super().__init__(name=f"ble-worker-{address}", daemon=True)
        self.address = address
        self._addr_type = addr_type
        self._adapter_lock = adapter_lock
        self._queue: queue.Queue[_Cmd] = queue.Queue()
        self._peripheral: btle.Peripheral | None = None
        self._delegate = _NotifyDelegate()
        self._char_cache: dict[str, btle.Characteristic] = {}
        self._connected = threading.Event()
        # NOTE: must NOT be named ``_stop`` — that shadows threading.Thread._stop(),
        # which CPython calls internally from is_alive()/join() once the thread has
        # terminated, raising "TypeError: 'Event' object is not callable".
        self._stop_event = threading.Event()
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
            # Hold the adapter lock only around the blocking connect attempt.
            # bluepy scanning and a pending LE Create Connection cannot share
            # the hci adapter; BlueZ rejects mgmt commands with "Rejected" if
            # both are in flight at once.  Releasing the lock immediately after
            # btle.Peripheral() returns lets the command loop and disconnect
            # cleanup proceed without blocking the scanner.
            with self._adapter_lock:
                self._peripheral = btle.Peripheral(self.address, addrType=self._addr_type)
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
        while not self._stop_event.is_set():
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
                self._stop_event.set()
                # Fail any remaining queued commands.
                self._drain_with_error(ConnectionError("peripheral disconnected"))
                return

    def _handle_command(self, cmd: _Cmd) -> None:
        assert self._peripheral is not None
        try:
            if cmd.op == "shutdown":
                self._stop_event.set()
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
