"""REVERSAL v1: a credit that returns money from an earlier debit.

A credit c reverses debit d when: same account, same amount, 0 <= (c.date - d.date) <= 7 days,
the same counterparty_key (or both unknown), and c's narration has a reversal keyword.
  * exactly one candidate debit, which no other reversal credit also claims -> verified
  * several candidates, or a debit claimed by several credits -> unresolved, one link each
  * keyword but no candidate debit in the ledger -> inferred, txn_b = None
The "claimed by several credits" check mirrors SELF_TRANSFER's uniqueness pass, so one debit
can never back two verified exclusions.
Links are (txn_a = the reversing credit, txn_b = the original debit).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from khataiq.evidence.types import LedgerTxn, Link, sorted_links
from khataiq.models.enums import EvidenceKind, EvidenceLevel

RULE_ID, RULE_VERSION = "REVERSAL", 1
WINDOW_DAYS = 7
KEYWORDS = re.compile(r"\b(REV|REVERSAL|RETURN|REFUND|RTN|FAILED)\b")

_Key = tuple[int, int, str | None]


def reversal_links(txns: list[LedgerTxn]) -> list[Link]:
    debits: dict[_Key, list[LedgerTxn]] = defaultdict(list)
    for t in txns:
        if not t.is_credit:
            debits[(t.account_id, t.amount_paise, t.counterparty_key)].append(t)

    candidates: dict[int, list[int]] = {}
    for c in txns:
        if c.is_credit and KEYWORDS.search(c.narration_norm):
            key = (c.account_id, c.amount_paise, c.counterparty_key)
            candidates[c.id] = sorted(
                d.id for d in debits.get(key, [])
                if 0 <= (c.txn_date - d.txn_date).days <= WINDOW_DAYS)
    claims = Counter(d for ds in candidates.values() for d in ds)

    links: list[Link] = []
    for credit_id, debit_ids in candidates.items():
        if not debit_ids:
            links.append(Link(EvidenceKind.REVERSAL, credit_id, None, EvidenceLevel.INFERRED,
                              RULE_ID, RULE_VERSION, {"reason": "keyword, no matching debit"}))
        elif len(debit_ids) == 1 and claims[debit_ids[0]] == 1:
            links.append(Link(EvidenceKind.REVERSAL, credit_id, debit_ids[0],
                              EvidenceLevel.VERIFIED, RULE_ID, RULE_VERSION))
        else:
            links.extend(Link(EvidenceKind.REVERSAL, credit_id, d, EvidenceLevel.UNRESOLVED,
                              RULE_ID, RULE_VERSION, {"candidates": len(debit_ids)})
                         for d in debit_ids)
    return sorted_links(links)
