"""readings table repository (sensor data history)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

# SQLite's CURRENT_TIMESTAMP format. All timestamps stored as UTC strings in this
# format so lexicographic comparison matches chronological order.
_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _format_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        # Naive datetime — assume UTC.
        return dt.strftime(_TS_FMT)
    return dt.astimezone(UTC).strftime(_TS_FMT)


@dataclass(frozen=True)
class Reading:
    id: int
    channel_id: int
    value: float
    recorded_at: str  # "YYYY-MM-DD HH:MM:SS" in UTC

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Reading:
        return cls(
            id=row["id"],
            channel_id=row["channel_id"],
            value=row["value"],
            recorded_at=row["recorded_at"],
        )


def insert(
    conn: sqlite3.Connection,
    *,
    channel_id: int,
    value: float,
    recorded_at: datetime | None = None,
) -> int:
    if recorded_at is None:
        cur = conn.execute(
            "INSERT INTO readings (channel_id, value) VALUES (?, ?)",
            (channel_id, value),
        )
    else:
        cur = conn.execute(
            "INSERT INTO readings (channel_id, value, recorded_at) VALUES (?, ?, ?)",
            (channel_id, value, _format_ts(recorded_at)),
        )
    rid = cur.lastrowid
    assert rid is not None
    return rid


def list_by_channel(
    conn: sqlite3.Connection,
    channel_id: int,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
) -> list[Reading]:
    """Return readings sorted oldest → newest. ``since`` is inclusive, ``until`` exclusive."""
    sql = "SELECT * FROM readings WHERE channel_id = ?"
    params: list[object] = [channel_id]
    if since is not None:
        sql += " AND recorded_at >= ?"
        params.append(_format_ts(since))
    if until is not None:
        sql += " AND recorded_at < ?"
        params.append(_format_ts(until))
    sql += " ORDER BY recorded_at ASC, id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [Reading.from_row(r) for r in rows]


def count_by_channel(conn: sqlite3.Connection, channel_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM readings WHERE channel_id = ?",
        (channel_id,),
    ).fetchone()
    return int(row["n"])


def delete_older_than(
    conn: sqlite3.Connection, channel_id: int, before: datetime
) -> int:
    """Delete readings strictly older than ``before``. Returns number deleted."""
    cur = conn.execute(
        "DELETE FROM readings WHERE channel_id = ? AND recorded_at < ?",
        (channel_id, _format_ts(before)),
    )
    return cur.rowcount
