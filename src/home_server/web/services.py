"""Typed accessors for app-scoped services stored in ``app.extensions``.

Kept separate from ``web/__init__`` so blueprints import these without an
import cycle through the application factory (mirrors ``web/db.py``).
"""

from __future__ import annotations

from flask import current_app

from home_server.services.channel_service import ChannelService
from home_server.services.device_service import DeviceService

DEVICE_SERVICE_KEY = "home_device_service"
CHANNEL_SERVICE_KEY = "home_channel_service"


def get_device_service() -> DeviceService:
    svc = current_app.extensions[DEVICE_SERVICE_KEY]
    assert isinstance(svc, DeviceService)
    return svc


def get_channel_service() -> ChannelService:
    svc = current_app.extensions[CHANNEL_SERVICE_KEY]
    assert isinstance(svc, ChannelService)
    return svc
