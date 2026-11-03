from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DeadLetterOut(BaseModel):
    run_id: int
    upload_id: int
    business_id: int
    stage: str
    attempt_no: int
    error: str | None
    finished_at: datetime | None


class RetryOut(BaseModel):
    upload_id: int
    stage: str
    attempt: int


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None
    action: str
    entity_type: str
    entity_id: int | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None
    at: datetime
