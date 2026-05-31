"""Select the BLE backend at startup.

bluepy only imports on Linux (the module raises ImportError elsewhere), so the
import is deferred into _load_bluepy() to keep this module importable anywhere.
"""

from __future__ import annotations

import logging

from home_server.ble.interface import BLEManager
from home_server.ble.mock_manager import MockBLEManager

log = logging.getLogger(__name__)


def select_ble_manager(backend: str, platform: str) -> BLEManager:
    if backend == "mock":
        return MockBLEManager()
    if backend == "bluepy":
        return _load_bluepy()
    if backend == "auto":
        if platform.startswith("linux"):
            try:
                return _load_bluepy()
            except ImportError:
                log.warning("bluepy unavailable; falling back to MockBLEManager")
                return MockBLEManager()
        return MockBLEManager()
    raise ValueError(f"unknown BLE backend: {backend!r}")


def _load_bluepy() -> BLEManager:
    from home_server.ble.bluepy_manager import BluepyManager

    return BluepyManager()
