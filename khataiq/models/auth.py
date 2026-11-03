"""Refresh tokens. Only a SHA-256 of each token is stored; the token itself lives in the
client's httpOnly cookie. Tokens issued from one login share a family_id, so reuse of a
rotated token can revoke the whole family."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CHAR, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from khataiq.db import Base
from khataiq.models.base import created_at_column, id_column, org_id_column


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    family_id: Mapped[uuid.UUID]
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_refresh_tokens_family", "family_id"),)
