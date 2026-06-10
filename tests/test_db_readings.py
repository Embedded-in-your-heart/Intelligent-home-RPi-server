from datetime import UTC, datetime, timedelta

import pytest

from home_server.db import channels, devices, readings, users


@pytest.fixture
def channel_id(db_conn) -> int:
    uid = users.create(db_conn, username="u", password_hash="h")
    did = devices.create(db_conn, address="a", name="d", owner_user_id=uid)
    return channels.create(
        db_conn,
        device_id=did,
        name="Temperature",
        type="display",
        char_uuid="u",
        data_format="float32_le",
    )


def test_insert_with_default_timestamp(db_conn, channel_id) -> None:
    rid = readings.insert(db_conn, channel_id=channel_id, value=23.5)
    rs = readings.list_by_channel(db_conn, channel_id)
    assert len(rs) == 1
    assert rs[0].id == rid
    assert rs[0].value == 23.5
    assert rs[0].recorded_at  # DEFAULT populated


def test_insert_with_explicit_timestamp(db_conn, channel_id) -> None:
    ts = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
    readings.insert(db_conn, channel_id=channel_id, value=1.0, recorded_at=ts)
    rs = readings.list_by_channel(db_conn, channel_id)
    assert rs[0].recorded_at == "2026-05-27 12:00:00"


def _insert_at(db_conn, channel_id, value, base, **delta_kwargs):
    readings.insert(
        db_conn,
        channel_id=channel_id,
        value=value,
        recorded_at=base + timedelta(**delta_kwargs),
    )


def test_list_ordered_oldest_first(db_conn, channel_id) -> None:
    base = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
    _insert_at(db_conn, channel_id, 2.0, base, minutes=2)
    _insert_at(db_conn, channel_id, 1.0, base, minutes=1)
    _insert_at(db_conn, channel_id, 3.0, base, minutes=3)
    values = [r.value for r in readings.list_by_channel(db_conn, channel_id)]
    assert values == [1.0, 2.0, 3.0]


def test_since_filter_inclusive(db_conn, channel_id) -> None:
    base = datetime(2026, 5, 27, 0, 0, 0, tzinfo=UTC)
    readings.insert(db_conn, channel_id=channel_id, value=1.0, recorded_at=base)
    _insert_at(db_conn, channel_id, 2.0, base, hours=1)
    _insert_at(db_conn, channel_id, 3.0, base, hours=2)

    rs = readings.list_by_channel(db_conn, channel_id, since=base + timedelta(hours=1))
    assert [r.value for r in rs] == [2.0, 3.0]


def test_until_filter_exclusive(db_conn, channel_id) -> None:
    base = datetime(2026, 5, 27, 0, 0, 0, tzinfo=UTC)
    readings.insert(db_conn, channel_id=channel_id, value=1.0, recorded_at=base)
    _insert_at(db_conn, channel_id, 2.0, base, hours=1)
    _insert_at(db_conn, channel_id, 3.0, base, hours=2)

    rs = readings.list_by_channel(db_conn, channel_id, until=base + timedelta(hours=2))
    assert [r.value for r in rs] == [1.0, 2.0]


def test_limit(db_conn, channel_id) -> None:
    for i in range(5):
        readings.insert(db_conn, channel_id=channel_id, value=float(i))
    rs = readings.list_by_channel(db_conn, channel_id, limit=3)
    assert len(rs) == 3


def test_count_by_channel(db_conn, channel_id) -> None:
    for i in range(7):
        readings.insert(db_conn, channel_id=channel_id, value=float(i))
    assert readings.count_by_channel(db_conn, channel_id) == 7


def test_delete_older_than(db_conn, channel_id) -> None:
    base = datetime(2026, 5, 27, 0, 0, 0, tzinfo=UTC)
    for h in range(5):
        _insert_at(db_conn, channel_id, float(h), base, hours=h)

    n_deleted = readings.delete_older_than(db_conn, channel_id, base + timedelta(hours=3))
    assert n_deleted == 3
    remaining = [r.value for r in readings.list_by_channel(db_conn, channel_id)]
    assert remaining == [3.0, 4.0]


def test_downsample_averages_into_buckets(db_conn, channel_id) -> None:
    base = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
    # Two readings in the first 60s bucket, one in the next.
    _insert_at(db_conn, channel_id, 10.0, base, seconds=10)
    _insert_at(db_conn, channel_id, 20.0, base, seconds=30)
    _insert_at(db_conn, channel_id, 5.0, base, seconds=70)
    points = readings.downsample_since(
        db_conn, channel_id, since=base, bucket_seconds=60
    )
    assert [v for v, _ in points] == [15.0, 5.0]  # avg(10,20)=15, then 5
    # recorded_at is the latest timestamp within each bucket.
    assert points[0][1] == "2026-05-27 12:00:30"
    assert points[1][1] == "2026-05-27 12:01:10"


def test_downsample_excludes_readings_before_since(db_conn, channel_id) -> None:
    base = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
    _insert_at(db_conn, channel_id, 1.0, base, seconds=-30)  # before since
    _insert_at(db_conn, channel_id, 2.0, base, seconds=30)
    points = readings.downsample_since(
        db_conn, channel_id, since=base, bucket_seconds=60
    )
    assert [v for v, _ in points] == [2.0]


def test_cascade_on_channel_delete(db_conn, channel_id) -> None:
    readings.insert(db_conn, channel_id=channel_id, value=1.0)
    channels.delete(db_conn, channel_id)
    assert readings.count_by_channel(db_conn, channel_id) == 0


def test_readings_are_scoped_per_channel(db_conn) -> None:
    uid = users.create(db_conn, username="u", password_hash="h")
    did = devices.create(db_conn, address="a", name="d", owner_user_id=uid)
    c1 = channels.create(
        db_conn, device_id=did, name="A", type="display", char_uuid="u", data_format="uint8"
    )
    c2 = channels.create(
        db_conn, device_id=did, name="B", type="display", char_uuid="u", data_format="uint8"
    )
    readings.insert(db_conn, channel_id=c1, value=1.0)
    readings.insert(db_conn, channel_id=c2, value=2.0)
    assert readings.count_by_channel(db_conn, c1) == 1
    assert readings.count_by_channel(db_conn, c2) == 1
