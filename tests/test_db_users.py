import pytest

from home_server.db import users
from home_server.db.users import DuplicateUsernameError, UserNotFoundError


def test_create_and_get_by_id(db_conn) -> None:
    uid = users.create(db_conn, username="alice", password_hash="hash-a")
    user = users.get_by_id(db_conn, uid)
    assert user is not None
    assert user.username == "alice"
    assert user.password_hash == "hash-a"
    assert user.created_at  # populated by DEFAULT


def test_get_by_username(db_conn) -> None:
    users.create(db_conn, username="alice", password_hash="h")
    user = users.get_by_username(db_conn, "alice")
    assert user is not None
    assert user.username == "alice"


def test_get_missing_returns_none(db_conn) -> None:
    assert users.get_by_id(db_conn, 999) is None
    assert users.get_by_username(db_conn, "ghost") is None


def test_duplicate_username_rejected(db_conn) -> None:
    users.create(db_conn, username="alice", password_hash="h1")
    with pytest.raises(DuplicateUsernameError):
        users.create(db_conn, username="alice", password_hash="h2")


def test_update_password(db_conn) -> None:
    uid = users.create(db_conn, username="alice", password_hash="old")
    users.update_password(db_conn, uid, "new")
    assert users.get_by_id(db_conn, uid).password_hash == "new"


def test_update_password_missing_user(db_conn) -> None:
    with pytest.raises(UserNotFoundError):
        users.update_password(db_conn, 999, "x")
