"""Inputs and outputs shared by the rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from khataiq.models.enums import EvidenceKind, EvidenceLevel


@dataclass(frozen=True)
class LedgerTxn:
    id: int
    account_id: int
    upload_id: int
    txn_date: date
    amount_paise: int
    direction: str  # "debit" | "credit"
    balance_after_paise: int
    narration_norm: str
    utr: str | None
    counterparty_key: str | None
    fingerprint: str
    label: str | None = None

    @property
    def is_credit(self) -> bool:
        return self.direction == "credit"


@dataclass(frozen=True)
class AccountInfo:
    id: int
    mask: str
    upi_id: str | None


@dataclass(frozen=True)
class Link:
    kind: EvidenceKind
    txn_a: int
    txn_b: int | None
    level: EvidenceLevel
    rule_id: str
    rule_version: int
    details: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def sort_key(self) -> tuple[str, int, int, str]:
        return (self.kind.value, self.txn_a, self.txn_b or 0, self.level.value)


def sorted_links(links: list[Link]) -> list[Link]:
    return sorted(links, key=Link.sort_key)
