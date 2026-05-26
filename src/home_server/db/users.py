"""users table repository."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


class DuplicateUsernameError(ValueError):
    pass


class UserNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class User:
    id: int
    username: str
    password_hash: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> User:
        return cls(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
        )


def create(conn: sqlite3.Connection, *, username: str, password_hash: str) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e).upper():
            raise DuplicateUsernameError(f"username already exists: {username}") from e
        raise
    user_id = cur.lastrowid
    assert user_id is not None
    return user_id


def get_by_id(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return User.from_row(row) if row else None


def get_by_username(conn: sqlite3.Connection, username: str) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return User.from_row(row) if row else None


def update_password(conn: sqlite3.Connection, user_id: int, password_hash: str) -> None:
    cur = conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (password_hash, user_id),
    )
    if cur.rowcount == 0:
        raise UserNotFoundError(f"user not found: id={user_id}")
