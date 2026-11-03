"""Copilot conversations: what officers asked and what the copilot answered."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from khataiq.db import Base
from khataiq.models.base import created_at_column, id_column, org_id_column


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    conversation_id: Mapped[uuid.UUID]
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str]  # "user" | "assistant"
    content: Mapped[dict[str, Any]]  # {"text": ...} or {"answer": ..., "citations": [...]}
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_copilot_messages_conversation", "conversation_id", "id"),)
