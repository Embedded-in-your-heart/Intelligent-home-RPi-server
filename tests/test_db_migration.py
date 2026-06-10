import sqlite3

from home_server.db import connection

# Pre-addr_type devices schema (before this migration existed).
_OLD_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _old_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(_OLD_SCHEMA)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (1, 'u', 'h')"
    )
    return conn


def test_migration_adds_column_and_backfills_by_inference() -> None:
    conn = _old_db()
    conn.execute(
        "INSERT INTO devices (address, name, owner_user_id) "
        "VALUES ('f6:8c:f2:d3:ea:e7', 'stm', 1)"
    )
    conn.execute(
        "INSERT INTO devices (address, name, owner_user_id) "
        "VALUES ('aa:bb:cc:dd:ee:ff', 'pub', 1)"
    )
    connection.apply_migrations(conn)
    rows = {
        r["address"]: r["addr_type"]
        for r in conn.execute("SELECT address, addr_type FROM devices")
    }
    assert rows["f6:8c:f2:d3:ea:e7"] == "random"
    assert rows["aa:bb:cc:dd:ee:ff"] == "public"
    conn.close()


def test_migration_idempotent_preserves_existing_values() -> None:
    conn = _old_db()
    conn.execute(
        "INSERT INTO devices (address, name, owner_user_id) "
        "VALUES ('f6:8c:f2:d3:ea:e7', 'stm', 1)"
    )
    connection.apply_migrations(conn)
    # An authoritative correction (e.g. scan reported public) is later stored.
    conn.execute(
        "UPDATE devices SET addr_type = 'public' "
        "WHERE address = 'f6:8c:f2:d3:ea:e7'"
    )
    connection.apply_migrations(conn)  # second run must not touch the column
    row = conn.execute(
        "SELECT addr_type FROM devices WHERE address = 'f6:8c:f2:d3:ea:e7'"
    ).fetchone()
    assert row["addr_type"] == "public"
    conn.close()


def test_migration_adds_label_column_as_null() -> None:
    # Old DB without the label column; after migration the column must exist
    # and existing rows must have NULL as their label value.
    conn = _old_db()
    conn.execute(
        "INSERT INTO devices (address, name, owner_user_id) "
        "VALUES ('aa:bb:cc:dd:ee:ff', 'sensor', 1)"
    )
    connection.apply_migrations(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(devices)")}
    assert "label" in cols
    row = conn.execute(
        "SELECT label FROM devices WHERE address = 'aa:bb:cc:dd:ee:ff'"
    ).fetchone()
    assert row["label"] is None
    conn.close()


def test_migration_label_idempotent() -> None:
    # Running apply_migrations twice must not overwrite a label written in between.
    conn = _old_db()
    conn.execute(
        "INSERT INTO devices (address, name, owner_user_id) "
        "VALUES ('aa:bb:cc:dd:ee:ff', 'sensor', 1)"
    )
    connection.apply_migrations(conn)
    conn.execute(
        "UPDATE devices SET label = 'Kitchen' WHERE address = 'aa:bb:cc:dd:ee:ff'"
    )
    connection.apply_migrations(conn)  # second run must not touch the column
    row = conn.execute(
        "SELECT label FROM devices WHERE address = 'aa:bb:cc:dd:ee:ff'"
    ).fetchone()
    assert row["label"] == "Kitchen"
    conn.close()
