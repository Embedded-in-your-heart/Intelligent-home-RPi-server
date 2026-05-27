"""Per-request SQLite connection helper.

Kept separate from ``web/__init__`` so blueprints can import ``get_conn``
without creating an import cycle through the application factory.
"""

from __future__ import annotations

import sqlite3

from flask import current_app, g

from home_server.db import connection


def get_conn() -> sqlite3.Connection:
    """Return the per-request connection, opening one on first use."""
    if "conn" not in g:
        g.conn = connection.connect(current_app.config["DB_PATH"])
    conn: sqlite3.Connection = g.conn
    return conn
