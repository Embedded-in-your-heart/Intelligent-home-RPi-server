"""In-memory BLEManager for tests and Windows development.

Test code arranges:
    mock.scan_results = [DiscoveredDevice(...)]
    mock.set_read_value(addr, uuid, b"...")
    mock.simulate_notify(addr, uuid, b"...")

…then inspects ``mock.writes`` afterwards to assert what was sent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from home_server.core.periodic import PeriodicWorker

from .interface import ConnectionHandle, DiscoveredDevice, NotifyCallback


class MockBLEError(Exception):
    pass


@dataclass
class MockBLEManager:
    scan_results: list[DiscoveredDevice] = field(default_factory=list)
    fail_connect_for: set[str] = field(default_factory=set)

    # Populated by test code via set_read_value(); read() pops from here.
    _read_values: dict[tuple[str, str], list[bytes]] = field(default_factory=dict)

    # All write() calls recorded in order; tests assert on this.
    writes: list[tuple[str, str, bytes]] = field(default_factory=list)

    _connected: set[str] = field(default_factory=set)
    _subscriptions: dict[tuple[str, str], NotifyCallback] = field(default_factory=dict)
    scan_calls: list[float] = field(default_factory=list)
    connect_calls: list[tuple[str, str]] = field(default_factory=list)

    # Dev-only synthetic producer (see start()/stop()). Not part of equality.
    _producer: PeriodicWorker | None = field(default=None, compare=False, repr=False)

    # ---- BLEManager protocol ----

    def start_scan(self, duration_s: float) -> list[DiscoveredDevice]:
        self.scan_calls.append(duration_s)
        return list(self.scan_results)

    def connect(
        self, address: str, addr_type: str = "public"
    ) -> ConnectionHandle:
        self.connect_calls.append((address, addr_type))
        if address in self.fail_connect_for:
            raise MockBLEError(f"Mocked connect failure for {address}")
        self._connected.add(address)
        return address

    def disconnect(self, handle: ConnectionHandle) -> None:
        self._connected.discard(handle)
        # Drop subscriptions tied to this handle.
        for key in [k for k in self._subscriptions if k[0] == handle]:
            del self._subscriptions[key]

    def is_connected(self, handle: ConnectionHandle) -> bool:
        return handle in self._connected

    def read(self, handle: ConnectionHandle, char_uuid: str) -> bytes:
        self._require_connected(handle)
        queue = self._read_values.get((handle, char_uuid))
        if not queue:
            raise MockBLEError(
                f"No mock read value queued for ({handle}, {char_uuid}). "
                f"Call set_read_value() first."
            )
        # If only one value queued, keep returning it; otherwise pop FIFO.
        if len(queue) == 1:
            return queue[0]
        return queue.pop(0)

    def write(self, handle: ConnectionHandle, char_uuid: str, data: bytes) -> None:
        self._require_connected(handle)
        self.writes.append((handle, char_uuid, data))

    def subscribe(
        self,
        handle: ConnectionHandle,
        char_uuid: str,
        callback: NotifyCallback,
    ) -> None:
        self._require_connected(handle)
        self._subscriptions[(handle, char_uuid)] = callback

    def unsubscribe(self, handle: ConnectionHandle, char_uuid: str) -> None:
        self._subscriptions.pop((handle, char_uuid), None)

    # ---- Dev-only synthetic producer ----

    def start(
        self, feed: Callable[[str, str], bytes | None], interval_s: float = 1.0
    ) -> None:
        """Begin emitting synthetic notifications to active subscribers.

        ``feed(address, char_uuid)`` returns the bytes to deliver, or None to
        skip that subscription this tick. Dev/demo use only — tests drive
        notifications synchronously via simulate_notify().
        """
        if self._producer is not None:
            return
        self._producer = PeriodicWorker(
            lambda: self._tick(feed),
            interval_s=interval_s,
            name="mock-ble-producer",
        )
        self._producer.start()

    def stop(self) -> None:
        if self._producer is not None:
            self._producer.stop()
            self._producer = None

    def _tick(self, feed: Callable[[str, str], bytes | None]) -> None:
        for (address, char_uuid), callback in list(self._subscriptions.items()):
            data = feed(address, char_uuid)
            if data is not None:
                callback(data)

    # ---- Test helpers ----

    def set_read_value(self, address: str, char_uuid: str, data: bytes) -> None:
        """Queue (or replace) the value returned on next read()."""
        self._read_values[(address, char_uuid)] = [data]

    def queue_read_values(self, address: str, char_uuid: str, values: list[bytes]) -> None:
        """Queue a sequence of read responses (consumed FIFO)."""
        self._read_values[(address, char_uuid)] = list(values)

    def simulate_notify(self, handle: ConnectionHandle, char_uuid: str, data: bytes) -> None:
        """Invoke the subscribed callback as if a Notify packet arrived."""
        callback = self._subscriptions.get((handle, char_uuid))
        if callback is None:
            raise MockBLEError(
                f"No subscriber for ({handle}, {char_uuid}); call subscribe() first."
            )
        callback(data)

    def simulate_disconnect(self, handle: ConnectionHandle) -> None:
        """Mark handle as disconnected without going through disconnect() —
        useful for testing reconnect logic."""
        self._connected.discard(handle)

    def writes_for(self, address: str, char_uuid: str) -> list[bytes]:
        return [d for (h, u, d) in self.writes if h == address and u == char_uuid]

    # ---- Internal ----

    def _require_connected(self, handle: ConnectionHandle) -> None:
        if handle not in self._connected:
            raise MockBLEError(f"Not connected: {handle}")
