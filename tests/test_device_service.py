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
    mock = MockBLEManager(scan_results=[DiscoveredDevice(ADDR, "STM32", -50)])
    svc = DeviceService(mock)
    found = svc.scan(5.0)
    assert found == [DiscoveredDevice(ADDR, "STM32", -50)]
    assert mock.scan_calls == [5.0]


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
