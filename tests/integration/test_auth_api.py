"""M2.1/M2.2: login, refresh rotation with family revocation, logout, /me, user creation."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from khataiq.models import AuditLog, RefreshToken
from tests.integration.conftest import PASSWORD, People, login

REFRESH = "khataiq_refresh"


def use_cookie(client, token: str) -> None:
    """Replace whatever refresh cookie the client holds with token. (The cookie jar stores a
    dotless host like 'testserver' as 'testserver.local'.)"""
    client.cookies.clear()
    client.cookies.set(REFRESH, token, domain="testserver.local", path="/v1/auth")


def test_login_returns_token_and_sets_hardened_cookie(api, people: People):
    r = api.post("/v1/auth/login", json={"email": people.officer, "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 900
    cookie = r.headers["set-cookie"].lower()
    for attribute in ("httponly", "secure", "samesite=strict", "path=/v1/auth"):
        assert attribute in cookie


def test_wrong_password_and_unknown_email_look_the_same(api, people: People):
    wrong = api.post("/v1/auth/login", json={"email": people.officer, "password": "nope"})
    unknown = api.post("/v1/auth/login", json={"email": "ghost@a.example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert wrong.headers["content-type"] == "application/problem+json"


def test_me(api, people: People):
    r = api.get("/v1/me", headers=login(api, people.admin))
    assert r.status_code == 200
    assert r.json()["email"] == people.admin and r.json()["role"] == "admin"


def test_missing_or_bad_token_is_401_problem(api, people: People):
    r = api.get("/v1/me")
    assert r.status_code == 401
    body = r.json()
    assert set(body) >= {"type", "title", "status", "detail", "instance", "request_id"}
    assert body["request_id"] == r.headers["x-request-id"]
    assert api.get("/v1/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_refresh_rotates_the_cookie(api, people: People):
    login(api, people.owner1)
    first = api.cookies.get(REFRESH)
    r = api.post("/v1/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]
    assert api.cookies.get(REFRESH) != first


def test_reusing_a_rotated_token_revokes_the_whole_family(api, people: People,
                                                          owner_session: Session):
    login(api, people.owner1)
    stolen = api.cookies.get(REFRESH)
    assert api.post("/v1/auth/refresh").status_code == 200  # legitimate rotation
    newest = api.cookies.get(REFRESH)

    use_cookie(api, stolen)
    replay = api.post("/v1/auth/refresh")
    assert replay.status_code == 401 and "already used" in replay.json()["detail"]

    use_cookie(api, newest)
    assert api.post("/v1/auth/refresh").status_code == 401  # family is dead too
    tokens = owner_session.scalars(select(RefreshToken)).all()
    assert tokens and all(t.revoked_at is not None for t in tokens)
    actions = owner_session.scalars(select(AuditLog.action)).all()
    assert "auth.refresh_family_revoked.reuse" in actions


def test_logout_revokes_family(api, people: People):
    headers = login(api, people.owner1)
    cookie = api.cookies.get(REFRESH)
    assert api.post("/v1/auth/logout", headers=headers).status_code == 204
    use_cookie(api, cookie)
    r = api.post("/v1/auth/refresh")
    assert r.status_code == 401 and "already used" in r.json()["detail"]


def test_refresh_without_cookie_is_401(api, people: People):
    r = api.post("/v1/auth/refresh")
    assert r.status_code == 401 and r.json()["detail"] == "missing refresh cookie"


def test_only_admin_creates_users(api, people: People):
    new = {"email": "New.Officer@a.example.com", "password": "long enough password",
           "role": "officer"}
    assert api.post("/v1/users", json=new, headers=login(api, people.officer)).status_code == 403
    r = api.post("/v1/users", json=new, headers=login(api, people.admin))
    assert r.status_code == 201 and r.json()["email"] == "new.officer@a.example.com"
    assert api.post("/v1/users", json=new, headers=login(api, people.admin)).status_code == 409
    login(api, "new.officer@a.example.com", "long enough password")


def test_validation_errors_do_not_echo_input(api, people: People):
    r = api.post("/v1/users", headers=login(api, people.admin),
                 json={"email": "x@a.example.com", "password": "short", "role": "admin"})
    assert r.status_code == 422
    assert "short" not in r.text
