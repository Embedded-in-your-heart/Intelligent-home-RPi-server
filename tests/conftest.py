"""Shared pytest fixtures."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from home_server.ble.mock_manager import MockBLEManager
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
def mock_ble() -> MockBLEManager:
    return MockBLEManager()


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
        debug=True,
    )
    flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def _csrf_token(client: FlaskClient, path: str) -> str:
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match, f"csrf_token not found at {path}"
    return match.group(1)


@pytest.fixture
def logged_in_client(client: FlaskClient) -> FlaskClient:
    token = _csrf_token(client, "/auth/register")
    client.post(
        "/auth/register",
        data={
            "username": "tester",
            "password": "password1",
            "confirm": "password1",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    return client
