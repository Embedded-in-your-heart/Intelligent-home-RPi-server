"""SQLite connection helpers and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from home_server.ble.address import infer_addr_type

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sensible pragmas for this app.

    Each thread should call this for its own connection — sqlite3 connections
    are not safe to share across threads by default.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent in-place migrations for databases created before a column
    existed. Each block runs only when its target column is missing, so values
    written later (by scan or the user) are never overwritten.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(devices)")}
    if "addr_type" not in cols:
        conn.execute(
            "ALTER TABLE devices ADD COLUMN addr_type TEXT NOT NULL "
            "DEFAULT 'public' CHECK (addr_type IN ('public', 'random'))"
        )
        for row in conn.execute("SELECT id, address FROM devices").fetchall():
            conn.execute(
                "UPDATE devices SET addr_type = ? WHERE id = ?",
                (infer_addr_type(row["address"]), row["id"]),
            )


def initialize(db_path: Path) -> None:
    """Create parent dir, run schema.sql, apply migrations. Safe to repeat."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        apply_migrations(conn)
    finally:
        conn.close()
