from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from khataiq.models.enums import AssessmentStatus


class AssessmentCreateIn(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class TransitionIn(BaseModel):
    to: AssessmentStatus
    note: str | None = Field(default=None, max_length=4000)


class HistoryEntryOut(BaseModel):
    action: str
    actor_id: int | None
    at: datetime
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    status: AssessmentStatus
    metric_run_id: int | None
    note: str | None
    reviewer_id: int | None
    decided_at: datetime | None
    created_by: int
    created_at: datetime
    allowed_transitions: list[AssessmentStatus] = []
    history: list[HistoryEntryOut] = []
