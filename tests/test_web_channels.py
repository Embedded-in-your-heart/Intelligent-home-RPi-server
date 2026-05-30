import re

from flask import Flask
from flask.testing import FlaskClient

from home_server.db import channels, connection, devices


def _csrf_token(client: FlaskClient, path: str) -> str:
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match, f"csrf_token not found at {path}"
    return match.group(1)


def _make_device(app: Flask, address: str, name: str) -> int:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        return devices.create(conn, address=address, name=name, owner_user_id=1)
    finally:
        conn.close()


def test_add_channel_appears_on_detail(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:06", "Board")
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/devices/{device_id}/channels",
        data={
            "name": "Humidity",
            "type": "display",
            "char_uuid": "uuid-h",
            "data_format": "uint16_le",
            "unit": "%",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Humidity" in resp.data


def test_add_channel_duplicate_name_flashes(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:07", "Board2")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channels.create(
            conn,
            device_id=device_id,
            name="Dup",
            type="display",
            char_uuid="u",
            data_format="uint8",
            unit=None,
        )
    finally:
        conn.close()
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/devices/{device_id}/channels",
        data={
            "name": "Dup",
            "type": "display",
            "char_uuid": "u2",
            "data_format": "uint8",
            "unit": "",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 200
    assert b"Channel name already exists" in resp.data
