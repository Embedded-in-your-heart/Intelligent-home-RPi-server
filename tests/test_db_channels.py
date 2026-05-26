import pytest

from home_server.db import channels, devices, users
from home_server.db.channels import (
    ChannelNotFoundError,
    DuplicateChannelNameError,
    InvalidChannelTypeError,
)


@pytest.fixture
def device_id(db_conn) -> int:
    uid = users.create(db_conn, username="alice", password_hash="h")
    return devices.create(db_conn, address="aa:bb", name="dev", owner_user_id=uid)


def test_create_display_channel(db_conn, device_id) -> None:
    cid = channels.create(
        db_conn,
        device_id=device_id,
        name="Temperature",
        type="display",
        char_uuid="00002a6e-0000-1000-8000-00805f9b34fb",
        data_format="float32_le",
        unit="°C",
    )
    ch = channels.get_by_id(db_conn, cid)
    assert ch is not None
    assert ch.type == "display"
    assert ch.unit == "°C"


def test_create_controller_channel(db_conn, device_id) -> None:
    cid = channels.create(
        db_conn,
        device_id=device_id,
        name="LED",
        type="controller",
        char_uuid="abc",
        data_format="uint8",
    )
    ch = channels.get_by_id(db_conn, cid)
    assert ch is not None
    assert ch.type == "controller"
    assert ch.unit is None


def test_invalid_type_rejected(db_conn, device_id) -> None:
    with pytest.raises(InvalidChannelTypeError):
        channels.create(
            db_conn,
            device_id=device_id,
            name="x",
            type="invalid",  # type: ignore[arg-type]
            char_uuid="u",
            data_format="uint8",
        )


def test_duplicate_name_per_device(db_conn, device_id) -> None:
    channels.create(
        db_conn,
        device_id=device_id,
        name="Temp",
        type="display",
        char_uuid="u",
        data_format="float32_le",
    )
    with pytest.raises(DuplicateChannelNameError):
        channels.create(
            db_conn,
            device_id=device_id,
            name="Temp",
            type="display",
            char_uuid="u",
            data_format="float32_le",
        )


def test_same_name_different_devices_ok(db_conn) -> None:
    uid = users.create(db_conn, username="u", password_hash="h")
    d1 = devices.create(db_conn, address="a1", name="d1", owner_user_id=uid)
    d2 = devices.create(db_conn, address="a2", name="d2", owner_user_id=uid)
    channels.create(
        db_conn, device_id=d1, name="Temp", type="display", char_uuid="u", data_format="uint8"
    )
    channels.create(
        db_conn, device_id=d2, name="Temp", type="display", char_uuid="u", data_format="uint8"
    )


def test_list_by_device(db_conn, device_id) -> None:
    channels.create(
        db_conn, device_id=device_id, name="A", type="display", char_uuid="u1", data_format="uint8"
    )
    channels.create(
        db_conn,
        device_id=device_id,
        name="B",
        type="controller",
        char_uuid="u2",
        data_format="uint8",
    )
    chs = channels.list_by_device(db_conn, device_id)
    assert [c.name for c in chs] == ["A", "B"]


def test_delete(db_conn, device_id) -> None:
    cid = channels.create(
        db_conn, device_id=device_id, name="A", type="display", char_uuid="u", data_format="uint8"
    )
    channels.delete(db_conn, cid)
    assert channels.get_by_id(db_conn, cid) is None


def test_delete_missing(db_conn) -> None:
    with pytest.raises(ChannelNotFoundError):
        channels.delete(db_conn, 999)


def test_cascade_on_device_delete(db_conn, device_id) -> None:
    channels.create(
        db_conn, device_id=device_id, name="A", type="display", char_uuid="u", data_format="uint8"
    )
    devices.delete(db_conn, device_id)
    assert channels.list_all(db_conn) == []
