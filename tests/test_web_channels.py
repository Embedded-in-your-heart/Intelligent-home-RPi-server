import re
import struct

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
        data={"name": "Humidity", "preset": "uuid-temp", "csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Humidity" in resp.data
    # The preset (uuid-temp) determines the stored technical fields.
    conn = connection.connect(app.config["DB_PATH"])
    try:
        created = channels.list_by_device(conn, device_id)
    finally:
        conn.close()
    assert len(created) == 1
    ch = created[0]
    assert ch.name == "Humidity"
    assert ch.char_uuid == "uuid-temp"
    assert ch.type == "display"
    assert ch.data_format == "float32_le"
    assert ch.unit == "°C"


def test_add_channel_subscribes_immediately_when_device_connected(
    app: Flask, logged_in_client: FlaskClient, mock_ble
) -> None:
    # Adding a display channel while the device link is already up must
    # subscribe right away — without this, data only flows after the STM32
    # resets and the reconnect monitor re-subscribes.
    address = "AA:BB:CC:DD:EE:0A"
    device_id = _make_device(app, address, "LiveBoard")
    mock_ble.connect(address)
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/devices/{device_id}/channels",
        data={"name": "Temp", "preset": "uuid-temp", "csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    mock_ble.simulate_notify(address, "uuid-temp", struct.pack("<f", 21.5))
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel = channels.list_by_device(conn, device_id)[0]
        rows = readings.list_by_channel(conn, channel.id)
    finally:
        conn.close()
    assert [r.value for r in rows] == [21.5]


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
        data={"name": "Dup", "preset": "uuid-temp", "csrf_token": token},
    )
    assert resp.status_code == 200
    assert b"Channel name already exists" in resp.data


def test_add_channel_duplicate_uuid_flashes(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:0B", "DupUuid")
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/devices/{device_id}/channels",
        data={"name": "T1", "preset": "uuid-temp", "csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/devices/{device_id}/channels",
        data={"name": "T2", "preset": "uuid-temp", "csrf_token": token},
    )
    assert resp.status_code == 200
    assert b"This function is already added on this device" in resp.data
    conn = connection.connect(app.config["DB_PATH"])
    try:
        assert len(channels.list_by_device(conn, device_id)) == 1
    finally:
        conn.close()


def test_detail_dropdown_hides_used_presets(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:0C", "Filtered")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channels.create(
            conn, device_id=device_id, name="Temp", type="display",
            char_uuid="uuid-temp", data_format="float32_le", unit="°C",
        )
    finally:
        conn.close()
    html = logged_in_client.get(f"/devices/{device_id}").get_data(as_text=True)
    assert 'value="uuid-temp"' not in html
    assert 'value="uuid-led"' in html


def test_detail_all_presets_used_shows_message(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:0D", "Full")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channels.create(
            conn, device_id=device_id, name="Temp", type="display",
            char_uuid="uuid-temp", data_format="float32_le", unit="°C",
        )
        channels.create(
            conn, device_id=device_id, name="LED", type="controller",
            char_uuid="uuid-led", data_format="uint8", unit=None,
        )
    finally:
        conn.close()
    html = logged_in_client.get(f"/devices/{device_id}").get_data(as_text=True)
    assert 'id="channel-preset"' not in html
    assert "所有功能皆已新增" in html


def test_add_channel_device_not_found(logged_in_client: FlaskClient) -> None:
    token = _csrf_token(logged_in_client, "/devices")
    resp = logged_in_client.post(
        "/devices/999/channels",
        data={"name": "X", "preset": "uuid-temp", "csrf_token": token},
    )
    assert resp.status_code == 404


def test_add_channel_unknown_preset_rejected(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:09", "Board3")
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/devices/{device_id}/channels",
        data={"name": "X", "preset": "uuid-nope", "csrf_token": token},
        follow_redirects=True,
    )
    # SelectField choices validation rejects an unknown preset; no channel created.
    assert resp.status_code == 200
    conn = connection.connect(app.config["DB_PATH"])
    try:
        assert channels.list_by_device(conn, device_id) == []
    finally:
        conn.close()


def test_delete_channel_unsubscribes_ble_when_connected(
    app: Flask, logged_in_client: FlaskClient, mock_ble
) -> None:
    # When a display channel is deleted while the device link is up, the BLE
    # notify subscription must be torn down so handle_notify stops being called.
    address = "AA:BB:CC:DD:EE:10"
    device_id = _make_device(app, address, "DelBoard")
    mock_ble.connect(address)
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn,
            device_id=device_id,
            name="ToDelete",
            type="display",
            char_uuid="uuid-temp",
            data_format="float32_le",
            unit="°C",
        )
    finally:
        conn.close()
    # Subscribe via the web route (mirrors add_channel flow) so mock_ble knows
    # about it, then delete the channel and verify the subscription is gone.
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    logged_in_client.post(
        f"/devices/{device_id}/channels",
        data={"name": "ToDelete2", "preset": "uuid-temp", "csrf_token": token},
        follow_redirects=True,
    )
    # Manually subscribe so the mock tracks it (channel created directly above
    # bypassed on_channel_added).
    mock_ble._subscriptions[(address, "uuid-temp")] = lambda _: None
    token = _csrf_token(logged_in_client, f"/devices/{device_id}")
    resp = logged_in_client.post(
        f"/channels/{channel_id}/delete",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Subscription must be removed from mock_ble after delete.
    assert (address, "uuid-temp") not in mock_ble._subscriptions
    # Channel must be gone from the DB.
    conn = connection.connect(app.config["DB_PATH"])
    try:
        remaining = channels.list_by_device(conn, device_id)
    finally:
        conn.close()
    assert all(ch.id != channel_id for ch in remaining)


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


def test_flag_reports_current_state_and_last_on(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:33", "Alert")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="Shake", type="display",
            char_uuid="uuid-shake", data_format="uint8", unit="0/1",
        )
        readings.insert(conn, channel_id=channel_id, value=1.0)  # last became 1
        readings.insert(conn, channel_id=channel_id, value=0.0)  # current state
    finally:
        conn.close()
    resp = logged_in_client.get(f"/channels/{channel_id}/flag")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["channel_id"] == channel_id
    assert body["value"] == 0.0
    assert body["last_on_at"] is not None


def test_flag_no_readings_returns_nulls(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:34", "Alert2")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="Loud", type="display",
            char_uuid="uuid-loud", data_format="uint8", unit="0/1",
        )
    finally:
        conn.close()
    resp = logged_in_client.get(f"/channels/{channel_id}/flag")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["value"] is None
    assert body["recorded_at"] is None
    assert body["last_on_at"] is None


def test_flag_missing_channel_404(logged_in_client: FlaskClient) -> None:
    resp = logged_in_client.get("/channels/999/flag")
    assert resp.status_code == 404


def test_flag_requires_login(client: FlaskClient) -> None:
    resp = client.get("/channels/1/flag")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_write_channel_requires_login(client: FlaskClient) -> None:
    token = _csrf_token(client, "/auth/login")
    resp = client.post(
        "/channels/1/write", data={"value": "1", "csrf_token": token}
    )
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_history_requires_login(client: FlaskClient) -> None:
    resp = client.get("/channels/1/history")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_write_out_of_range_value_flashes(
    app: Flask, logged_in_client: FlaskClient, mock_ble
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:24", "Lamp3")
    mock_ble.connect("AA:BB:CC:DD:EE:24")
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
        data={"value": "256", "csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Value out of range" in resp.data
    assert mock_ble.writes_for("AA:BB:CC:DD:EE:24", "uuid-led") == []
