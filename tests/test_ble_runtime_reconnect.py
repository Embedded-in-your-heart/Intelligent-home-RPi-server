"""Tests for BleRuntime auto-reconnect monitor and device status."""

import time
from pathlib import Path

from home_server.ble.mock_manager import MockBLEManager
from home_server.ble.rate_limiter import RateLimiter
from home_server.db import channels, connection, devices, users
from home_server.services.ble_runtime import BleRuntime
from home_server.services.channel_service import ChannelService

ADDR = "AA:BB:CC:DD:EE:FF"
DISP_UUID = "uuid-disp"
CTRL_UUID = "uuid-ctrl"


def _seed(path: Path, *, with_display: bool = True, with_controller: bool = False) -> None:
    connection.initialize(path)
    conn = connection.connect(path)
    try:
        uid = users.create(conn, username="u", password_hash="x")
        did = devices.create(conn, address=ADDR, name="dev", owner_user_id=uid)
        if with_display:
            channels.create(
                conn, device_id=did, name="temp", type="display",
                char_uuid=DISP_UUID, data_format="uint8", unit=None,
            )
        if with_controller:
            channels.create(
                conn, device_id=did, name="led", type="controller",
                char_uuid=CTRL_UUID, data_format="uint8", unit=None,
            )
    finally:
        conn.close()


def _runtime(
    path: Path, ble: MockBLEManager
) -> tuple[BleRuntime, list[tuple[int, str]]]:
    statuses: list[tuple[int, str]] = []
    svc = ChannelService(ble, RateLimiter(0.0), lambda *_: None)
    rt = BleRuntime(
        ble, svc,
        conn_factory=lambda: connection.connect(path),
        scan_duration=1.0,
        on_status=lambda did, st: statuses.append((did, st)),
    )
    return rt, statuses


def test_tick_emits_connected_for_live_device(tmp_path: Path) -> None:
    path = tmp_path / "rt.db"
    _seed(path)
    ble = MockBLEManager()
    rt, statuses = _runtime(path, ble)
    rt.activate()
    rt._monitor_tick(0.0)
    assert statuses[-1][1] == "connected"


def test_disconnect_then_reconnect_cycle(tmp_path: Path) -> None:
    path = tmp_path / "rt.db"
    _seed(path)
    ble = MockBLEManager()
    rt, statuses = _runtime(path, ble)
    rt.activate()
    rt._monitor_tick(0.0)                 # connected
    ble.simulate_disconnect(ADDR)
    rt._monitor_tick(1.0)                 # drop detected -> disconnected, retry at 2.0
    assert statuses[-1][1] == "disconnected"
    rt._monitor_tick(1.5)                 # too early, no change
    assert statuses[-1][1] == "disconnected"
    rt._monitor_tick(2.0)                 # retry -> reconnecting then connected
    seen = [s for _, s in statuses]
    assert "reconnecting" in seen
    assert statuses[-1][1] == "connected"
    ble.simulate_notify(ADDR, DISP_UUID, b"\x2a")  # re-subscribed: no MockBLEError


def test_backoff_doubles_and_caps_at_60(tmp_path: Path) -> None:
    path = tmp_path / "rt.db"
    _seed(path)
    ble = MockBLEManager()
    rt, _ = _runtime(path, ble)
    rt.activate()
    rt._monitor_tick(0.0)                 # connected
    ble.fail_connect_for.add(ADDR)        # reconnects now fail
    ble.simulate_disconnect(ADDR)
    rt._monitor_tick(10.0)                # disconnected, retry scheduled
    for t in range(100, 900, 100):        # each tick = one failed retry (now >> next_retry)
        rt._monitor_tick(float(t))
    assert rt._monitor[ADDR].backoff_s == 60.0


def test_status_emitted_once_per_transition(tmp_path: Path) -> None:
    path = tmp_path / "rt.db"
    _seed(path)
    ble = MockBLEManager()
    rt, statuses = _runtime(path, ble)
    rt.activate()
    rt._monitor_tick(0.0)
    rt._monitor_tick(1.0)
    rt._monitor_tick(2.0)
    assert [s for _, s in statuses].count("connected") == 1


def test_controller_only_device_reconnects(tmp_path: Path) -> None:
    path = tmp_path / "rt.db"
    _seed(path, with_display=False, with_controller=True)
    ble = MockBLEManager()
    rt, statuses = _runtime(path, ble)
    rt.activate()
    rt._monitor_tick(0.0)                 # connected
    ble.simulate_disconnect(ADDR)
    rt._monitor_tick(1.0)                 # disconnected
    rt._monitor_tick(2.0)                 # reconnecting -> connected
    assert ble.is_connected(ADDR)
    assert statuses[-1][1] == "connected"


def test_monitor_start_stop_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "rt.db"
    _seed(path)
    ble = MockBLEManager()
    rt, _ = _runtime(path, ble)
    rt.activate()
    rt.monitor_start(interval_s=0.01)
    time.sleep(0.05)
    thread = rt._monitor_thread
    rt.monitor_stop()
    assert rt._monitor_thread is None
    assert thread is not None and not thread.is_alive()
