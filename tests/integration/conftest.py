"""Integration-test fixtures: a real Postgres, migrated from scratch once per session.

Set KHATAIQ_TEST_DATABASE_URL to a database owned by the migration role, e.g.
    postgresql+psycopg://khataiq:khataiq@localhost:5432/khataiq_test
If it's unset, every integration test is skipped with that message. CI always sets it.
The app-role URL defaults to the same database as user khataiq_app (password khataiq_app);
override it with KHATAIQ_TEST_APP_DATABASE_URL.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from khataiq.config import get_settings
from khataiq.db import Base, get_engine, get_sessionmaker

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from khataiq.storage import ObjectStore, Store

TEST_DB_URL = os.environ.get("KHATAIQ_TEST_DATABASE_URL")
APP_PASSWORD = "khataiq_app"


def _app_url(owner_url: str) -> str:
    explicit = os.environ.get("KHATAIQ_TEST_APP_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(owner_url).set(username="khataiq_app", password=APP_PASSWORD)
    return url.render_as_string(hide_password=False)


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture(scope="session")
def owner_url() -> str:
    if not TEST_DB_URL:
        pytest.skip("KHATAIQ_TEST_DATABASE_URL is not set; integration tests need Postgres")
    return TEST_DB_URL


@pytest.fixture(scope="session")
def app_url(owner_url: str) -> str:
    return _app_url(owner_url)


@pytest.fixture(scope="session")
def migrated(owner_url: str, app_url: str) -> Iterator[None]:
    """Run every migration down and up again, then point the app's settings at the test DB."""
    env = {
        "KHATAIQ_MIGRATION_DATABASE_URL": owner_url,
        "KHATAIQ_DATABASE_URL": app_url,
        "KHATAIQ_APP_DB_PASSWORD": APP_PASSWORD,
    }
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    _clear_caches()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", owner_url)
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _clear_caches()


@pytest.fixture(scope="session")
def owner_engine(owner_url: str, migrated: None) -> Iterator[Engine]:
    engine = create_engine(owner_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(app_url: str, migrated: None) -> Iterator[Engine]:
    engine = create_engine(app_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    """Empty every table before each integration test (owner role, so RLS doesn't apply)."""
    if "integration" not in request.keywords:
        yield
        return
    engine: Engine = request.getfixturevalue("owner_engine")
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def owner_session(owner_engine: Engine) -> Iterator[Session]:
    """A session as the table owner: bypasses RLS, for arranging test data."""
    with Session(owner_engine) as session:
        yield session


# ------------------------------------------------------------------ API fixtures

TEST_REDIS_URL = os.environ.get("KHATAIQ_TEST_REDIS_URL")
PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session")
def password_hash() -> str:
    from khataiq.security import hash_password

    return hash_password(PASSWORD)  # argon2 is slow on purpose; hash once per session


@pytest.fixture()
def redis_available(monkeypatch: pytest.MonkeyPatch) -> Iterator[bool]:
    """Point the rate limiter at the test Redis (flushed), or at nothing so it fails open."""
    from khataiq.ratelimit import get_limiter

    monkeypatch.setenv("KHATAIQ_REDIS_URL", TEST_REDIS_URL or "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    get_limiter.cache_clear()
    if TEST_REDIS_URL:
        get_limiter().client.flushdb()
    yield TEST_REDIS_URL is not None
    get_settings.cache_clear()
    get_limiter.cache_clear()


@pytest.fixture()
def api(migrated: None, redis_available: bool) -> Iterator[TestClient]:
    from fastapi.testclient import TestClient

    from khataiq.api.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as client:
        yield client


@dataclass
class People:
    """Two orgs. Org A: two owners, an officer, an admin. Org B: one owner."""

    org_a: int
    org_b: int
    owner1: str = "owner1@a.example.com"
    owner2: str = "owner2@a.example.com"
    officer: str = "officer@a.example.com"
    admin: str = "admin@a.example.com"
    owner_b: str = "owner@b.example.com"


@pytest.fixture()
def people(owner_session: Session, password_hash: str) -> People:
    from khataiq.models.enums import UserRole
    from tests.integration import factories as f

    a, b = f.org(owner_session), f.org(owner_session)
    p = People(org_a=a.id, org_b=b.id)
    for email, org_id, role in [
        (p.owner1, a.id, UserRole.OWNER), (p.owner2, a.id, UserRole.OWNER),
        (p.officer, a.id, UserRole.OFFICER), (p.admin, a.id, UserRole.ADMIN),
        (p.owner_b, b.id, UserRole.OWNER),
    ]:
        f.user(owner_session, org_id, role, email=email, password_hash=password_hash)
    owner_session.commit()
    return p


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    """Log in and return the Authorization header for that user."""
    response = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def s3(monkeypatch: pytest.MonkeyPatch) -> Iterator[ObjectStore]:
    """An in-memory S3 (moto) behind khataiq.storage.get_store()."""
    from moto import mock_aws

    from khataiq.storage import get_store

    monkeypatch.setenv("KHATAIQ_S3_ENDPOINT", "")
    get_settings.cache_clear()
    get_store.cache_clear()
    with mock_aws():
        yield get_store()
    get_settings.cache_clear()
    get_store.cache_clear()


@pytest.fixture()
def local_store(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Store]:
    """Object storage in a temp directory (works across processes, unlike moto)."""
    from khataiq.storage import get_store

    monkeypatch.setenv("KHATAIQ_STORAGE_BACKEND", "local")
    monkeypatch.setenv("KHATAIQ_LOCAL_STORAGE_DIR", str(tmp_path / "objects"))
    get_settings.cache_clear()
    get_store.cache_clear()
    yield get_store()
    get_settings.cache_clear()
    get_store.cache_clear()
