"""Rendering checks for the realtime/control frontend."""

from flask import Flask
from flask.testing import FlaskClient

from home_server.db import channels, connection, devices


def _make_device(app: Flask, address: str, name: str) -> int:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        return devices.create(conn, address=address, name=name, owner_user_id=1)
    finally:
        conn.close()


def _add_channel(
    app: Flask, device_id: int, *, name: str, type_: str, char_uuid: str
) -> int:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        return channels.create(
            conn, device_id=device_id, name=name, type=type_,
            char_uuid=char_uuid, data_format="uint8", unit=None,
        )
    finally:
        conn.close()


def test_base_includes_frontend_assets(logged_in_client: FlaskClient) -> None:
    body = logged_in_client.get("/").get_data(as_text=True)
    assert "vendor/chartjs/chart.umd.min.js" in body
    assert "vendor/socketio/socket.io.min.js" in body
    assert "vendor/htmx/htmx.min.js" in body
    assert "js/dashboard.js" in body
