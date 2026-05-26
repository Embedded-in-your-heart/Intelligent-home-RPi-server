"""channels table repository."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

ChannelType = Literal["controller", "display"]


class InvalidChannelTypeError(ValueError):
    pass


class DuplicateChannelNameError(ValueError):
    pass


class ChannelNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class Channel:
    id: int
    device_id: int
    name: str
    type: ChannelType
    char_uuid: str
    data_format: str
    unit: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Channel:
        return cls(
            id=row["id"],
            device_id=row["device_id"],
            name=row["name"],
            type=row["type"],
            char_uuid=row["char_uuid"],
            data_format=row["data_format"],
            unit=row["unit"],
            created_at=row["created_at"],
        )


def create(
    conn: sqlite3.Connection,
    *,
    device_id: int,
    name: str,
    type: ChannelType,
    char_uuid: str,
    data_format: str,
    unit: str | None = None,
) -> int:
    if type not in ("controller", "display"):
        raise InvalidChannelTypeError(f"invalid type: {type!r}")
    try:
        cur = conn.execute(
            """
            INSERT INTO channels (device_id, name, type, char_uuid, data_format, unit)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (device_id, name, type, char_uuid, data_format, unit),
        )
    except sqlite3.IntegrityError as e:
        msg = str(e).upper()
        if "UNIQUE" in msg:
            raise DuplicateChannelNameError(
                f"channel name {name!r} already exists on device {device_id}"
            ) from e
        raise
    channel_id = cur.lastrowid
    assert channel_id is not None
    return channel_id


def get_by_id(conn: sqlite3.Connection, channel_id: int) -> Channel | None:
    row = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
    return Channel.from_row(row) if row else None


def list_by_device(conn: sqlite3.Connection, device_id: int) -> list[Channel]:
    rows = conn.execute(
        "SELECT * FROM channels WHERE device_id = ? ORDER BY id",
        (device_id,),
    ).fetchall()
    return [Channel.from_row(r) for r in rows]


def list_all(conn: sqlite3.Connection) -> list[Channel]:
    rows = conn.execute("SELECT * FROM channels ORDER BY id").fetchall()
    return [Channel.from_row(r) for r in rows]


def delete(conn: sqlite3.Connection, channel_id: int) -> None:
    cur = conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    if cur.rowcount == 0:
        raise ChannelNotFoundError(f"channel not found: id={channel_id}")
