"""KhataIQ core ledger logic.

Make every test in tests/test_ledger.py pass:  pytest -q

Rules for this file:
  * Pure functions only. No database, no I/O, no framework imports.
  * Money is always int paise. A float anywhere here is a bug.
  * Deterministic: same input -> same output, every time.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

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
    utr: str | None = None  # bank reference number, when the statement has one


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
    parts = [
        str(txn.account_id),
        txn.txn_date.isoformat(),
        str(txn.amount_paise),
        txn.direction,
        normalize_narration(txn.narration),
        str(txn.balance_after_paise),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# 2. Reconciliation
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ReconcileResult:
    ok: bool
    reason: Literal["running_balance", "closing_balance"] | None = None
    break_index: int | None = None   # index into txns of the first bad row
    expected_paise: int | None = None
    actual_paise: int | None = None


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
    running = opening_paise
    for i, row in enumerate(txns):
        running += row.amount_paise if row.direction == "credit" else -row.amount_paise
        if running != row.balance_after_paise:
            return ReconcileResult(
                ok=False,
                reason="running_balance",
                break_index=i,
                expected_paise=running,
                actual_paise=row.balance_after_paise,
            )
    if running != closing_paise:
        return ReconcileResult(
            ok=False,
            reason="closing_balance",
            expected_paise=running,
            actual_paise=closing_paise,
        )
    return ReconcileResult(ok=True)


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
    candidates = _candidate_pairs(txns, window_days)
    verified: list[tuple[Txn, Txn]] = []

    # Pass 1: a UTR shared by exactly one candidate pair proves the link.
    pairs_by_utr: dict[str, list[tuple[Txn, Txn]]] = defaultdict(list)
    for d, c in candidates:
        if d.utr and d.utr == c.utr:
            pairs_by_utr[d.utr].append((d, c))
    for pairs in pairs_by_utr.values():
        if len(pairs) == 1:
            verified.append(pairs[0])
    used = {x.id for pair in verified for x in pair}
    remaining = [(d, c) for d, c in candidates if d.id not in used and c.id not in used]

    # Pass 2: a pair is verified when neither side has any other option.
    debit_degree = Counter(d.id for d, _ in remaining)
    credit_degree = Counter(c.id for _, c in remaining)
    unresolved: list[tuple[Txn, Txn]] = []
    for d, c in remaining:
        if debit_degree[d.id] == 1 and credit_degree[c.id] == 1:
            verified.append((d, c))
        else:
            unresolved.append((d, c))

    # Pass 3: everything still ambiguous goes to a human.
    matches = [Match(d.id, c.id, "verified") for d, c in verified]
    matches += [Match(d.id, c.id, "unresolved") for d, c in unresolved]
    return sorted(matches, key=lambda m: (m.debit_id, m.credit_id))


def _candidate_pairs(txns: list[Txn], window_days: int) -> list[tuple[Txn, Txn]]:
    """Every (debit, credit) pair across accounts with equal amount, within the window."""
    debits_by_amount: dict[int, list[Txn]] = defaultdict(list)
    credits_by_amount: dict[int, list[Txn]] = defaultdict(list)
    for x in txns:
        group = debits_by_amount if x.direction == "debit" else credits_by_amount
        group[x.amount_paise].append(x)

    window = timedelta(days=window_days)
    pairs: list[tuple[Txn, Txn]] = []
    for amount, debits in debits_by_amount.items():
        credits = sorted(credits_by_amount.get(amount, []), key=lambda c: c.txn_date)
        credit_dates = [c.txn_date for c in credits]
        for d in debits:
            lo = bisect_left(credit_dates, d.txn_date - window)
            hi = bisect_right(credit_dates, d.txn_date + window)
            pairs.extend((d, c) for c in credits[lo:hi] if c.account_id != d.account_id)
    return pairs
