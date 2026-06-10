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
from home_server.presets import available_presets
from home_server.services.channel_service import (
    DuplicateChannelUuidError,
    UnknownWindowError,
    WrongChannelTypeError,
)
from home_server.web.db import get_conn
from home_server.web.services import get_ble_runtime, get_channel_service

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
                channel = get_channel_service().add_channel(
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
            except DuplicateChannelUuidError:
                flash("This function is already added on this device")
            else:
                get_ble_runtime().on_channel_added(device, channel)
                return redirect(url_for("devices.detail", device_id=device_id))
    device_channels = channels.list_by_device(conn, device_id)
    avail = available_presets(presets, device_channels)
    return render_template(
        "devices/detail.html",
        device=device,
        channels=device_channels,
        presets=avail,
        presets_exhausted=bool(presets) and not avail,
    )


@bp.post("/channels/<int:channel_id>/delete")
@login_required
def delete_channel(channel_id: int) -> Response:
    conn = get_conn()
    channel = channels.get_by_id(conn, channel_id)
    if channel is None:
        abort(404)
    device = devices.get_by_id(conn, channel.device_id)
    if device is None:
        abort(404)
    channels.delete(conn, channel_id)
    get_ble_runtime().on_channel_removed(device, channel)
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
    window = request.args.get("window")
    if window is not None:
        try:
            points = get_channel_service().get_history_windowed(
                conn, channel_id, window
            )
        except UnknownWindowError:
            abort(400)
        return jsonify(
            {
                "channel_id": channel_id,
                "readings": [
                    {"value": value, "recorded_at": recorded_at}
                    for value, recorded_at in points
                ],
            }
        )
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


@bp.get("/channels/<int:channel_id>/flag")
@login_required
def channel_flag(channel_id: int) -> Response:
    """Current state and last-triggered time for a 0/1 flag channel."""
    conn = get_conn()
    channel = channels.get_by_id(conn, channel_id)
    if channel is None:
        abort(404)
    latest, last_on = get_channel_service().get_flag_state(conn, channel_id)
    return jsonify(
        {
            "channel_id": channel_id,
            "value": latest.value if latest else None,
            "recorded_at": latest.recorded_at if latest else None,
            "last_on_at": last_on.recorded_at if last_on else None,
        }
    )
