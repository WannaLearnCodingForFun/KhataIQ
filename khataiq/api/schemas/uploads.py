from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class StageOut(BaseModel):
    stage: str
    status: str
    attempts: int
    error: str | None


class ReconOut(BaseModel):
    reason: str
    break_line: int | None
    expected_paise: int | None
    actual_paise: int | None


class UploadOut(BaseModel):
    id: int
    account_id: int
    status: str
    content_type: str
    size_bytes: int
    sha256: str
    parser_version: str | None
    period_start: date | None
    period_end: date | None
    opening_paise: int | None
    closing_paise: int | None
    error: str | None
    created_at: datetime
    stages: list[StageOut]
    recon: ReconOut | None
