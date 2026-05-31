import time

import pytest

from home_server.ble.interface import BLEManager, DiscoveredDevice
from home_server.ble.mock_manager import MockBLEError, MockBLEManager


def test_satisfies_protocol() -> None:
    assert isinstance(MockBLEManager(), BLEManager)


def test_scan_returns_preset() -> None:
    mgr = MockBLEManager(
        scan_results=[
            DiscoveredDevice("aa:bb:cc:dd:ee:ff", "STM32-1", -50),
            DiscoveredDevice("11:22:33:44:55:66", None, -70),
        ]
    )
    devices = mgr.start_scan(3.0)
    assert len(devices) == 2
    assert devices[0].name == "STM32-1"
    assert mgr.scan_calls == [3.0]


def test_connect_disconnect_cycle() -> None:
    mgr = MockBLEManager()
    handle = mgr.connect("aa:bb")
    assert handle == "aa:bb"
    assert mgr.is_connected(handle)
    mgr.disconnect(handle)
    assert not mgr.is_connected(handle)


def test_connect_failure() -> None:
    mgr = MockBLEManager(fail_connect_for={"aa:bb"})
    with pytest.raises(MockBLEError):
        mgr.connect("aa:bb")


def test_read_requires_value_queued() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    with pytest.raises(MockBLEError):
        mgr.read("aa:bb", "uuid-1")


def test_read_returns_set_value_repeatedly() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    mgr.set_read_value("aa:bb", "uuid-1", b"\x42")
    assert mgr.read("aa:bb", "uuid-1") == b"\x42"
    assert mgr.read("aa:bb", "uuid-1") == b"\x42"  # sticky


def test_queue_read_values_fifo() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    mgr.queue_read_values("aa:bb", "uuid-1", [b"\x01", b"\x02", b"\x03"])
    assert mgr.read("aa:bb", "uuid-1") == b"\x01"
    assert mgr.read("aa:bb", "uuid-1") == b"\x02"
    assert mgr.read("aa:bb", "uuid-1") == b"\x03"  # last sticks
    assert mgr.read("aa:bb", "uuid-1") == b"\x03"


def test_write_records_calls() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    mgr.write("aa:bb", "uuid-led", b"\x01")
    mgr.write("aa:bb", "uuid-led", b"\x00")
    assert mgr.writes_for("aa:bb", "uuid-led") == [b"\x01", b"\x00"]


def test_write_without_connect() -> None:
    mgr = MockBLEManager()
    with pytest.raises(MockBLEError):
        mgr.write("aa:bb", "uuid", b"\x00")


def test_subscribe_and_notify() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    received: list[bytes] = []
    mgr.subscribe("aa:bb", "uuid-temp", received.append)
    mgr.simulate_notify("aa:bb", "uuid-temp", b"\xaa\xbb")
    mgr.simulate_notify("aa:bb", "uuid-temp", b"\xcc\xdd")
    assert received == [b"\xaa\xbb", b"\xcc\xdd"]


def test_notify_without_subscriber_errors() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    with pytest.raises(MockBLEError):
        mgr.simulate_notify("aa:bb", "uuid", b"\x00")


def test_disconnect_drops_subscriptions() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    mgr.subscribe("aa:bb", "uuid", lambda _: None)
    mgr.disconnect("aa:bb")
    mgr.connect("aa:bb")
    with pytest.raises(MockBLEError):
        mgr.simulate_notify("aa:bb", "uuid", b"\x00")


def test_simulate_disconnect_keeps_subscription_but_marks_offline() -> None:
    """simulate_disconnect models a peer dropping mid-session — subscription
    state stays, but is_connected returns False so reconnect logic can run."""
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    mgr.subscribe("aa:bb", "uuid", lambda _: None)
    mgr.simulate_disconnect("aa:bb")
    assert not mgr.is_connected("aa:bb")


def test_tick_emits_to_subscriber() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    received: list[bytes] = []
    mgr.subscribe("aa:bb", "uuid-x", received.append)
    mgr._tick(lambda address, char_uuid: b"\x07")
    assert received == [b"\x07"]


def test_tick_skips_when_feed_returns_none() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    received: list[bytes] = []
    mgr.subscribe("aa:bb", "uuid-x", received.append)
    mgr._tick(lambda address, char_uuid: None)
    assert received == []


def test_start_then_stop_emits_and_terminates() -> None:
    mgr = MockBLEManager()
    mgr.connect("aa:bb")
    received: list[bytes] = []
    mgr.subscribe("aa:bb", "uuid-x", received.append)
    mgr.start(lambda address, char_uuid: b"\x01", interval_s=0.01)
    time.sleep(0.05)
    thread = mgr._producer_thread
    mgr.stop()
    assert len(received) >= 1
    assert mgr._producer_thread is None
    assert thread is not None and not thread.is_alive()
