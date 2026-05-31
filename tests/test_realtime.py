"""Tests for SocketIO realtime reading push."""

from flask import Flask
from flask.testing import FlaskClient

from home_server.db import channels, connection, devices, users
from home_server.web import socketio
from home_server.web.services import get_ble_runtime, get_channel_service

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


def test_reading_pushed_to_subscribed_client(app: Flask, logged_in_client: FlaskClient) -> None:
    channel_id = _seed_display_channel(app)
    ws = socketio.test_client(app, flask_test_client=logged_in_client)
    ws.emit("subscribe_channel", {"channel_id": channel_id})
    _notify(app, channel_id, b"\x2a")
    events = [e for e in ws.get_received() if e["name"] == "reading"]
    assert events, "expected a reading event"
    payload = events[0]["args"][0]
    assert payload["channel_id"] == channel_id
    assert payload["value"] == 42.0


def test_reading_not_pushed_without_subscription(app: Flask, logged_in_client: FlaskClient) -> None:
    channel_id = _seed_display_channel(app)
    ws = socketio.test_client(app, flask_test_client=logged_in_client)  # no room subscription
    _notify(app, channel_id, b"\x2a")
    assert [e for e in ws.get_received() if e["name"] == "reading"] == []


def test_unauthenticated_socket_rejected(app: Flask) -> None:
    ws = socketio.test_client(app)
    assert not ws.is_connected()


def test_device_status_pushed_to_client(app: Flask, logged_in_client: FlaskClient) -> None:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        uid = users.create(conn, username="u2", password_hash="x")
        did = devices.create(
            conn, address="C0:DE:00:00:00:01", name="d2", owner_user_id=uid
        )
    finally:
        conn.close()
    ws = socketio.test_client(app, flask_test_client=logged_in_client)
    with app.app_context():
        get_ble_runtime()._monitor_tick(0.0)  # device not connected -> "disconnected"
    events = [e for e in ws.get_received() if e["name"] == "device_status"]
    assert events, "expected a device_status event"
    assert events[0]["args"][0] == {"device_id": did, "status": "disconnected"}
