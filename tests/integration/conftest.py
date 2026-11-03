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

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from khataiq.config import get_settings
from khataiq.db import Base, get_engine, get_sessionmaker

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
