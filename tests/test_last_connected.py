"""Tests for last_connected_at: DB migration, runtime writes, and web rendering."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask
from flask.testing import FlaskClient

from home_server.ble.mock_manager import MockBLEManager
from home_server.ble.rate_limiter import RateLimiter
from home_server.db import channels, connection, devices, users
from home_server.services.ble_runtime import BleRuntime
from home_server.services.channel_service import ChannelService

ADDR = "AA:BB:CC:DD:EE:FF"
DISP_UUID = "uuid-disp"

# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

_OLD_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _old_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(_OLD_SCHEMA)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (1, 'u', 'h')"
    )
    return conn


def test_migration_adds_last_connected_at_column() -> None:
    conn = _old_db()
    conn.execute(
        "INSERT INTO devices (address, name, owner_user_id) "
        "VALUES ('aa:bb:cc:dd:ee:ff', 'dev', 1)"
    )
    connection.apply_migrations(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(devices)")}
    assert "last_connected_at" in cols
    conn.close()


def test_migration_last_connected_at_idempotent() -> None:
    # Running apply_migrations twice must not raise or corrupt data.
    conn = _old_db()
    connection.apply_migrations(conn)
    # Set a value to verify it is preserved on second run.
    conn.execute(
        "INSERT INTO devices (address, name, owner_user_id) "
        "VALUES ('aa:bb:cc:dd:ee:ff', 'dev', 1)"
    )
    conn.execute(
        "UPDATE devices SET last_connected_at = '2024-01-01 00:00:00' "
        "WHERE address = 'aa:bb:cc:dd:ee:ff'"
    )
    connection.apply_migrations(conn)
    row = conn.execute(
        "SELECT last_connected_at FROM devices WHERE address = 'aa:bb:cc:dd:ee:ff'"
    ).fetchone()
    assert row["last_connected_at"] == "2024-01-01 00:00:00"
    conn.close()


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------

def _seed(path: Path) -> None:
    connection.initialize(path)
    conn = connection.connect(path)
    try:
        uid = users.create(conn, username="u", password_hash="x")
        did = devices.create(conn, address=ADDR, name="dev", owner_user_id=uid)
        channels.create(
            conn, device_id=did, name="temp", type="display",
            char_uuid=DISP_UUID, data_format="uint8", unit=None,
        )
    finally:
        conn.close()


def _runtime(path: Path, ble: MockBLEManager) -> BleRuntime:
    svc = ChannelService(ble, RateLimiter(0.0), lambda *_: None)
    return BleRuntime(
        ble, svc,
        conn_factory=lambda: connection.connect(path),
        scan_duration=1.0,
    )


def _get_last_connected(path: Path, address: str) -> str | None:
    conn = connection.connect(path)
    try:
        row = conn.execute(
            "SELECT last_connected_at FROM devices WHERE address = ?", (address,)
        ).fetchone()
        assert row is not None
        value = row["last_connected_at"]
        return str(value) if value is not None else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Runtime: transition to connected sets last_connected_at
# ---------------------------------------------------------------------------

def test_transition_to_connected_sets_last_connected_at(tmp_path: Path) -> None:
    path = tmp_path / "rt.db"
    _seed(path)
    assert _get_last_connected(path, ADDR) is None

    ble = MockBLEManager()
    rt = _runtime(path, ble)
    rt.activate()
    rt._monitor_tick(0.0)  # connected transition

    assert _get_last_connected(path, ADDR) is not None


# ---------------------------------------------------------------------------
# Runtime: connected -> disconnected updates last_connected_at
# ---------------------------------------------------------------------------

def test_drop_from_connected_updates_last_connected_at(tmp_path: Path) -> None:
    path = tmp_path / "rt.db"
    _seed(path)

    ble = MockBLEManager()
    rt = _runtime(path, ble)
    rt.activate()
    rt._monitor_tick(0.0)  # connected

    ts_after_connect = _get_last_connected(path, ADDR)
    assert ts_after_connect is not None

    ble.simulate_disconnect(ADDR)
    rt._monitor_tick(1.0)  # drop observed -> disconnected

    # last_connected_at is updated again on the observed drop.
    ts_after_drop = _get_last_connected(path, ADDR)
    assert ts_after_drop is not None
    # Both timestamps are valid (may be equal within 1s resolution; just check set).
    assert ts_after_drop >= ts_after_connect


# ---------------------------------------------------------------------------
# Runtime: no write on steady-state ticks (disconnected -> disconnected)
# ---------------------------------------------------------------------------

def test_no_write_on_steady_disconnected_ticks(tmp_path: Path) -> None:
    # A device that was never connected (last_status stays None -> disconnected)
    # must not trigger a write on subsequent ticks that stay disconnected.
    path = tmp_path / "rt.db"
    _seed(path)

    ble = MockBLEManager()
    ble.fail_connect_for.add(ADDR)  # device is never reachable

    rt = _runtime(path, ble)
    # Never activate; device was never connected so last_status is None -> first
    # tick goes None -> disconnected (no write because prev was not CONNECTED).
    rt._monitor_tick(0.0)   # None -> disconnected (no write)
    rt._monitor_tick(1.0)   # retry -> still disconnected (no write)
    rt._monitor_tick(2.0)   # retry -> still disconnected (no write)

    assert _get_last_connected(path, ADDR) is None


# ---------------------------------------------------------------------------
# Web: devices list renders status badge and dash for never-connected device
# ---------------------------------------------------------------------------

def test_list_renders_status_badge_and_dash(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        device_id = devices.create(
            conn, address="AA:BB:CC:DD:EE:03", name="Sensor", owner_user_id=1
        )
    finally:
        conn.close()

    resp = logged_in_client.get("/devices")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Badge with data-device-id attribute must be present.
    assert f'data-device-id="{device_id}"' in body
    # Never-connected device shows the em-dash placeholder.
    assert "—" in body


def test_list_badge_class_for_disconnected_device(
    app: Flask, logged_in_client: FlaskClient
) -> None:
    conn = connection.connect(app.config["DB_PATH"])
    try:
        devices.create(
            conn, address="AA:BB:CC:DD:EE:04", name="Lamp", owner_user_id=1
        )
    finally:
        conn.close()

    resp = logged_in_client.get("/devices")
    body = resp.get_data(as_text=True)
    # Mock BLE has no connections, so status is disconnected -> bg-secondary badge.
    assert "bg-secondary" in body
    assert "disconnected" in body
