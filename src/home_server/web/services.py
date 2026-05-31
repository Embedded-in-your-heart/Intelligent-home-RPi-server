"""Typed accessors for app-scoped services stored in ``app.extensions``.

Kept separate from ``web/__init__`` so blueprints import these without an
import cycle through the application factory (mirrors ``web/db.py``).
"""

from __future__ import annotations

from flask import current_app

from home_server.services.ble_runtime import BleRuntime
from home_server.services.channel_service import ChannelService
from home_server.services.device_service import DeviceService

DEVICE_SERVICE_KEY = "home_device_service"
CHANNEL_SERVICE_KEY = "home_channel_service"
BLE_RUNTIME_KEY = "home_ble_runtime"


def get_device_service() -> DeviceService:
    svc = current_app.extensions[DEVICE_SERVICE_KEY]
    if not isinstance(svc, DeviceService):
        raise TypeError(
            f"Expected DeviceService in extensions[{DEVICE_SERVICE_KEY!r}], "
            f"got {type(svc).__name__}"
        )
    return svc


def get_channel_service() -> ChannelService:
    svc = current_app.extensions[CHANNEL_SERVICE_KEY]
    if not isinstance(svc, ChannelService):
        raise TypeError(
            f"Expected ChannelService in extensions[{CHANNEL_SERVICE_KEY!r}], "
            f"got {type(svc).__name__}"
        )
    return svc


def get_ble_runtime() -> BleRuntime:
    rt = current_app.extensions[BLE_RUNTIME_KEY]
    if not isinstance(rt, BleRuntime):
        raise TypeError(
            f"Expected BleRuntime in extensions[{BLE_RUNTIME_KEY!r}], "
            f"got {type(rt).__name__}"
        )
    return rt
