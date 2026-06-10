"""Smoke tests for the /analytics merged-view route."""

from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient

from home_server.db import channels, connection, devices


def _make_device(app: Flask, address: str, name: str) -> int:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        return devices.create(conn, address=address, name=name, owner_user_id=1)
    finally:
        conn.close()


def test_analytics_requires_login(client: FlaskClient) -> None:
    resp = client.get("/analytics")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_analytics_empty_state(logged_in_client: FlaskClient) -> None:
    # No devices or channels: should render the empty-state message.
    resp = logged_in_client.get("/analytics")
    assert resp.status_code == 200
    assert "合併檢視" in resp.get_data(as_text=True)


def test_analytics_shows_numeric_channel(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:A1", "SensorA")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channels.create(
            conn,
            device_id=device_id,
            name="Temperature",
            type="display",
            char_uuid="uuid-temp",
            data_format="float32_le",
            unit="°C",
        )
    finally:
        conn.close()
    resp = logged_in_client.get("/analytics")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Temperature" in html
    assert "data-merged-chart" in html
    assert "SensorA" in html


def test_analytics_shows_flag_channel(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:A2", "AlertDev")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channels.create(
            conn,
            device_id=device_id,
            name="Shake",
            type="display",
            char_uuid="uuid-shake",
            data_format="uint8",
            unit="0/1",
        )
    finally:
        conn.close()
    resp = logged_in_client.get("/analytics")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Shake" in html
    assert "data-mflag-channel-id" in html
    assert "AlertDev" in html


def test_analytics_excludes_controller_channels(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    device_id = _make_device(app, "AA:BB:CC:DD:EE:A3", "Lamp")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channels.create(
            conn,
            device_id=device_id,
            name="LED Control",
            type="controller",
            char_uuid="uuid-led",
            data_format="uint8",
            unit=None,
        )
    finally:
        conn.close()
    resp = logged_in_client.get("/analytics")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Controller channel must not appear on the analytics page.
    assert "LED Control" not in html
    assert "data-merged-chart" not in html


def test_analytics_merges_same_uuid_across_devices(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    dev_a = _make_device(app, "AA:BB:CC:DD:EE:A4", "DeviceA")
    dev_b = _make_device(app, "AA:BB:CC:DD:EE:A5", "DeviceB")
    conn = connection.connect(app.config["DB_PATH"])
    try:
        channels.create(
            conn,
            device_id=dev_a,
            name="Temp",
            type="display",
            char_uuid="uuid-temp",
            data_format="float32_le",
            unit="°C",
        )
        channels.create(
            conn,
            device_id=dev_b,
            name="Temp",
            type="display",
            char_uuid="uuid-temp",
            data_format="float32_le",
            unit="°C",
        )
    finally:
        conn.close()
    resp = logged_in_client.get("/analytics")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Both device names must appear inside a single merged card.
    assert "DeviceA" in html
    assert "DeviceB" in html
    # Only one merged-chart canvas should exist for this uuid group.
    assert html.count("data-merged-chart") == 1
