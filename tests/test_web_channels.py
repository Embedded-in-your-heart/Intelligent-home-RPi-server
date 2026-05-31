import re

from flask import Flask
from flask.testing import FlaskClient

from home_server.db import channels, connection, devices, readings


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


def test_add_channel_device_not_found(logged_in_client: FlaskClient) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    resp = logged_in_client.post(
        "/devices/999/channels",
        data={
            "name": "X",
            "type": "display",
            "char_uuid": "u",
            "data_format": "uint8",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 404


def test_delete_channel_removes_it(app: Flask, logged_in_client: FlaskClient) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:08", "B3")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn,
            device_id=device_id,
            name="Gone",
            type="display",
            char_uuid="u",
            data_format="uint8",
            unit=None,
        )
    finally:
        conn.close()
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/channels/{channel_id}/delete",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Gone" not in resp.data


def test_delete_missing_channel_404(logged_in_client: FlaskClient) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    resp = logged_in_client.post("/channels/999/delete", data={"csrf_token": token})
    assert resp.status_code == 404


def test_delete_channel_requires_login(client: FlaskClient) -> None:
    # Supply a valid CSRF token (from an anonymous page) so the CSRF guard
    # passes and @login_required is what rejects the unauthenticated request.
    token = _csrf_token(client, "/auth/login")
    resp = client.post("/channels/1/delete", data={"csrf_token": token})
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_write_controller_sends_encoded_bytes(
    app: Flask, logged_in_client: FlaskClient, mock_ble
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:21", "Lamp")
    mock_ble.connect("AA:BB:CC:DD:EE:21")  # write() requires a connected handle
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="LED", type="controller",
            char_uuid="uuid-led", data_format="uint8", unit=None,
        )
    finally:
        conn.close()
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/channels/{channel_id}/write",
        data={"value": "1", "csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert mock_ble.writes_for("AA:BB:CC:DD:EE:21", "uuid-led") == [b"\x01"]


def test_write_display_channel_rejected(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:22", "Sensor")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="Temp", type="display",
            char_uuid="uuid-t", data_format="uint8", unit=None,
        )
    finally:
        conn.close()
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/channels/{channel_id}/write",
        data={"value": "1", "csrf_token": token},
    )
    assert resp.status_code == 400


def test_write_non_numeric_value_flashes(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:23", "Lamp2")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="LED", type="controller",
            char_uuid="uuid-led", data_format="uint8", unit=None,
        )
    finally:
        conn.close()
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/channels/{channel_id}/write",
        data={"value": "abc", "csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Value must be a number" in resp.data


def test_write_missing_channel_404(logged_in_client: FlaskClient) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    resp = logged_in_client.post(
        "/channels/999/write", data={"value": "1", "csrf_token": token}
    )
    assert resp.status_code == 404


def test_history_returns_readings_oldest_first(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:31", "Sensor")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="Temp", type="display",
            char_uuid="uuid-t", data_format="uint8", unit="C",
        )
        readings.insert(conn, channel_id=channel_id, value=24.5)
        readings.insert(conn, channel_id=channel_id, value=25.0)
    finally:
        conn.close()
    resp = logged_in_client.get(f"/channels/{channel_id}/history")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["channel_id"] == channel_id
    assert [r["value"] for r in body["readings"]] == [24.5, 25.0]


def test_history_empty(app: Flask, logged_in_client: FlaskClient) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:32", "Sensor2")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="Temp", type="display",
            char_uuid="uuid-t", data_format="uint8", unit=None,
        )
    finally:
        conn.close()
    resp = logged_in_client.get(f"/channels/{channel_id}/history")
    assert resp.status_code == 200
    assert resp.get_json()["readings"] == []


def test_history_missing_channel_404(logged_in_client: FlaskClient) -> None:
    resp = logged_in_client.get("/channels/999/history")
    assert resp.status_code == 404
