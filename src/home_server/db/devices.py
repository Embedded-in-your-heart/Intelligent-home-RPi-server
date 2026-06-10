"""devices table repository."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


class DuplicateAddressError(ValueError):
    pass


class DeviceNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class Device:
    id: int
    address: str
    addr_type: str
    name: str
    label: str | None
    owner_user_id: int
    last_connected_at: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Device:
        return cls(
            id=row["id"],
            address=row["address"],
            addr_type=row["addr_type"],
            name=row["name"],
            label=row["label"],
            owner_user_id=row["owner_user_id"],
            last_connected_at=row["last_connected_at"],
            created_at=row["created_at"],
        )

    @property
    def display_name(self) -> str:
        return self.label or self.name


def create(
    conn: sqlite3.Connection,
    *,
    address: str,
    name: str,
    owner_user_id: int,
    addr_type: str = "public",
) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO devices (address, name, owner_user_id, addr_type) "
            "VALUES (?, ?, ?, ?)",
            (address, name, owner_user_id, addr_type),
        )
    except sqlite3.IntegrityError as e:
        msg = str(e).upper()
        if "UNIQUE" in msg:
            raise DuplicateAddressError(f"address already exists: {address}") from e
        raise
    device_id = cur.lastrowid
    assert device_id is not None
    return device_id


def get_by_id(conn: sqlite3.Connection, device_id: int) -> Device | None:
    row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    return Device.from_row(row) if row else None


def get_by_address(conn: sqlite3.Connection, address: str) -> Device | None:
    row = conn.execute("SELECT * FROM devices WHERE address = ?", (address,)).fetchone()
    return Device.from_row(row) if row else None


def list_all(conn: sqlite3.Connection) -> list[Device]:
    rows = conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
    return [Device.from_row(r) for r in rows]


def list_by_owner(conn: sqlite3.Connection, owner_user_id: int) -> list[Device]:
    rows = conn.execute(
        "SELECT * FROM devices WHERE owner_user_id = ? ORDER BY id",
        (owner_user_id,),
    ).fetchall()
    return [Device.from_row(r) for r in rows]


def delete(conn: sqlite3.Connection, device_id: int) -> None:
    cur = conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    if cur.rowcount == 0:
        raise DeviceNotFoundError(f"device not found: id={device_id}")


def touch_last_connected(conn: sqlite3.Connection, device_id: int) -> None:
    """Set last_connected_at to now. Called on status transitions to/from connected."""
    conn.execute(
        "UPDATE devices SET last_connected_at = CURRENT_TIMESTAMP WHERE id = ?",
        (device_id,),
    )


def set_label(conn: sqlite3.Connection, device_id: int, label: str | None) -> None:
    """Write label directly; the caller is responsible for normalisation."""
    cur = conn.execute(
        "UPDATE devices SET label = ? WHERE id = ?", (label, device_id)
    )
    if cur.rowcount == 0:
        raise DeviceNotFoundError(f"device not found: id={device_id}")
