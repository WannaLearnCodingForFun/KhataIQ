"""LOAN_DISBURSAL v1: a credit that is borrowed money, not business income.

A credit whose narration contains LOAN, DISB or NBFC *and* whose current label is loan_in.
Both are required: the keyword alone also matches EMI debits and loan-account names, and the
label alone may come from a model. Level inferred: one leg, named evidence.
"""

from __future__ import annotations

import re

from khataiq.evidence.types import LedgerTxn, Link, sorted_links
from khataiq.models.enums import EvidenceKind, EvidenceLevel

RULE_ID, RULE_VERSION = "LOAN_DISBURSAL", 1
KEYWORDS = re.compile(r"LOAN|DISB|NBFC")


def loan_links(txns: list[LedgerTxn]) -> list[Link]:
    return sorted_links([
        Link(EvidenceKind.LOAN_DISBURSAL, t.id, None, EvidenceLevel.INFERRED, RULE_ID,
             RULE_VERSION, {"label": t.label})
        for t in txns
        if t.is_credit and t.label == "loan_in" and KEYWORDS.search(t.narration_norm)
    ])
