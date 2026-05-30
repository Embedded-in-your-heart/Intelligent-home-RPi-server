"""Shared pytest fixtures."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from home_server.config import Config
from home_server.db import connection
from home_server.web import create_app

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


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    # File-backed DB (not :memory:) so each per-request connection sees the
    # same database — distinct :memory: connections would each be empty.
    db_path = tmp_path / "test.db"
    connection.initialize(db_path)
    config = Config(
        db_path=db_path,
        secret_key="test-secret",
        host="127.0.0.1",
        port=5000,
        log_level="INFO",
        ble_scan_duration=1.0,
        reading_min_interval=1.0,
        admin_username="admin",
        admin_password=None,
        debug=True,
    )
    flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()
