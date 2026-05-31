import re

from flask.testing import FlaskClient


def _csrf_token(client: FlaskClient, path: str) -> str:
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match, f"csrf_token not found at {path}"
    return match.group(1)


def test_health_ok(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_login_page_renders_with_csrf(client) -> None:
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b'name="csrf_token"' in resp.data


def test_unauthenticated_index_redirects_to_login(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_register_then_access_index(client) -> None:
    token = _csrf_token(client, "/auth/register")
    resp = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "password": "password1",
            "confirm": "password1",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data


def test_register_duplicate_shows_error(client) -> None:
    token = _csrf_token(client, "/auth/register")
    client.post(
        "/auth/register",
        data={
            "username": "alice",
            "password": "password1",
            "confirm": "password1",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    token = _csrf_token(client, "/auth/register")
    resp = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "password": "password2",
            "confirm": "password2",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 200
    assert b"Username already taken" in resp.data


def test_login_logout_flow(client) -> None:
    token = _csrf_token(client, "/auth/register")
    client.post(
        "/auth/register",
        data={
            "username": "bob",
            "password": "password1",
            "confirm": "password1",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    logout_token = _csrf_token(client, "/")
    client.post("/auth/logout", data={"csrf_token": logout_token}, follow_redirects=True)
    assert client.get("/").status_code == 302  # logged out

    token = _csrf_token(client, "/auth/login")
    resp = client.post(
        "/auth/login",
        data={"username": "bob", "password": "password1", "csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data


def test_login_wrong_password_shows_error(client) -> None:
    token = _csrf_token(client, "/auth/register")
    client.post(
        "/auth/register",
        data={
            "username": "carol",
            "password": "password1",
            "confirm": "password1",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    token = _csrf_token(client, "/auth/login")
    resp = client.post(
        "/auth/login",
        data={"username": "carol", "password": "wrong-pass", "csrf_token": token},
    )
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


def _register_then_logout(client: FlaskClient, username: str) -> None:
    token = _csrf_token(client, "/auth/register")
    client.post(
        "/auth/register",
        data={
            "username": username,
            "password": "password1",
            "confirm": "password1",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    client.post("/auth/logout", data={"csrf_token": _csrf_token(client, "/")})


def test_login_honors_relative_next(client) -> None:
    _register_then_logout(client, "dave")
    token = _csrf_token(client, "/auth/login")
    resp = client.post(
        "/auth/login?next=/health",
        data={"username": "dave", "password": "password1", "csrf_token": token},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/health"


def test_login_blocks_open_redirect(client) -> None:
    _register_then_logout(client, "eve")
    token = _csrf_token(client, "/auth/login")
    resp = client.post(
        "/auth/login?next=//evil.com",
        data={"username": "eve", "password": "password1", "csrf_token": token},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"  # fell back to index
