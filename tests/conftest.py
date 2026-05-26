"""Shared pytest fixtures."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

_SCHEMA_PATH = Path(__file__).parent.parent / "src" / "home_server" / "db" / "schema.sql"


@pytest.fixture
def db_conn() -> Iterator[sqlite3.Connection]:
    """Fresh in-memory SQLite with the full schema applied."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        yield conn
    finally:
        conn.close()
