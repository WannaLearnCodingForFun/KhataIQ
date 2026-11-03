"""Monthly cash-flow metrics. Pure: ledger rows and evidence links in, one row per month out.

Per month (docs/specs/evidence-engine.md, "Net business inflow"):
  gross_inflow          sum of credits
  excluded_verified     credits in verified SELF_TRANSFER or verified REVERSAL links, and
                        credits in LOAN_DISBURSAL links: money that isn't business income
  uncertain             credits in inferred or unresolved links that aren't already excluded
  net_business_inflow   gross_inflow - excluded_verified - uncertain
  outflow               debits, minus the debit legs of verified self-transfers (moving money
                        between your own accounts isn't spending it)
  obligations           debits labelled emi, rent or salary_paid
  closing_balance       sum over accounts of each account's last known balance at month end
  volatility_bp         coefficient of variation of daily net flow, in basis points

Each credit is counted at most once in excluded_verified and at most once in uncertain (sets of
ids, not sums of links), and never in both. For a DUPLICATE link only txn_b, the copy, is
uncertain; txn_a is the row it duplicates.

Everything is integer arithmetic, volatility included (via math.isqrt), so no float ever
touches a money amount.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from math import isqrt

from khataiq.evidence.types import LedgerTxn, Link
from khataiq.models.enums import EvidenceKind, EvidenceLevel

OBLIGATION_LABELS = frozenset({"emi", "rent", "salary_paid"})


@dataclass(frozen=True)
class MonthMetrics:
    month: date  # first day of the month
    gross_inflow_paise: int
    excluded_verified_paise: int
    uncertain_paise: int
    net_business_inflow_paise: int
    outflow_paise: int
    obligations_paise: int
    closing_balance_paise: int | None
    volatility_bp: int


@dataclass(frozen=True)
class Classification:
    excluded_credits: frozenset[int]
    uncertain_credits: frozenset[int]
    internal_debits: frozenset[int]


def classify_by_evidence(txns: list[LedgerTxn], links: list[Link]) -> Classification:
    credits = {t.id for t in txns if t.is_credit}
    debits = {t.id for t in txns if not t.is_credit}
    excluded: set[int] = set()
    uncertain: set[int] = set()
    internal: set[int] = set()
    for link in links:
        if link.kind == EvidenceKind.DUPLICATE:
            involved = {link.txn_b} if link.txn_b is not None else set()
        else:
            involved = {link.txn_a} | ({link.txn_b} if link.txn_b is not None else set())
        if link.kind == EvidenceKind.LOAN_DISBURSAL or (
                link.level == EvidenceLevel.VERIFIED
                and link.kind in (EvidenceKind.SELF_TRANSFER, EvidenceKind.REVERSAL)):
            excluded |= involved & credits
            if link.kind == EvidenceKind.SELF_TRANSFER:
                internal |= involved & debits
        elif link.level in (EvidenceLevel.INFERRED, EvidenceLevel.UNRESOLVED):
            uncertain |= involved & credits
    return Classification(frozenset(excluded), frozenset(uncertain - excluded),
                          frozenset(internal))


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def volatility_bp(daily_net: list[int]) -> int:
    """Coefficient of variation (population stdev / |mean|) in basis points, exactly.

    stdev = sqrt(n*sum(x^2) - S^2) / n and mean = S / n, so CV = sqrt(n*sum(x^2) - S^2) / |S|.
    A month whose daily flows average zero has no meaningful CV; it reports 0.
    """
    n, total = len(daily_net), sum(daily_net)
    if n == 0 or total == 0:
        return 0
    spread = n * sum(x * x for x in daily_net) - total * total
    return isqrt(spread * 10**8) // abs(total)


def monthly_metrics(txns: list[LedgerTxn], links: list[Link]) -> list[MonthMetrics]:
    if not txns:
        return []
    cls = classify_by_evidence(txns, links)
    by_month: dict[date, list[LedgerTxn]] = defaultdict(list)
    for t in txns:
        by_month[month_start(t.txn_date)].append(t)
    first, last = min(t.txn_date for t in txns), max(t.txn_date for t in txns)

    # Last known balance per account, carried forward month to month. Within a day, statement
    # order is the transaction id order.
    ordered = sorted(txns, key=lambda t: (t.txn_date, t.id))
    balances: dict[int, int] = {}
    cursor = 0

    result = []
    month = month_start(first)
    while month <= last:
        rows = by_month.get(month, [])
        following = next_month(month)
        while cursor < len(ordered) and ordered[cursor].txn_date < following:
            balances[ordered[cursor].account_id] = ordered[cursor].balance_after_paise
            cursor += 1

        gross = sum(t.amount_paise for t in rows if t.is_credit)
        excluded = sum(t.amount_paise for t in rows if t.id in cls.excluded_credits)
        uncertain = sum(t.amount_paise for t in rows if t.id in cls.uncertain_credits)
        outflow = sum(t.amount_paise for t in rows
                      if not t.is_credit and t.id not in cls.internal_debits)
        obligations = sum(t.amount_paise for t in rows
                          if not t.is_credit and t.label in OBLIGATION_LABELS)

        daily: dict[date, int] = defaultdict(int)
        for t in rows:
            daily[t.txn_date] += t.amount_paise if t.is_credit else -t.amount_paise
        span_start, span_end = max(month, first), min(following - timedelta(days=1), last)
        days = [span_start + timedelta(days=i) for i in range((span_end - span_start).days + 1)]

        result.append(MonthMetrics(
            month=month,
            gross_inflow_paise=gross,
            excluded_verified_paise=excluded,
            uncertain_paise=uncertain,
            net_business_inflow_paise=gross - excluded - uncertain,
            outflow_paise=outflow,
            obligations_paise=obligations,
            closing_balance_paise=sum(balances.values()) if balances else None,
            volatility_bp=volatility_bp([daily[d] for d in days]),
        ))
        month = following
    return result
