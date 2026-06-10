"""Tests for BleRuntime notify wiring and synthetic feed."""

from pathlib import Path

import pytest

from home_server.ble import parser
from home_server.ble.mock_manager import MockBLEError, MockBLEManager
from home_server.ble.rate_limiter import RateLimiter
from home_server.db import channels, connection, devices, readings, users
from home_server.services.ble_runtime import BleRuntime
from home_server.services.channel_service import ChannelService

ADDR = "AA:BB:CC:DD:EE:FF"
DISP_UUID = "uuid-disp"
CTRL_UUID = "uuid-ctrl"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "rt.db"
    connection.initialize(path)
    conn = connection.connect(path)
    try:
        uid = users.create(conn, username="u", password_hash="x")
        did = devices.create(conn, address=ADDR, name="dev", owner_user_id=uid)
        channels.create(
            conn, device_id=did, name="temp", type="display",
            char_uuid=DISP_UUID, data_format="uint8", unit=None,
        )
        channels.create(
            conn, device_id=did, name="led", type="controller",
            char_uuid=CTRL_UUID, data_format="uint8", unit=None,
        )
    finally:
        conn.close()
    return path


def _runtime(
    db_path: Path, ble: MockBLEManager
) -> tuple[BleRuntime, list[tuple[int, float, str]]]:
    seen: list[tuple[int, float, str]] = []
    svc = ChannelService(
        ble, RateLimiter(0.0), lambda cid, value, ts: seen.append((cid, value, ts))
    )
    rt = BleRuntime(
        ble, svc,
        conn_factory=lambda: connection.connect(db_path),
        scan_duration=1.0,
    )
    return rt, seen


def test_activate_connects_and_subscribes_only_display(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    assert ble.is_connected(ADDR)
    # display channel is subscribed; controller channel is not
    ble.simulate_notify(ADDR, DISP_UUID, b"\x2a")  # no error
    with pytest.raises(MockBLEError):
        ble.simulate_notify(ADDR, CTRL_UUID, b"\x01")


def test_notify_persists_reading_and_calls_on_reading(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, seen = _runtime(db_path, ble)
    rt.activate()
    ble.simulate_notify(ADDR, DISP_UUID, b"\x2a")
    assert seen and seen[0][1] == 42.0
    conn = connection.connect(db_path)
    try:
        disp = next(c for c in channels.list_by_device(conn, 1) if c.char_uuid == DISP_UUID)
        rows = readings.list_by_channel(conn, disp.id)
    finally:
        conn.close()
    assert [r.value for r in rows] == [42.0]


def test_make_feed_encodes_known_channel_and_skips_unknown(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    feed = rt.make_feed()
    data = feed(ADDR, DISP_UUID)
    assert data is not None
    assert 0 <= parser.decode(data, "uint8") <= 255
    assert feed("ZZ:ZZ", "nope") is None


def test_activate_connects_with_device_addr_type(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    # db_path fixture created the device without addr_type -> defaults public.
    assert ble.connect_calls == [(ADDR, "public")]


def test_on_channel_added_subscribes_display_on_live_link(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, seen = _runtime(db_path, ble)
    rt.activate()
    conn = connection.connect(db_path)
    try:
        device = devices.list_all(conn)[0]
        cid = channels.create(
            conn, device_id=device.id, name="hum", type="display",
            char_uuid="uuid-hum", data_format="uint8", unit=None,
        )
        channel = channels.get_by_id(conn, cid)
    finally:
        conn.close()
    assert channel is not None
    rt.on_channel_added(device, channel)
    ble.simulate_notify(ADDR, "uuid-hum", b"\x07")  # no error
    assert seen and seen[-1][1] == 7.0


def test_on_channel_added_ignores_controller_and_disconnected(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    conn = connection.connect(db_path)
    try:
        device = devices.list_all(conn)[0]
        cid = channels.create(
            conn, device_id=device.id, name="fan", type="controller",
            char_uuid="uuid-fan", data_format="uint8", unit=None,
        )
        ctrl = channels.get_by_id(conn, cid)
        cid = channels.create(
            conn, device_id=device.id, name="hum", type="display",
            char_uuid="uuid-hum", data_format="uint8", unit=None,
        )
        disp = channels.get_by_id(conn, cid)
    finally:
        conn.close()
    assert ctrl is not None and disp is not None
    rt.on_channel_added(device, ctrl)
    with pytest.raises(MockBLEError):
        ble.simulate_notify(ADDR, "uuid-fan", b"\x01")
    ble.disconnect(ADDR)
    rt.on_channel_added(device, disp)  # no exception while link is down


def test_scan_window_drops_connections_to_free_the_adapter(db_path: Path) -> None:
    # bluepy cannot reliably scan while peripherals are connected on the same
    # adapter, so scan_window() must disconnect every live link for its body.
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    assert ble.is_connected(ADDR)
    with rt.scan_window():
        assert not ble.is_connected(ADDR)


def test_scan_window_does_not_spawn_monitor_when_not_running(db_path: Path) -> None:
    # The test app never starts the monitor; scan_window() must not start one
    # (which would leak a background thread into otherwise thread-free tests).
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    with rt.scan_window():
        pass
    assert rt._monitor_worker is None


def test_scan_window_restarts_monitor_when_running(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    rt.monitor_start(interval_s=0.05)
    try:
        assert rt._monitor_worker is not None
        with rt.scan_window():
            assert rt._monitor_worker is None  # stopped to free the adapter
        assert rt._monitor_worker is not None  # restored afterwards
    finally:
        rt.monitor_stop()
