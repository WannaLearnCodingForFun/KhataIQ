"""DUPLICATE v1: the same line apparently printed in two statements of one account, but with
a different running balance (so the fingerprints differ and both rows were stored).

Two rows of the same account with equal (date, amount, direction, normalized narration),
first stored from different uploads, with different fingerprints -> an unresolved link for a
human to decide. Exact duplicates never get this far: UNIQUE(account_id, fingerprint) drops
them at insert time.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import combinations

from khataiq.evidence.types import LedgerTxn, Link, sorted_links
from khataiq.models.enums import EvidenceKind, EvidenceLevel

RULE_ID, RULE_VERSION = "DUPLICATE", 1


def duplicate_links(txns: list[LedgerTxn]) -> list[Link]:
    groups: dict[tuple[int, date, int, str, str], list[LedgerTxn]] = defaultdict(list)
    for t in txns:
        groups[(t.account_id, t.txn_date, t.amount_paise, t.direction, t.narration_norm)].append(t)
    links = []
    for group in groups.values():
        for a, b in combinations(sorted(group, key=lambda t: t.id), 2):
            if a.upload_id != b.upload_id and a.fingerprint != b.fingerprint:
                links.append(Link(EvidenceKind.DUPLICATE, a.id, b.id, EvidenceLevel.UNRESOLVED,
                                  RULE_ID, RULE_VERSION,
                                  {"uploads": [a.upload_id, b.upload_id]}))
    return sorted_links(links)
