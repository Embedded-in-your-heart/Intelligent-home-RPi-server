import re

from flask import Flask
from flask.testing import FlaskClient

from home_server.ble.interface import DiscoveredDevice
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


def test_delete_device_removes_it(app: Flask, logged_in_client: FlaskClient) -> None:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        device_id = devices.create(
            conn, address="AA:BB:CC:DD:EE:04", name="Heater", owner_user_id=1
        )
    finally:
        conn.close()
    token = _csrf_token(logged_in_client, "/devices")
    resp = logged_in_client.post(
        f"/devices/{device_id}/delete",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Heater" not in resp.data


def test_delete_device_cascades_channels(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        device_id = devices.create(
            conn, address="AA:BB:CC:DD:EE:05", name="Hub", owner_user_id=1
        )
        channels.create(
            conn,
            device_id=device_id,
            name="Temp",
            type="display",
            char_uuid="u",
            data_format="float32_le",
            unit="C",
        )
    finally:
        conn.close()
    token = _csrf_token(logged_in_client, "/devices")
    logged_in_client.post(f"/devices/{device_id}/delete", data={"csrf_token": token})
    conn = connection.connect(app.config["DB_PATH"])
    try:
        remaining = channels.list_by_device(conn, device_id)
    finally:
        conn.close()
    assert remaining == []


def test_delete_missing_device_404(logged_in_client: FlaskClient) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    resp = logged_in_client.post("/devices/999/delete", data={"csrf_token": token})
    assert resp.status_code == 404


def test_post_without_csrf_rejected(logged_in_client: FlaskClient) -> None:
    resp = logged_in_client.post(
        "/devices",
        data={"address": "AA:BB:CC:DD:EE:09", "name": "NoCSRF"},
    )
    assert resp.status_code == 400


def test_scan_lists_discovered_devices(
    logged_in_client: FlaskClient, mock_ble
) -> None:
    mock_ble.scan_results = [
        DiscoveredDevice(address="11:22:33:44:55:66", name="HOME-Node-A", rssi=-50)
    ]
    resp = logged_in_client.get("/devices/scan")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "11:22:33:44:55:66" in body
    assert "HOME-Node-A" in body


def test_scan_requires_login(client: FlaskClient) -> None:
    resp = client.get("/devices/scan")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_scan_failure_returns_error_message_not_500(
    logged_in_client: FlaskClient, mock_ble
) -> None:
    # A flaky BLE adapter (e.g. bluepy BTLEDisconnectError mid-scan) must not
    # crash the endpoint; the user sees a recoverable message instead.
    mock_ble.scan_error = RuntimeError("Device disconnected")
    resp = logged_in_client.get("/devices/scan")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "掃描暫時失敗" in body
    assert "No devices found" not in body


def test_add_device_stores_addr_type_from_form(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    logged_in_client.post(
        "/devices",
        data={
            "address": "f6:8c:f2:d3:ea:e7",
            "name": "STM",
            "addr_type": "random",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    conn = connection.connect(app.config["DB_PATH"])
    try:
        device = devices.get_by_address(conn, "f6:8c:f2:d3:ea:e7")
    finally:
        conn.close()
    assert device is not None
    assert device.addr_type == "random"


def test_add_device_without_addr_type_infers(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    logged_in_client.post(
        "/devices",
        data={
            "address": "f6:8c:f2:d3:ea:e7",
            "name": "STM",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    conn = connection.connect(app.config["DB_PATH"])
    try:
        device = devices.get_by_address(conn, "f6:8c:f2:d3:ea:e7")
    finally:
        conn.close()
    assert device is not None
    assert device.addr_type == "random"


def test_scan_results_include_addr_type_hidden_input(
    logged_in_client: FlaskClient, mock_ble
) -> None:
    mock_ble.scan_results = [
        DiscoveredDevice(
            address="f6:8c:f2:d3:ea:e7", name="HOME-N", rssi=-40, addr_type="random"
        )
    ]
    body = logged_in_client.get("/devices/scan").get_data(as_text=True)
    assert 'name="addr_type"' in body
    assert 'value="random"' in body


def test_add_device_form_addr_type_overrides_inference(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    # f6:... infers "random"; an explicit form addr_type must take precedence,
    # proving the scanned value (not inference) is what gets persisted.
    token = _csrf_token(logged_in_client, "/devices")
    logged_in_client.post(
        "/devices",
        data={
            "address": "f6:8c:f2:d3:ea:e7",
            "name": "STM",
            "addr_type": "public",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    conn = connection.connect(app.config["DB_PATH"])
    try:
        device = devices.get_by_address(conn, "f6:8c:f2:d3:ea:e7")
    finally:
        conn.close()
    assert device is not None
    assert device.addr_type == "public"
