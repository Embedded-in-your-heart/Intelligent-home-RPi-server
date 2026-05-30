"""Device management blueprint: list, add, detail, delete."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from werkzeug.wrappers import Response
from wtforms import StringField
from wtforms.validators import DataRequired

from home_server.db import devices
from home_server.db.devices import DuplicateAddressError
from home_server.services.device_service import InvalidAddressError
from home_server.web.db import get_conn
from home_server.web.services import get_channel_service, get_device_service

bp = Blueprint("devices", __name__)


class AddDeviceForm(FlaskForm):
    address = StringField("Address", validators=[DataRequired()])
    name = StringField("Name", validators=[DataRequired()])


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
            )
        except InvalidAddressError:
            flash("Invalid BLE address")
        except DuplicateAddressError:
            flash("Address already exists")
        else:
            return redirect(url_for("devices.list_devices"))
    items = get_device_service().list_devices(get_conn())
    return render_template("devices/list.html", devices=items, form=form)


@bp.get("/devices/<int:device_id>")
@login_required
def detail(device_id: int) -> str:
    conn = get_conn()
    device = devices.get_by_id(conn, device_id)
    if device is None:
        abort(404)
    device_channels = get_channel_service().list_by_device(conn, device_id)
    return render_template("devices/detail.html", device=device, channels=device_channels)
