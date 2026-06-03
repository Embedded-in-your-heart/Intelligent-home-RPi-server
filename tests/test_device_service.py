import pytest

from home_server.ble.interface import DiscoveredDevice
from home_server.ble.mock_manager import MockBLEManager
from home_server.db import devices, users
from home_server.db.devices import DeviceNotFoundError, DuplicateAddressError
from home_server.services.device_service import DeviceService, InvalidAddressError

ADDR = "AA:BB:CC:DD:EE:FF"


@pytest.fixture
def owner(db_conn) -> int:
    return users.create(db_conn, username="owner", password_hash="h")


def test_scan_returns_devices(db_conn) -> None:
    mock = MockBLEManager(scan_results=[DiscoveredDevice(ADDR, "HOME-STM32", -50)])
    svc = DeviceService(mock)
    found = svc.scan(5.0)
    assert found == [DiscoveredDevice(ADDR, "HOME-STM32", -50)]
    assert mock.scan_calls == [5.0]


def test_scan_filters_out_non_home_and_unnamed(db_conn) -> None:
    mock = MockBLEManager(
        scan_results=[
            DiscoveredDevice("AA:BB:CC:DD:EE:01", "HOME-Light", -40),
            DiscoveredDevice("AA:BB:CC:DD:EE:02", "Other", -50),
            DiscoveredDevice("AA:BB:CC:DD:EE:03", None, -60),
            DiscoveredDevice("AA:BB:CC:DD:EE:04", "home-light", -70),  # case-sensitive
        ]
    )
    svc = DeviceService(mock)
    found = svc.scan(5.0)
    assert [d.name for d in found] == ["HOME-Light"]


def test_add_device_persists_and_connects(db_conn, owner) -> None:
    mock = MockBLEManager()
    svc = DeviceService(mock)
    device = svc.add_device(db_conn, owner_user_id=owner, address=ADDR, name="Living Room")
    assert device.address == ADDR
    assert device.name == "Living Room"
    assert mock.is_connected(ADDR)


def test_add_device_kept_when_connect_fails(db_conn, owner) -> None:
    mock = MockBLEManager(fail_connect_for={ADDR})
    svc = DeviceService(mock)
    device = svc.add_device(db_conn, owner_user_id=owner, address=ADDR, name="x")
    assert devices.get_by_id(db_conn, device.id) is not None
    assert not mock.is_connected(ADDR)


def test_add_device_rejects_invalid_address(db_conn, owner) -> None:
    svc = DeviceService(MockBLEManager())
    with pytest.raises(InvalidAddressError):
        svc.add_device(db_conn, owner_user_id=owner, address="not-a-mac", name="x")


def test_add_device_rejects_duplicate(db_conn, owner) -> None:
    svc = DeviceService(MockBLEManager())
    svc.add_device(db_conn, owner_user_id=owner, address=ADDR, name="x")
    with pytest.raises(DuplicateAddressError):
        svc.add_device(db_conn, owner_user_id=owner, address=ADDR, name="y")


def test_remove_device_disconnects_and_deletes(db_conn, owner) -> None:
    mock = MockBLEManager()
    svc = DeviceService(mock)
    device = svc.add_device(db_conn, owner_user_id=owner, address=ADDR, name="x")
    svc.remove_device(db_conn, device.id)
    assert devices.get_by_id(db_conn, device.id) is None
    assert not mock.is_connected(ADDR)


def test_remove_missing_device_raises(db_conn) -> None:
    svc = DeviceService(MockBLEManager())
    with pytest.raises(DeviceNotFoundError):
        svc.remove_device(db_conn, 999)


def test_list_devices(db_conn, owner) -> None:
    svc = DeviceService(MockBLEManager())
    svc.add_device(db_conn, owner_user_id=owner, address=ADDR, name="x")
    assert len(svc.list_devices(db_conn)) == 1


def test_remove_device_not_connected_just_deletes(db_conn, owner) -> None:
    # Device that never connected (connect failed) must still delete cleanly,
    # without attempting a disconnect on an unconnected handle.
    mock = MockBLEManager(fail_connect_for={ADDR})
    svc = DeviceService(mock)
    device = svc.add_device(db_conn, owner_user_id=owner, address=ADDR, name="x")
    assert not mock.is_connected(ADDR)
    svc.remove_device(db_conn, device.id)
    assert devices.get_by_id(db_conn, device.id) is None


def test_is_connected_reflects_ble() -> None:
    mock = MockBLEManager()
    svc = DeviceService(mock)
    assert svc.is_connected(ADDR) is False
    mock.connect(ADDR)
    assert svc.is_connected(ADDR) is True


RANDOM_ADDR = "f6:8c:f2:d3:ea:e7"


def test_add_device_infers_random_addr_type(db_conn, owner) -> None:
    mock = MockBLEManager()
    svc = DeviceService(mock)
    d = svc.add_device(
        db_conn, owner_user_id=owner, address=RANDOM_ADDR, name="stm"
    )
    assert d.addr_type == "random"
    assert mock.connect_calls == [(RANDOM_ADDR, "random")]


def test_add_device_uses_explicit_addr_type(db_conn, owner) -> None:
    mock = MockBLEManager()
    svc = DeviceService(mock)
    d = svc.add_device(
        db_conn,
        owner_user_id=owner,
        address=RANDOM_ADDR,
        name="stm",
        addr_type="public",
    )
    assert d.addr_type == "public"
    assert mock.connect_calls == [(RANDOM_ADDR, "public")]


def test_add_device_coerces_invalid_addr_type_to_inference(db_conn, owner) -> None:
    # A tampered request could supply a value outside the CHECK allowlist; it
    # must be coerced (here: inferred -> "random") rather than raising on insert.
    mock = MockBLEManager()
    svc = DeviceService(mock)
    d = svc.add_device(
        db_conn,
        owner_user_id=owner,
        address=RANDOM_ADDR,
        name="stm",
        addr_type="garbage",
    )
    assert d.addr_type == "random"
    assert mock.connect_calls == [(RANDOM_ADDR, "random")]
