"""SQLAlchemy engine, session factory and the declarative base for models."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import BigInteger, DateTime, Engine, MetaData, create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Session, SessionTransaction, sessionmaker

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
    """A session with no tenant set: RLS hides every tenant row from it. Used only for
    auth lookups that go through SECURITY DEFINER functions."""
    with get_sessionmaker()() as session:
        yield session


TENANT_KEY = "org_id"


@event.listens_for(Session, "after_begin")
def _apply_tenant(session: Session, transaction: SessionTransaction, conn: Connection) -> None:
    """Re-apply app.org_id at the start of every transaction a tenant session opens.

    set_config(..., true) is SET LOCAL: it lasts until the transaction ends. Hooking
    after_begin means a commit in the middle of a request can't silently drop the tenant
    and leave later queries seeing nothing (or, worse, failing their WITH CHECK).
    """
    org_id = session.info.get(TENANT_KEY)
    if org_id is not None:
        conn.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})


def bind_tenant(session: Session, org_id: int) -> None:
    """Scope a session to one org. Takes effect from the next transaction it begins."""
    if session.in_transaction():
        raise RuntimeError("bind the tenant before the session starts a transaction")
    session.info[TENANT_KEY] = org_id


@contextmanager
def tenant_session(org_id: int) -> Iterator[Session]:
    """A session whose every query is filtered to org_id by row-level security.

    Commits when the block exits normally, rolls back if it raises.
    """
    with get_sessionmaker()() as session:
        bind_tenant(session, org_id)
        with session.begin():
            yield session
