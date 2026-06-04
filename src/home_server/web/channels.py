"""Channel management blueprint: add, delete."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from flask_wtf import FlaskForm
from werkzeug.wrappers import Response
from wtforms import SelectField, StringField
from wtforms.validators import DataRequired

from home_server.ble import parser
from home_server.db import channels, devices
from home_server.db.channels import DuplicateChannelNameError
from home_server.services.channel_service import WrongChannelTypeError
from home_server.web.db import get_conn
from home_server.web.services import get_channel_service

bp = Blueprint("channels", __name__)


class AddChannelForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    preset = SelectField("Function", validators=[DataRequired()])


@bp.post("/devices/<int:device_id>/channels")
@login_required
def add_channel(device_id: int) -> Response | str:
    conn = get_conn()
    device = devices.get_by_id(conn, device_id)
    if device is None:
        abort(404)
    presets = current_app.config["CHANNEL_PRESETS"]
    form = AddChannelForm()
    form.preset.choices = [(p.char_uuid, p.label) for p in presets]
    if form.validate_on_submit():
        preset = next((p for p in presets if p.char_uuid == form.preset.data), None)
        if preset is None:
            flash("Unknown channel function")
        else:
            try:
                get_channel_service().add_channel(
                    conn,
                    device_id=device_id,
                    name=form.name.data,
                    type=preset.type,
                    char_uuid=preset.char_uuid,
                    data_format=preset.data_format,
                    unit=preset.unit,
                )
            except DuplicateChannelNameError:
                flash("Channel name already exists on this device")
            else:
                return redirect(url_for("devices.detail", device_id=device_id))
    device_channels = channels.list_by_device(conn, device_id)
    return render_template(
        "devices/detail.html",
        device=device,
        channels=device_channels,
        presets=presets,
    )


@bp.post("/channels/<int:channel_id>/delete")
@login_required
def delete_channel(channel_id: int) -> Response:
    conn = get_conn()
    channel = channels.get_by_id(conn, channel_id)
    if channel is None:
        abort(404)
    channels.delete(conn, channel_id)
    return redirect(url_for("devices.detail", device_id=channel.device_id))


@bp.post("/channels/<int:channel_id>/write")
@login_required
def write_channel(channel_id: int) -> Response:
    conn = get_conn()
    channel = channels.get_by_id(conn, channel_id)
    if channel is None:
        abort(404)
    raw = request.form.get("value", "").strip()
    try:
        value = float(raw)
    except ValueError:
        flash("Value must be a number")
        return redirect(url_for("devices.detail", device_id=channel.device_id))
    try:
        get_channel_service().write_command(conn, channel_id=channel_id, raw_value=value)
    except WrongChannelTypeError:
        abort(400)
    except parser.ParseError:
        flash("Value out of range for this channel format")
        return redirect(url_for("devices.detail", device_id=channel.device_id))
    return redirect(url_for("devices.detail", device_id=channel.device_id))


@bp.get("/channels/<int:channel_id>/history")
@login_required
def channel_history(channel_id: int) -> Response:
    conn = get_conn()
    channel = channels.get_by_id(conn, channel_id)
    if channel is None:
        abort(404)
    limit_raw = request.args.get("limit", type=int)
    limit = 200 if limit_raw is None else max(1, min(limit_raw, 1000))
    history = get_channel_service().get_history(conn, channel_id, limit=limit)
    return jsonify(
        {
            "channel_id": channel_id,
            "readings": [
                {"value": r.value, "recorded_at": r.recorded_at} for r in history
            ],
        }
    )
