"""Column helpers shared by every model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Identity, func
from sqlalchemy.orm import Mapped, mapped_column


def id_column() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(), primary_key=True)


def created_at_column() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


def org_id_column() -> Mapped[int]:
    """org_id is denormalised onto every tenant table so the RLS policy is one equality check."""
    return mapped_column(ForeignKey("organizations.id"), index=True)
