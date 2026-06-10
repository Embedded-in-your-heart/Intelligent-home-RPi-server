"""Device management blueprint: list, add, detail, delete."""

from __future__ import annotations

import logging

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from werkzeug.wrappers import Response
from wtforms import HiddenField, StringField
from wtforms.validators import DataRequired

from home_server.db import devices
from home_server.db.devices import DeviceNotFoundError, DuplicateAddressError
from home_server.presets import available_presets
from home_server.services.device_service import InvalidAddressError
from home_server.web.db import get_conn
from home_server.web.services import (
    get_ble_runtime,
    get_channel_service,
    get_device_service,
)

log = logging.getLogger(__name__)

bp = Blueprint("devices", __name__)


class AddDeviceForm(FlaskForm):
    address = StringField("Address", validators=[DataRequired()])
    name = StringField("Name", validators=[DataRequired()])
    addr_type = HiddenField("Addr type")


@bp.route("/devices", methods=["GET", "POST"])
@login_required
def list_devices() -> Response | str:
    form = AddDeviceForm()
    if form.validate_on_submit():
        try:
            get_device_service().add_device(
                get_conn(),
                owner_user_id=int(current_user.get_id()),
                address=form.address.data,
                name=form.name.data,
                addr_type=form.addr_type.data or None,
            )
        except InvalidAddressError:
            flash("Invalid BLE address")
        except DuplicateAddressError:
            flash("Address already exists")
        else:
            return redirect(url_for("devices.list_devices"))
    svc = get_device_service()
    items = svc.list_devices(get_conn())
    statuses = {
        d.id: "connected" if svc.is_connected(d.address) else "disconnected"
        for d in items
    }
    return render_template("devices/list.html", devices=items, statuses=statuses, form=form)


@bp.get("/devices/<int:device_id>")
@login_required
def detail(device_id: int) -> str:
    conn = get_conn()
    device = devices.get_by_id(conn, device_id)
    if device is None:
        abort(404)
    device_channels = get_channel_service().list_by_device(conn, device_id)
    status = (
        "connected" if get_device_service().is_connected(device.address) else "disconnected"
    )
    presets = current_app.config["CHANNEL_PRESETS"]
    avail = available_presets(presets, device_channels)
    return render_template(
        "devices/detail.html",
        device=device,
        channels=device_channels,
        presets=avail,
        presets_exhausted=bool(presets) and not avail,
        device_status=status,
    )


@bp.post("/devices/<int:device_id>/delete")
@login_required
def delete(device_id: int) -> Response:
    try:
        get_device_service().remove_device(get_conn(), device_id)
    except DeviceNotFoundError:
        abort(404)
    return redirect(url_for("devices.list_devices"))


@bp.post("/devices/<int:device_id>/label")
@login_required
def set_device_label(device_id: int) -> Response:
    try:
        get_device_service().set_label(get_conn(), device_id, request.form.get("label", ""))
    except DeviceNotFoundError:
        abort(404)
    return redirect(url_for("devices.list_devices"))


@bp.get("/devices/scan")
@login_required
def scan() -> str:
    duration = current_app.config["BLE_SCAN_DURATION"]
    # bluepy scanning is unreliable while peripherals are connected on the same
    # adapter; scan_window() drops live links for the scan and reconnects after.
    # Any residual adapter flakiness must surface as a recoverable message, not
    # an unhandled 500.
    try:
        with get_ble_runtime().scan_window():
            found = get_device_service().scan(duration)
    except Exception:
        log.warning("BLE scan failed", exc_info=True)
        return render_template("devices/_scan_results.html", found=[], scan_error=True)
    return render_template("devices/_scan_results.html", found=found)
