"""Device management: validate input, persist, drive BLE connection.

BLE operations call the BLEManager interface synchronously; the production
BluepyManager serializes each operation onto its per-peripheral worker thread,
so the service itself never touches threads.
"""

from __future__ import annotations

import logging
import re
import sqlite3

from home_server.ble.address import ADDR_TYPE_PUBLIC, ADDR_TYPE_RANDOM, infer_addr_type
from home_server.ble.interface import BLEManager, DiscoveredDevice
from home_server.db import devices
from home_server.db.devices import Device, DeviceNotFoundError

log = logging.getLogger(__name__)


class InvalidAddressError(ValueError):
    pass


_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


class DeviceService:
    def __init__(self, ble: BLEManager, scan_name_prefix: str = "HOME-") -> None:
        self._ble = ble
        self._scan_name_prefix = scan_name_prefix

    def scan(self, duration_s: float) -> list[DiscoveredDevice]:
        found = self._ble.start_scan(duration_s)
        # name is not None guard always applies; startswith("") is True for all strings,
        # so an empty prefix effectively disables prefix filtering (keeps all named devices).
        return [
            d
            for d in found
            if d.name is not None and d.name.startswith(self._scan_name_prefix)
        ]

    def add_device(
        self,
        conn: sqlite3.Connection,
        *,
        owner_user_id: int,
        address: str,
        name: str,
        addr_type: str | None = None,
    ) -> Device:
        if not _MAC_RE.match(address):
            raise InvalidAddressError(f"invalid BLE address: {address!r}")
        # Honour an explicit, valid addr_type; otherwise infer from the address.
        # Coercing unknown values (only reachable via a tampered request) avoids
        # an uncaught CHECK-constraint IntegrityError on insert.
        if addr_type in (ADDR_TYPE_PUBLIC, ADDR_TYPE_RANDOM):
            resolved_addr_type = addr_type
        else:
            resolved_addr_type = infer_addr_type(address)
        device_id = devices.create(
            conn,
            address=address,
            name=name,
            owner_user_id=owner_user_id,
            addr_type=resolved_addr_type,
        )
        # Best-effort initial connect; keep the device on failure for later retry.
        try:
            self._ble.connect(address, resolved_addr_type)
        except Exception:
            log.warning(
                "Initial connect to %s failed; device kept for later retry",
                address,
                exc_info=True,
            )
        device = devices.get_by_id(conn, device_id)
        assert device is not None
        return device

    def remove_device(self, conn: sqlite3.Connection, device_id: int) -> None:
        device = devices.get_by_id(conn, device_id)
        if device is None:
            raise DeviceNotFoundError(f"device not found: id={device_id}")
        if self._ble.is_connected(device.address):
            self._ble.disconnect(device.address)
        devices.delete(conn, device_id)

    def list_devices(self, conn: sqlite3.Connection) -> list[Device]:
        return devices.list_all(conn)

    def set_label(
        self, conn: sqlite3.Connection, device_id: int, label: str
    ) -> None:
        """Trim label; store None when empty. Raises DeviceNotFoundError if missing."""
        normalized: str | None = label.strip() or None
        device = devices.get_by_id(conn, device_id)
        if device is None:
            raise DeviceNotFoundError(f"device not found: id={device_id}")
        devices.set_label(conn, device_id, normalized)

    def is_connected(self, address: str) -> bool:
        return self._ble.is_connected(address)
