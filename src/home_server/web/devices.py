"""Device management blueprint: list, add, detail, delete."""

from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required

from home_server.web.db import get_conn
from home_server.web.services import get_device_service

bp = Blueprint("devices", __name__)


@bp.get("/devices")
@login_required
def list_devices() -> str:
    items = get_device_service().list_devices(get_conn())
    return render_template("devices/list.html", devices=items)
