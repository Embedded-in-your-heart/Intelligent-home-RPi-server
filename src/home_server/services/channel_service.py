"""Channel service: CRUD, control writes, and notify handling.

Notify handling is a plain method (`handle_notify`) taking the caller's
connection; the BLE worker-thread wiring is implemented in
`services/ble_runtime.py` (BleRuntime.subscribe_channel). UI push (on_reading)
is unthrottled; DB persistence is rate-limited per channel.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from home_server.ble import parser
from home_server.ble.interface import BLEManager
from home_server.ble.rate_limiter import RateLimiter
from home_server.db import channels, devices, readings
from home_server.db.channels import Channel, ChannelNotFoundError, ChannelType
from home_server.db.readings import Reading

log = logging.getLogger(__name__)

# (channel_id, value, iso_utc_timestamp) pushed to the UI on every notify.
ReadingCallback = Callable[[int, float, str], None]


# A 0/1 flag channel is considered "on" once its value reaches this threshold.
_FLAG_ON_THRESHOLD = 0.5


class WrongChannelTypeError(ValueError):
    pass


class DuplicateChannelUuidError(ValueError):
    pass


class ChannelService:
    def __init__(
        self,
        ble: BLEManager,
        limiter: RateLimiter,
        on_reading: ReadingCallback,
    ) -> None:
        self._ble = ble
        self._limiter = limiter
        self._on_reading = on_reading

    def add_channel(
        self,
        conn: sqlite3.Connection,
        *,
        device_id: int,
        name: str,
        type: ChannelType,
        char_uuid: str,
        data_format: str,
        unit: str | None = None,
    ) -> Channel:
        if data_format not in parser.supported_formats():
            raise parser.UnknownFormatError(f"unknown data_format: {data_format!r}")
        if any(
            c.char_uuid == char_uuid for c in channels.list_by_device(conn, device_id)
        ):
            raise DuplicateChannelUuidError(
                f"char_uuid {char_uuid!r} already exists on device {device_id}"
            )
        channel_id = channels.create(
            conn,
            device_id=device_id,
            name=name,
            type=type,
            char_uuid=char_uuid,
            data_format=data_format,
            unit=unit,
        )
        channel = channels.get_by_id(conn, channel_id)
        assert channel is not None
        return channel

    def write_command(
        self,
        conn: sqlite3.Connection,
        *,
        channel_id: int,
        raw_value: float,
    ) -> None:
        channel = channels.get_by_id(conn, channel_id)
        if channel is None:
            raise ChannelNotFoundError(f"channel not found: id={channel_id}")
        if channel.type != "controller":
            raise WrongChannelTypeError(f"channel {channel_id} is not a controller")
        data = parser.encode(raw_value, channel.data_format)
        device = devices.get_by_id(conn, channel.device_id)
        assert device is not None
        self._ble.write(device.address, channel.char_uuid, data)

    def handle_notify(
        self,
        conn: sqlite3.Connection,
        *,
        channel_id: int,
        raw_bytes: bytes,
    ) -> float:
        channel = channels.get_by_id(conn, channel_id)
        if channel is None:
            raise ChannelNotFoundError(f"channel not found: id={channel_id}")
        value = parser.decode(raw_bytes, channel.data_format)
        # ISO 8601 UTC for the UI callback, e.g. "2026-05-27T10:00:00+00:00".
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        # UI push is best-effort: a failing callback (e.g. a dead SocketIO
        # client in phase 3e) must never drop the rate-limited DB write below.
        try:
            self._on_reading(channel_id, value, timestamp)  # unthrottled
        except Exception:
            log.warning(
                "on_reading callback raised for channel %d", channel_id, exc_info=True
            )
        if self._limiter.should_emit(str(channel_id)):
            readings.insert(conn, channel_id=channel_id, value=value)
        return value

    def get_history(
        self,
        conn: sqlite3.Connection,
        channel_id: int,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[Reading]:
        return readings.list_by_channel(
            conn, channel_id, since=since, until=until, limit=limit
        )

    def get_flag_state(
        self, conn: sqlite3.Connection, channel_id: int
    ) -> tuple[Reading | None, Reading | None]:
        """State for a 0/1 flag channel.

        Returns ``(latest, last_on)`` where ``latest`` is the most recent
        reading (the current flag state) and ``last_on`` is the most recent
        reading at which the flag became 1. Either may be None when there is
        no matching reading yet.
        """
        latest = readings.latest_by_channel(conn, channel_id)
        last_on = readings.latest_at_or_above(conn, channel_id, _FLAG_ON_THRESHOLD)
        return latest, last_on

    def list_by_device(
        self, conn: sqlite3.Connection, device_id: int
    ) -> list[Channel]:
        return channels.list_by_device(conn, device_id)
