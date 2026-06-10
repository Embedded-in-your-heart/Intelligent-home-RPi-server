"""Rendering checks for the realtime/control frontend."""

from flask import Flask
from flask.testing import FlaskClient

from home_server.db import channels, connection, devices, readings


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


def test_detail_shows_chart_for_display_channel(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:41", "Sensor")
    channel_id = _add_channel(
        app, device_id, name="Temp", type_="display", char_uuid="uuid-t"
    )
    body = logged_in_client.get(f"/devices/{device_id}").get_data(as_text=True)
    assert f'data-channel-id="{channel_id}"' in body


def test_detail_shows_flag_for_binary_channel(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:44", "Alert")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="Shake", type="display",
            char_uuid="uuid-shake", data_format="uint8", unit="0/1",
        )
    finally:
        conn.close()
    body = logged_in_client.get(f"/devices/{device_id}").get_data(as_text=True)
    assert f'data-flag-channel-id="{channel_id}"' in body
    assert f'data-channel-id="{channel_id}"' not in body
    # The flag carries its name so the live feed can label the trigger toast.
    assert 'data-flag-name="Shake"' in body


def test_base_includes_toast_container(logged_in_client: FlaskClient) -> None:
    body = logged_in_client.get("/").get_data(as_text=True)
    assert 'id="toast-container"' in body


def test_detail_shows_control_form_for_controller(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:42", "Lamp")
    channel_id = _add_channel(
        app, device_id, name="LED", type_="controller", char_uuid="uuid-led"
    )
    body = logged_in_client.get(f"/devices/{device_id}").get_data(as_text=True)
    assert f"/channels/{channel_id}/write" in body
    assert 'name="value"' in body


def test_detail_shows_switch_for_binary_controller(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:43", "Lamp")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="LED1", type="controller",
            char_uuid="uuid-led1", data_format="uint8", unit="0/1",
        )
    finally:
        conn.close()
    body = logged_in_client.get(f"/devices/{device_id}").get_data(as_text=True)
    assert f'id="led-switch-{channel_id}"' in body
    assert "form-switch" in body
    assert f'hx-post="/channels/{channel_id}/write"' in body
    # The number input must be gone for a 0/1 controller.
    assert 'placeholder="value"' not in body


def test_switch_reflects_last_commanded_state(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:45", "Lamp")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channel_id = channels.create(
            conn, device_id=device_id, name="LED1", type="controller",
            char_uuid="uuid-led2", data_format="uint8", unit="0/1",
        )
        readings.insert(conn, channel_id=channel_id, value=1)
        conn.commit()
    finally:
        conn.close()
    body = logged_in_client.get(f"/devices/{device_id}").get_data(as_text=True)
    # The switch starts in the "on" position because the last command was 1.
    assert f'id="led-switch-{channel_id}" checked' in body


def test_list_has_scan_button(logged_in_client: FlaskClient) -> None:
    body = logged_in_client.get("/devices").get_data(as_text=True)
    assert 'hx-get="/devices/scan"' in body
    assert 'id="scan-results"' in body


def test_index_dashboard_lists_channels(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:43", "Sensor2")
    channel_id = _add_channel(
        app, device_id, name="Humidity", type_="display", char_uuid="uuid-h"
    )
    body = logged_in_client.get("/").get_data(as_text=True)
    assert "Humidity" in body
    assert f'data-channel-id="{channel_id}"' in body


def test_index_shows_observation_window_selector(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:45", "Sensor5")
    _add_channel(app, device_id, name="Temp", type_="display", char_uuid="uuid-w")
    body = logged_in_client.get("/").get_data(as_text=True)
    assert 'id="window-selector"' in body
    for window in ("1m", "10m", "1h", "1d", "1w"):
        assert f'data-window="{window}"' in body


def test_detail_shows_device_status_badge(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:51", "Sensor3")
    body = logged_in_client.get(f"/devices/{device_id}").get_data(as_text=True)
    assert f'data-device-id="{device_id}"' in body


def test_index_shows_device_status_badge(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:52", "Sensor4")
    body = logged_in_client.get("/").get_data(as_text=True)
    assert f'data-device-id="{device_id}"' in body
