import re

from flask import Flask
from flask.testing import FlaskClient

from home_server.db import connection, devices


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
