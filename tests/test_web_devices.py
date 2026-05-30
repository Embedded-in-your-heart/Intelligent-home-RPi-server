import re

from flask import Flask
from flask.testing import FlaskClient

from home_server.db import channels, connection, devices


def _csrf_token(client: FlaskClient, path: str) -> str:
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match, f"csrf_token not found at {path}"
    return match.group(1)


def test_devices_requires_login(client: FlaskClient) -> None:
    resp = client.get("/devices")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_devices_empty_list(logged_in_client: FlaskClient) -> None:
    resp = logged_in_client.get("/devices")
    assert resp.status_code == 200
    assert b"No devices yet" in resp.data


def test_devices_list_shows_device(app: Flask, logged_in_client: FlaskClient) -> None:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        devices.create(conn, address="AA:BB:CC:DD:EE:03", name="Fan", owner_user_id=1)
    finally:
        conn.close()
    resp = logged_in_client.get("/devices")
    assert resp.status_code == 200
    assert b"Fan" in resp.data
    assert b"AA:BB:CC:DD:EE:03" in resp.data


def test_detail_shows_device_and_channels(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        device_id = devices.create(
            conn, address="AA:BB:CC:DD:EE:02", name="Lamp", owner_user_id=1
        )
        channels.create(
            conn,
            device_id=device_id,
            name="Power",
            type="controller",
            char_uuid="uuid-1",
            data_format="uint8",
            unit=None,
        )
    finally:
        conn.close()
    resp = logged_in_client.get(f"/devices/{device_id}")
    assert resp.status_code == 200
    assert b"Lamp" in resp.data
    assert b"Power" in resp.data


def test_detail_404_for_missing(logged_in_client: FlaskClient) -> None:
    resp = logged_in_client.get("/devices/999")
    assert resp.status_code == 404


def test_add_device_persists_with_owner(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    resp = logged_in_client.post(
        "/devices",
        data={"address": "AA:BB:CC:DD:EE:FF", "name": "Sensor", "csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    conn = connection.connect(app.config["DB_PATH"])
    try:
        device = devices.get_by_address(conn, "AA:BB:CC:DD:EE:FF")
    finally:
        conn.close()
    assert device is not None
    assert device.name == "Sensor"
    assert device.owner_user_id == 1


def test_add_device_invalid_address_flashes(logged_in_client: FlaskClient) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    resp = logged_in_client.post(
        "/devices",
        data={"address": "not-a-mac", "name": "X", "csrf_token": token},
    )
    assert resp.status_code == 200
    assert b"Invalid BLE address" in resp.data


def test_add_device_duplicate_flashes(logged_in_client: FlaskClient) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    logged_in_client.post(
        "/devices",
        data={"address": "AA:BB:CC:DD:EE:01", "name": "A", "csrf_token": token},
        follow_redirects=True,
    )
    token = _csrf_token(logged_in_client, "/devices")
    resp = logged_in_client.post(
        "/devices",
        data={"address": "AA:BB:CC:DD:EE:01", "name": "B", "csrf_token": token},
    )
    assert resp.status_code == 200
    assert b"Address already exists" in resp.data
