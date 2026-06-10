from collections.abc import Callable

import pytest

from home_server.ble import parser
from home_server.ble.mock_manager import MockBLEManager
from home_server.ble.rate_limiter import RateLimiter
from home_server.db import devices, readings, users
from home_server.db.channels import ChannelNotFoundError
from home_server.services.channel_service import (
    ChannelService,
    DuplicateChannelUuidError,
    UnknownWindowError,
    WrongChannelTypeError,
)

ADDR = "AA:BB:CC:DD:EE:FF"
CTRL_UUID = "0000aaaa-0000-1000-8000-00805f9b34fb"
DISP_UUID = "0000bbbb-0000-1000-8000-00805f9b34fb"


@pytest.fixture
def device_id(db_conn) -> int:
    uid = users.create(db_conn, username="u", password_hash="h")
    return devices.create(db_conn, address=ADDR, name="dev", owner_user_id=uid)


def _make_service(
    *,
    on_reading: Callable[[int, float, str], None] | None = None,
    min_interval: float = 1.0,
    clock: Callable[[], float] | None = None,
) -> tuple[ChannelService, MockBLEManager]:
    mock = MockBLEManager()
    mock.connect(ADDR)  # so write() is permitted
    limiter = (
        RateLimiter(min_interval)
        if clock is None
        else RateLimiter(min_interval, clock=clock)
    )
    svc = ChannelService(mock, limiter, on_reading or (lambda cid, value, ts: None))
    return svc, mock


def test_add_channel_rejects_unknown_format(db_conn, device_id) -> None:
    svc, _ = _make_service()
    with pytest.raises(parser.UnknownFormatError):
        svc.add_channel(
            db_conn,
            device_id=device_id,
            name="bad",
            type="display",
            char_uuid=DISP_UUID,
            data_format="nonsense",
        )


def test_add_channel_rejects_duplicate_uuid_on_same_device(db_conn, device_id) -> None:
    svc, _ = _make_service()
    svc.add_channel(
        db_conn,
        device_id=device_id,
        name="temp",
        type="display",
        char_uuid=DISP_UUID,
        data_format="uint8",
    )
    with pytest.raises(DuplicateChannelUuidError):
        svc.add_channel(
            db_conn,
            device_id=device_id,
            name="temp2",
            type="display",
            char_uuid=DISP_UUID,
            data_format="uint8",
        )


def test_write_command_encodes_and_writes(db_conn, device_id) -> None:
    svc, mock = _make_service()
    channel = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="led",
        type="controller",
        char_uuid=CTRL_UUID,
        data_format="uint8",
    )
    svc.write_command(db_conn, channel_id=channel.id, raw_value=1)
    assert mock.writes_for(ADDR, CTRL_UUID) == [parser.encode(1, "uint8")]


def test_write_command_rejects_display_channel(db_conn, device_id) -> None:
    svc, _ = _make_service()
    channel = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="temp",
        type="display",
        char_uuid=DISP_UUID,
        data_format="float32_le",
    )
    with pytest.raises(WrongChannelTypeError):
        svc.write_command(db_conn, channel_id=channel.id, raw_value=1)


def test_write_command_missing_channel(db_conn, device_id) -> None:
    svc, _ = _make_service()
    with pytest.raises(ChannelNotFoundError):
        svc.write_command(db_conn, channel_id=999, raw_value=1)


def test_handle_notify_decodes_emits_and_persists(db_conn, device_id) -> None:
    received: list[tuple[int, float, str]] = []
    svc, _ = _make_service(on_reading=lambda cid, value, ts: received.append((cid, value, ts)))
    channel = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="temp",
        type="display",
        char_uuid=DISP_UUID,
        data_format="uint8",
    )
    value = svc.handle_notify(db_conn, channel_id=channel.id, raw_bytes=b"\x2a")
    assert value == 42.0
    assert received[0][0] == channel.id
    assert received[0][1] == 42.0
    assert readings.count_by_channel(db_conn, channel.id) == 1


