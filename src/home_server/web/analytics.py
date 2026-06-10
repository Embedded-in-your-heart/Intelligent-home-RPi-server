"""Analytics blueprint: merged cross-device view grouped by char_uuid."""

from __future__ import annotations

from dataclasses import dataclass, field

from flask import Blueprint, render_template
from flask_login import login_required

from home_server.db import channels as db_channels
from home_server.db import devices as db_devices
from home_server.web.db import get_conn

bp = Blueprint("analytics", __name__)


@dataclass
class ChannelGroup:
    name: str
    unit: str | None
    # Each entry: {"channelId": int, "deviceName": str} — matches JS contract.
    devices: list[dict[str, object]] = field(default_factory=list)


@bp.get("/analytics")
@login_required
def merged() -> str:
    conn = get_conn()

    # Build a mapping from device id to display name.
    device_names: dict[int, str] = {
        d.id: d.display_name for d in db_devices.list_all(conn)
    }

    # Group display channels by char_uuid, preserving insertion order.
    groups: dict[str, ChannelGroup] = {}
    for ch in db_channels.list_all(conn):
        if ch.type != "display":
            continue
        if ch.char_uuid not in groups:
            groups[ch.char_uuid] = ChannelGroup(name=ch.name, unit=ch.unit)
        groups[ch.char_uuid].devices.append(
            {
                "channelId": ch.id,
                "deviceName": device_names.get(ch.device_id, f"Device {ch.device_id}"),
            }
        )

    numeric_groups: list[ChannelGroup] = []
    flag_groups: list[ChannelGroup] = []
    for g in groups.values():
        if g.unit == "0/1":
            flag_groups.append(g)
        else:
            numeric_groups.append(g)

    return render_template(
        "analytics/merged.html",
        numeric_groups=numeric_groups,
        flag_groups=flag_groups,
    )
