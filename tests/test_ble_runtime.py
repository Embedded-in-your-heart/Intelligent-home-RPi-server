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
FLAG_UUID = "uuid-flag"
ENUM_UUID = "uuid-sound-class"
DBA_UUID = "uuid-dba"
MG_UUID = "uuid-vib-rms"


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
        channels.create(
            conn, device_id=did, name="alert", type="display",
            char_uuid=FLAG_UUID, data_format="uint8", unit="0/1",
        )
        channels.create(
            conn, device_id=did, name="sound_class", type="display",
            char_uuid=ENUM_UUID, data_format="uint8",
            unit="enum:0=安靜,1=語音,2=拍手,3=警報,4=其他",
        )
        channels.create(
            conn, device_id=did, name="mic_dba", type="display",
            char_uuid=DBA_UUID, data_format="float32_le", unit="dBA",
        )
        channels.create(
            conn, device_id=did, name="vib_rms", type="display",
            char_uuid=MG_UUID, data_format="float32_le", unit="mg",
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


def test_activate_skips_channel_with_missing_characteristic(db_path: Path) -> None:
    # A display channel whose char_uuid is absent from the peripheral (e.g. a
    # characteristic removed from firmware, like the retired SoundClass 1A220009)
    # must not crash bring-up: the bad channel is logged and skipped, and every
    # other display channel on the device still gets subscribed.
    ble = MockBLEManager()
    ble.fail_subscribe_for = {ENUM_UUID}
    rt, _ = _runtime(db_path, ble)
    rt.activate()  # must not raise
    assert ble.is_connected(ADDR)
    # The healthy channels are still subscribed despite the bad one in the middle.
    ble.simulate_notify(ADDR, DISP_UUID, b"\x2a")  # no error
    ble.simulate_notify(ADDR, MG_UUID, b"\x00\x00\x00\x00")  # subscribed after ENUM
    # The failed channel is not subscribed.
    with pytest.raises(MockBLEError):
        ble.simulate_notify(ADDR, ENUM_UUID, b"\x01")


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


def test_make_feed_binary_channel_toggles_and_recovers(db_path: Path) -> None:
    # A 0/1 flag channel must emit both 0 and 1 over time, otherwise the
    # dashboard flag would trigger and never recover to "normal".
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    feed = rt.make_feed()
    values = {parser.decode(feed(ADDR, FLAG_UUID), "uint8") for _ in range(60)}
    assert values <= {0.0, 1.0}
    assert 0.0 in values  # recovers to normal
    assert 1.0 in values  # still triggers


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


def test_on_channel_removed_unsubscribes_display_while_connected(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    conn = connection.connect(db_path)
    try:
        device = devices.list_all(conn)[0]
        disp = next(c for c in channels.list_by_device(conn, device.id) if c.char_uuid == DISP_UUID)
    finally:
        conn.close()
    assert (ADDR, DISP_UUID) in rt._subscribed
    rt.on_channel_removed(device, disp)
    # Entry must be gone from _subscribed
    assert (ADDR, DISP_UUID) not in rt._subscribed
    # BLE-level subscription must have been torn down
    with pytest.raises(MockBLEError):
        ble.simulate_notify(ADDR, DISP_UUID, b"\x2a")


def test_on_channel_removed_ignores_controller_channel(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    conn = connection.connect(db_path)
    try:
        device = devices.list_all(conn)[0]
        ctrl = next(c for c in channels.list_by_device(conn, device.id) if c.char_uuid == CTRL_UUID)
    finally:
        conn.close()
    # controller channel was never subscribed; calling on_channel_removed is a no-op
    rt.on_channel_removed(device, ctrl)
    # display channel must still be subscribed
    assert (ADDR, DISP_UUID) in rt._subscribed


def test_on_channel_removed_removes_subscribed_entry_when_disconnected(db_path: Path) -> None:
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    conn = connection.connect(db_path)
    try:
        device = devices.list_all(conn)[0]
        disp = next(c for c in channels.list_by_device(conn, device.id) if c.char_uuid == DISP_UUID)
    finally:
        conn.close()
    ble.disconnect(ADDR)
    assert not ble.is_connected(ADDR)
    assert (ADDR, DISP_UUID) in rt._subscribed
    # Must not raise even though the link is down
    rt.on_channel_removed(device, disp)
    assert (ADDR, DISP_UUID) not in rt._subscribed


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


def test_make_feed_enum_channel_emits_only_valid_keys(db_path: Path) -> None:
    # Enum feed must only emit values that are keys of the parsed mapping.
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    feed = rt.make_feed()
    values = [parser.decode(feed(ADDR, ENUM_UUID), "uint8") for _ in range(60)]  # type: ignore[arg-type]
    valid_keys = {0.0, 1.0, 2.0, 3.0, 4.0}
    assert all(v in valid_keys for v in values)
    # Class 0 must dominate (at most 1 non-zero per 6 ticks).
    assert values.count(0.0) > len(values) // 2
    # At least one non-zero class must appear over 60 ticks (every 6th tick).
    assert any(v != 0.0 for v in values)


def test_make_feed_dba_channel_emits_plausible_range(db_path: Path) -> None:
    # Baseline: 40 ± 8 dB(A); spike: baseline + 25 every 30th tick.
    # Expected range: [32, 73].  Test uses [28, 75] to allow float32 rounding.
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    feed = rt.make_feed()
    values = [parser.decode(feed(ADDR, DBA_UUID), "float32_le") for _ in range(60)]  # type: ignore[arg-type]
    assert all(28.0 <= v <= 75.0 for v in values), (
        f"dBA feed out of [28, 75] range: min={min(values):.1f} max={max(values):.1f}"
    )
    # Must include both quiet baseline and at least one spike tick (tick 30).
    assert min(values) < 45.0, "expected quiet baseline ticks below 45 dB(A)"
    assert max(values) > 60.0, "expected spike tick above 60 dB(A)"


def test_make_feed_mg_channel_stays_in_range(db_path: Path) -> None:
    # VibrationRMS feed must stay within [0, 95] across 60 ticks.
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    feed = rt.make_feed()
    values = [parser.decode(feed(ADDR, MG_UUID), "float32_le") for _ in range(60)]  # type: ignore[arg-type]
    assert all(0.0 <= v <= 95.0 for v in values), (
        f"mg feed out of [0, 95] range: min={min(values):.1f} max={max(values):.1f}"
    )


def test_make_feed_mg_channel_has_quiet_and_burst(db_path: Path) -> None:
    # Feed must produce both a quiet baseline (<10 mg) and burst values (>60 mg)
    # within 60 ticks so the VibrationAlert-style demo is exercised.
    ble = MockBLEManager()
    rt, _ = _runtime(db_path, ble)
    rt.activate()
    feed = rt.make_feed()
    values = [parser.decode(feed(ADDR, MG_UUID), "float32_le") for _ in range(60)]  # type: ignore[arg-type]
    assert any(v < 10.0 for v in values), "expected quiet baseline ticks below 10 mg"
    assert any(v > 60.0 for v in values), "expected burst ticks above 60 mg"
