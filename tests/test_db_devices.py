import pytest

from home_server.db import devices, users
from home_server.db.devices import DeviceNotFoundError, DuplicateAddressError


@pytest.fixture
def alice_id(db_conn) -> int:
    return users.create(db_conn, username="alice", password_hash="h")


@pytest.fixture
def bob_id(db_conn) -> int:
    return users.create(db_conn, username="bob", password_hash="h")


def test_create_and_get(db_conn, alice_id) -> None:
    did = devices.create(
        db_conn, address="aa:bb:cc:dd:ee:ff", name="Living Room", owner_user_id=alice_id
    )
    d = devices.get_by_id(db_conn, did)
    assert d is not None
    assert d.address == "aa:bb:cc:dd:ee:ff"
    assert d.name == "Living Room"
    assert d.owner_user_id == alice_id


def test_get_by_address(db_conn, alice_id) -> None:
    devices.create(db_conn, address="aa:bb", name="d", owner_user_id=alice_id)
    d = devices.get_by_address(db_conn, "aa:bb")
    assert d is not None and d.name == "d"


def test_duplicate_address_rejected(db_conn, alice_id, bob_id) -> None:
    devices.create(db_conn, address="aa:bb", name="d1", owner_user_id=alice_id)
    with pytest.raises(DuplicateAddressError):
        devices.create(db_conn, address="aa:bb", name="d2", owner_user_id=bob_id)


def test_list_all_and_list_by_owner(db_conn, alice_id, bob_id) -> None:
    devices.create(db_conn, address="a1", name="d1", owner_user_id=alice_id)
    devices.create(db_conn, address="a2", name="d2", owner_user_id=alice_id)
    devices.create(db_conn, address="b1", name="d3", owner_user_id=bob_id)

    assert len(devices.list_all(db_conn)) == 3
    alice_devs = devices.list_by_owner(db_conn, alice_id)
    assert [d.address for d in alice_devs] == ["a1", "a2"]
    bob_devs = devices.list_by_owner(db_conn, bob_id)
    assert [d.address for d in bob_devs] == ["b1"]


def test_delete(db_conn, alice_id) -> None:
    did = devices.create(db_conn, address="aa", name="d", owner_user_id=alice_id)
    devices.delete(db_conn, did)
    assert devices.get_by_id(db_conn, did) is None


def test_delete_missing(db_conn) -> None:
    with pytest.raises(DeviceNotFoundError):
        devices.delete(db_conn, 999)


def test_cascade_on_user_delete(db_conn, alice_id) -> None:
    devices.create(db_conn, address="aa", name="d", owner_user_id=alice_id)
    db_conn.execute("DELETE FROM users WHERE id = ?", (alice_id,))
    assert devices.list_all(db_conn) == []


def test_create_stores_addr_type(db_conn, alice_id) -> None:
    did = devices.create(
        db_conn,
        address="f6:8c:f2:d3:ea:e7",
        name="stm",
        owner_user_id=alice_id,
        addr_type="random",
    )
    d = devices.get_by_id(db_conn, did)
    assert d is not None
    assert d.addr_type == "random"


def test_create_defaults_addr_type_public(db_conn, alice_id) -> None:
    did = devices.create(
        db_conn, address="aa:bb", name="d", owner_user_id=alice_id
    )
    d = devices.get_by_id(db_conn, did)
    assert d is not None
    assert d.addr_type == "public"
