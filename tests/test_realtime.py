"""Tests for SocketIO realtime reading push."""

from flask import Flask

from home_server.db import channels, connection, devices, users
from home_server.web import socketio
from home_server.web.services import get_channel_service

ADDR = "AA:BB:CC:DD:EE:FF"
DISP_UUID = "uuid-disp"


def _seed_display_channel(app: Flask) -> int:
    db_path = app.config["DB_PATH"]
    conn = connection.connect(db_path)
    try:
        uid = users.create(conn, username="u", password_hash="x")
        did = devices.create(conn, address=ADDR, name="d", owner_user_id=uid)
        return channels.create(
            conn, device_id=did, name="temp", type="display",
            char_uuid=DISP_UUID, data_format="uint8", unit=None,
        )
    finally:
        conn.close()


def _notify(app: Flask, channel_id: int, raw: bytes) -> None:
    with app.app_context():
        conn = connection.connect(app.config["DB_PATH"])
        try:
            get_channel_service().handle_notify(
                conn, channel_id=channel_id, raw_bytes=raw
            )
        finally:
            conn.close()


def test_reading_pushed_to_subscribed_client(app: Flask) -> None:
    channel_id = _seed_display_channel(app)
    ws = socketio.test_client(app)
    ws.emit("subscribe_channel", {"channel_id": channel_id})
    _notify(app, channel_id, b"\x2a")
    events = [e for e in ws.get_received() if e["name"] == "reading"]
    assert events, "expected a reading event"
    payload = events[0]["args"][0]
    assert payload["channel_id"] == channel_id
    assert payload["value"] == 42.0


def test_reading_not_pushed_without_subscription(app: Flask) -> None:
    channel_id = _seed_display_channel(app)
    ws = socketio.test_client(app)  # never subscribes to the room
    _notify(app, channel_id, b"\x2a")
    assert [e for e in ws.get_received() if e["name"] == "reading"] == []
