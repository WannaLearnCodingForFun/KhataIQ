"""SQLAlchemy engine, session factory and the declarative base for models."""

from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import BigInteger, DateTime, Engine, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from khataiq.config import get_settings

# Deterministic constraint names, so migrations can refer to (and drop) them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Every ORM model inherits from this; Alembic reads Base.metadata."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Python type -> column type when a Mapped[...] column doesn't say otherwise.
    # int is BIGINT everywhere, which is what every money column needs.
    type_annotation_map = {
        int: BigInteger,
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


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
