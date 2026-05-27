"""User registration and authentication (bcrypt password hashing)."""

from __future__ import annotations

import sqlite3

import bcrypt

from home_server.db import users
from home_server.db.users import User


class WeakPasswordError(ValueError):
    pass


_MIN_PASSWORD_LEN = 8


def hash_password(password: str, *, cost: int = 12) -> str:
    salt = bcrypt.gensalt(rounds=cost)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def register(
    conn: sqlite3.Connection,
    *,
    username: str,
    password: str,
    cost: int = 12,
) -> int:
    if len(password) < _MIN_PASSWORD_LEN:
        raise WeakPasswordError(
            f"password must be at least {_MIN_PASSWORD_LEN} characters"
        )
    password_hash = hash_password(password, cost=cost)
    return users.create(conn, username=username, password_hash=password_hash)


def authenticate(
    conn: sqlite3.Connection,
    *,
    username: str,
    password: str,
) -> User | None:
    user = users.get_by_username(conn, username)
    if user is None:
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        return None
    return user
