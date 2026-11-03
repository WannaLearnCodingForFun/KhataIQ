"""SQLAlchemy engine, session factory and the declarative base for models."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from khataiq.config import get_settings


class Base(DeclarativeBase):
    """Every ORM model inherits from this; Alembic reads Base.metadata."""


@lru_cache
def get_engine() -> Engine:
    # Created lazily so importing this module never opens a connection.
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    with get_sessionmaker()() as session:
        yield session