def test_handle_notify_rate_limits_persistence_but_always_emits(db_conn, device_id) -> None:
    now = [0.0]
    received: list[tuple[int, float, str]] = []
    svc, _ = _make_service(
        on_reading=lambda cid, value, ts: received.append((cid, value, ts)),
        min_interval=10.0,
        clock=lambda: now[0],
    )
    channel = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="temp",
        type="display",
        char_uuid=DISP_UUID,
        data_format="uint8",
    )
    svc.handle_notify(db_conn, channel_id=channel.id, raw_bytes=b"\x01")
    svc.handle_notify(db_conn, channel_id=channel.id, raw_bytes=b"\x02")  # within interval
    assert readings.count_by_channel(db_conn, channel.id) == 1  # 2nd not persisted
    assert len(received) == 2  # both pushed to UI


def test_handle_notify_persists_even_if_callback_raises(db_conn, device_id) -> None:
    def boom(cid: int, value: float, ts: str) -> None:
        raise RuntimeError("UI client gone")

    svc, _ = _make_service(on_reading=boom)
    channel = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="temp",
        type="display",
        char_uuid=DISP_UUID,
        data_format="uint8",
    )
    value = svc.handle_notify(db_conn, channel_id=channel.id, raw_bytes=b"\x07")
    assert value == 7.0
    assert readings.count_by_channel(db_conn, channel.id) == 1


def test_get_history_returns_readings(db_conn, device_id) -> None:
    svc, _ = _make_service()
    channel = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="temp",
        type="display",
        char_uuid=DISP_UUID,
        data_format="uint8",
    )
    svc.handle_notify(db_conn, channel_id=channel.id, raw_bytes=b"\x05")
    history = svc.get_history(db_conn, channel.id)
    assert len(history) == 1
    assert history[0].value == 5.0


def test_get_history_windowed_filters_to_window(db_conn, device_id) -> None:
    from datetime import UTC, datetime, timedelta

    svc, _ = _make_service()
    channel = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="temp",
        type="display",
        char_uuid=DISP_UUID,
        data_format="uint8",
    )
    now = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
    # Two readings inside the 1m window, one well outside it.
    readings.insert(
        db_conn, channel_id=channel.id, value=10.0,
        recorded_at=now - timedelta(seconds=30),
    )
    readings.insert(
        db_conn, channel_id=channel.id, value=20.0,
        recorded_at=now - timedelta(seconds=20),
    )
    readings.insert(
        db_conn, channel_id=channel.id, value=99.0,
        recorded_at=now - timedelta(minutes=5),
    )
    points = svc.get_history_windowed(db_conn, channel.id, "1m", now=now)
    # 1m uses 1s buckets, so the two in-window readings stay distinct; the
    # 5-minute-old reading is excluded.
    assert [v for v, _ in points] == [10.0, 20.0]


def test_get_history_windowed_rejects_unknown_window(db_conn, device_id) -> None:
    svc, _ = _make_service()
    channel = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="temp",
        type="display",
        char_uuid=DISP_UUID,
        data_format="uint8",
    )
    with pytest.raises(UnknownWindowError):
        svc.get_history_windowed(db_conn, channel.id, "bogus")


def test_list_by_device(db_conn, device_id) -> None:
    svc, _ = _make_service()
    svc.add_channel(
        db_conn,
        device_id=device_id,
        name="temp",
        type="display",
        char_uuid=DISP_UUID,
        data_format="uint8",
    )
    assert len(svc.list_by_device(db_conn, device_id)) == 1


def test_rate_limiter_is_per_channel(db_conn, device_id) -> None:
    # Notifies on two different channels within the same interval must both
    # persist — a global (non-per-channel) key would drop the second.
    now = [0.0]
    svc, _ = _make_service(min_interval=10.0, clock=lambda: now[0])
    ch1 = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="a",
        type="display",
        char_uuid=DISP_UUID,
        data_format="uint8",
    )
    ch2 = svc.add_channel(
        db_conn,
        device_id=device_id,
        name="b",
        type="display",
        char_uuid=CTRL_UUID,
        data_format="uint8",
    )
    svc.handle_notify(db_conn, channel_id=ch1.id, raw_bytes=b"\x01")
    svc.handle_notify(db_conn, channel_id=ch2.id, raw_bytes=b"\x02")
    assert readings.count_by_channel(db_conn, ch1.id) == 1
    assert readings.count_by_channel(db_conn, ch2.id) == 1
