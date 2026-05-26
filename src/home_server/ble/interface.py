"""BLE manager abstraction.

The Protocol defined here lets the rest of the app stay independent of
`bluepy`, which only runs on Linux. Tests use ``MockBLEManager``; production
on the RPi uses ``BluepyManager``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

NotifyCallback = Callable[[bytes], None]


@dataclass(frozen=True)
class DiscoveredDevice:
    address: str
    name: str | None
    rssi: int


# ConnectionHandle is just the device address — the manager keeps the
# Peripheral instance internally. Keeping this as a plain str avoids exposing
# bluepy types in the interface.
ConnectionHandle = str


@runtime_checkable
class BLEManager(Protocol):
    def start_scan(self, duration_s: float) -> list[DiscoveredDevice]:
        """Block for ``duration_s`` and return all advertising devices seen."""
        ...

    def connect(self, address: str) -> ConnectionHandle:
        """Establish a GATT connection. Raises if the peer is unreachable."""
        ...

    def disconnect(self, handle: ConnectionHandle) -> None: ...

    def is_connected(self, handle: ConnectionHandle) -> bool: ...

    def read(self, handle: ConnectionHandle, char_uuid: str) -> bytes: ...

    def write(self, handle: ConnectionHandle, char_uuid: str, data: bytes) -> None: ...

    def subscribe(
        self,
        handle: ConnectionHandle,
        char_uuid: str,
        callback: NotifyCallback,
    ) -> None:
        """Enable notifications. ``callback`` is invoked from the BLE worker thread."""
        ...

    def unsubscribe(self, handle: ConnectionHandle, char_uuid: str) -> None: ...
