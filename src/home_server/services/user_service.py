"""User registration and authentication (bcrypt password hashing)."""

from __future__ import annotations

import sqlite3

import bcrypt

from home_server.db import users
from home_server.db.users import User


class WeakPasswordError(ValueError):
    pass


_MIN_PASSWORD_LEN = 8
# bcrypt silently truncates input beyond 72 bytes, so reject longer passwords
# to avoid two distinct passwords hashing to the same value.
_MAX_PASSWORD_BYTES = 72


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
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise WeakPasswordError(
            f"password must be at most {_MAX_PASSWORD_BYTES} bytes"
        )
    password_hash = hash_password(password, cost=cost)
    return users.create(conn, username=username, password_hash=password_hash)


def seed_admin(
    conn: sqlite3.Connection,
    *,
    username: str,
    password: str,
    cost: int = 12,
) -> bool:
    """Create the admin account from configured credentials if it is absent.

    Intended to run once at startup so there is always a login. Returns True
    if a new account was created, False if the username already existed (in
    which case the stored password is left untouched). Raises WeakPasswordError
    if the configured password fails the same rules as normal registration.
    """
    if users.get_by_username(conn, username) is not None:
        return False
    register(conn, username=username, password=password, cost=cost)
    return True


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
