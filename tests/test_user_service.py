import pytest

from home_server.db.users import DuplicateUsernameError
from home_server.services import user_service
from home_server.services.user_service import WeakPasswordError


def test_register_and_authenticate(db_conn) -> None:
    uid = user_service.register(db_conn, username="alice", password="password1", cost=4)
    assert uid > 0
    user = user_service.authenticate(db_conn, username="alice", password="password1")
    assert user is not None
    assert user.id == uid
    assert user.username == "alice"


def test_register_rejects_weak_password(db_conn) -> None:
    with pytest.raises(WeakPasswordError):
        user_service.register(db_conn, username="bob", password="short", cost=4)


def test_register_rejects_password_over_72_bytes(db_conn) -> None:
    with pytest.raises(WeakPasswordError):
        user_service.register(db_conn, username="bob", password="a" * 73, cost=4)


def test_register_rejects_duplicate_username(db_conn) -> None:
    user_service.register(db_conn, username="alice", password="password1", cost=4)
    with pytest.raises(DuplicateUsernameError):
        user_service.register(db_conn, username="alice", password="password2", cost=4)


def test_authenticate_wrong_password_returns_none(db_conn) -> None:
    user_service.register(db_conn, username="alice", password="password1", cost=4)
    assert user_service.authenticate(db_conn, username="alice", password="wrong-pass") is None


def test_authenticate_unknown_user_returns_none(db_conn) -> None:
    assert user_service.authenticate(db_conn, username="ghost", password="password1") is None


def test_password_hash_is_not_plaintext(db_conn) -> None:
    user_service.register(db_conn, username="alice", password="password1", cost=4)
    user = user_service.authenticate(db_conn, username="alice", password="password1")
    assert user is not None
    assert user.password_hash != "password1"
    assert user.password_hash.startswith("$2")  # bcrypt prefix


def test_seed_admin_creates_when_absent(db_conn) -> None:
    created = user_service.seed_admin(db_conn, username="admin", password="admin123", cost=4)
    assert created is True
    assert user_service.authenticate(db_conn, username="admin", password="admin123") is not None


def test_seed_admin_is_idempotent_and_keeps_existing_password(db_conn) -> None:
    user_service.register(db_conn, username="admin", password="original-pw", cost=4)
    created = user_service.seed_admin(db_conn, username="admin", password="different-pw", cost=4)
    assert created is False
    # Existing password is left untouched; the env value is ignored.
    assert user_service.authenticate(db_conn, username="admin", password="original-pw") is not None
    assert user_service.authenticate(db_conn, username="admin", password="different-pw") is None


def test_seed_admin_rejects_weak_password(db_conn) -> None:
    with pytest.raises(WeakPasswordError):
        user_service.seed_admin(db_conn, username="admin", password="short", cost=4)
