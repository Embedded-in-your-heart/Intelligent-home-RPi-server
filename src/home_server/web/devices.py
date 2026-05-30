"""Device management blueprint: list, add, detail, delete."""

from __future__ import annotations

from flask import Blueprint, abort, render_template
from flask_login import login_required

from home_server.db import devices
from home_server.web.db import get_conn
from home_server.web.services import get_channel_service, get_device_service

bp = Blueprint("devices", __name__)


@bp.get("/devices")
@login_required
def list_devices() -> str:
    items = get_device_service().list_devices(get_conn())
    return render_template("devices/list.html", devices=items)


@bp.get("/devices/<int:device_id>")
@login_required
def detail(device_id: int) -> str:
    conn = get_conn()
    device = devices.get_by_id(conn, device_id)
    if device is None:
        abort(404)
    device_channels = get_channel_service().list_by_device(conn, device_id)
    return render_template("devices/detail.html", device=device, channels=device_channels)
