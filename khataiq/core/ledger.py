"""KhataIQ core ledger logic — YOU implement the functions marked TODO.

Make every test in tests/test_ledger.py pass:  pytest -q

Rules for this file (also in CLAUDE.md):
  * Pure functions only. No database, no I/O, no framework imports.
  * Money is always int paise. A float anywhere here is a bug.
  * Deterministic: same input -> same output, every time.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

Direction = Literal["debit", "credit"]
Level = Literal["verified", "unresolved"]


@dataclass(frozen=True)
class Txn:
    id: int
    account_id: int
    txn_date: date
    amount_paise: int          # always > 0; direction carries the sign
    direction: Direction
    balance_after_paise: int   # running balance printed on the statement
    narration: str
    utr: Optional[str] = None  # bank reference number, when the statement has one


# --------------------------------------------------------------------------
# 1. Fingerprint
# --------------------------------------------------------------------------

def normalize_narration(text: str) -> str:
    """Uppercase, trim, and collapse every run of whitespace to one space.

    Also remove spaces around '/' so 'UPI / ZOMATO' == 'UPI/ZOMATO'.
    Example: '  upi / Zomato   123 ' -> 'UPI/ZOMATO 123'
    """
    collapsed = " ".join(text.split())
    no_slash_spaces = re.sub(r" ?/ ?", "/", collapsed)
    return no_slash_spaces.upper()


def fingerprint(txn: Txn) -> str:
    """SHA-256 hex digest identifying a statement row.

    Hash these fields, joined with '|' in this exact order:
      account_id, txn_date (ISO), amount_paise, direction,
      normalize_narration(narration), balance_after_paise

    Do NOT include txn.id (DB ids differ across uploads of the same row).
    Think: why does including balance_after_paise let two genuine identical
    Rs 500 payments on the same day get different fingerprints?
    """
    # TODO
    raise NotImplementedError


# --------------------------------------------------------------------------
# 2. Reconciliation
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ReconcileResult:
    ok: bool
    reason: Optional[Literal["running_balance", "closing_balance"]] = None
    break_index: Optional[int] = None   # index into txns of the first bad row
    expected_paise: Optional[int] = None
    actual_paise: Optional[int] = None


def reconcile(opening_paise: int, closing_paise: int, txns: list[Txn]) -> ReconcileResult:
    """Check a statement adds up. txns are in statement order.

    1. Walk the rows keeping a running balance that starts at opening_paise.
       credit adds amount, debit subtracts it. After each row, the running
       balance must equal row.balance_after_paise. On the FIRST mismatch return
       ok=False, reason='running_balance', break_index=i,
       expected_paise=<your running balance>, actual_paise=<row's balance>.
    2. After all rows, the running balance must equal closing_paise, else
       ok=False, reason='closing_balance', break_index=None, expected/actual set.
    3. Otherwise ok=True with everything else None.
    An empty statement is valid only if opening == closing.
    """
    # TODO
    raise NotImplementedError


# --------------------------------------------------------------------------
# 3. Self-transfer matching
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Match:
    debit_id: int
    credit_id: int
    level: Level


def match_self_transfers(txns: list[Txn], window_days: int = 2) -> list[Match]:
    """Find money the owner moved between their OWN accounts.

    A candidate pair = (debit d, credit c) where
      d.account_id != c.account_id,
      d.amount_paise == c.amount_paise,
      abs((c.txn_date - d.txn_date).days) <= window_days.

    Pass 1 — UTR: look at candidate pairs where d.utr and c.utr are both
      present and equal. If a UTR value appears in exactly ONE such pair, that
      pair is 'verified'; remove both txns from further passes. (A UTR shared
      by several pairs is bad data — leave those txns for passes 2 and 3.)
    Pass 2 — uniqueness: among what is left, a pair is 'verified' only if d has
      exactly ONE candidate credit AND c has exactly ONE candidate debit.
    Pass 3 — everything else that has at least one candidate is ambiguous:
      emit every remaining candidate pair with level='unresolved'.
      Never guess. A human reviews these.

    Output sorted by (debit_id, credit_id).
    Invariant: a txn appears in at most one 'verified' match.

    Complexity target: O(n log n) typical. Hint: group by amount_paise in a
    dict first, so you never compare a Rs 500 debit with a Rs 7,000 credit.
    """
    # TODO
    raise NotImplementedError
