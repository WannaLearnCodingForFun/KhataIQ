"""Append-only audit log. The app's DB role can INSERT and SELECT, never UPDATE or DELETE."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from khataiq.db import Base
from khataiq.models.base import id_column, org_id_column


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # None = system
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[int | None]
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    request_id: Mapped[str | None]
    at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)
