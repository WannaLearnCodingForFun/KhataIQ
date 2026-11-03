"""Loan-officer assessments: a human decision with a state machine."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from khataiq.db import Base
from khataiq.models.base import created_at_column, id_column, org_id_column
from khataiq.models.enums import AssessmentStatus, pg_enum


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    status: Mapped[AssessmentStatus] = mapped_column(
        pg_enum(AssessmentStatus, "assessment_status"),
        server_default=AssessmentStatus.DRAFT.value,
    )
    metric_run_id: Mapped[int | None] = mapped_column(ForeignKey("metric_runs.id"))
    score: Mapped[int | None] = mapped_column(Integer)
    model_version: Mapped[str | None]
    reasons: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None]
    note: Mapped[str | None]
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
