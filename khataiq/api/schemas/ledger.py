from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from khataiq.models.enums import EvidenceKind, EvidenceLevel, FlagKind, FlagStatus


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    upload_id: int
    txn_date: date
    amount_paise: int
    direction: str
    balance_after_paise: int
    narration: str
    channel: str | None
    utr: str | None
    counterparty_key: str | None
    source_line: int
    label: str | None = None
    label_method: str | None = None
    evidence_level: EvidenceLevel | None = None
    evidence_kinds: list[EvidenceKind] = []


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    upload_id: int | None
    kind: FlagKind
    status: FlagStatus
    summary: str
    total_paise: int
    rule_id: str
    rule_version: int
    details: dict[str, Any]
    created_at: datetime
    resolved_by: int | None
    resolved_at: datetime | None
    resolution_note: str | None


class FlagDetailOut(FlagOut):
    evidence: list[TransactionOut]


class FlagResolveIn(BaseModel):
    status: Literal["confirmed", "dismissed"]
    note: str = Field(min_length=3, max_length=2000)


class EvidenceLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: EvidenceKind
    level: EvidenceLevel
    txn_a: int
    txn_b: int | None
    rule_id: str
    rule_version: int
    details: dict[str, Any]


class EvidenceOut(BaseModel):
    run_id: int | None
    links: list[EvidenceLinkOut]
