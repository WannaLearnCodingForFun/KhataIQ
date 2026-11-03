"""SELF_TRANSFER v1: money the owner moved between their own accounts.

verified / unresolved come straight from core.ledger.match_self_transfers (UTR pass, then the
uniqueness pass, then everything ambiguous). inferred covers a transaction in no match whose
narration names another of the business's account masks or one of its registered UPI IDs:
the other leg isn't in the ledger, but the row itself says where the money went.
"""

from __future__ import annotations

import re

from khataiq.core.ledger import Txn, match_self_transfers
from khataiq.evidence.types import AccountInfo, LedgerTxn, Link, sorted_links
from khataiq.models.enums import EvidenceKind, EvidenceLevel

RULE_ID, RULE_VERSION = "SELF_TRANSFER", 1
WINDOW_DAYS = 2


def self_transfer_links(txns: list[LedgerTxn], accounts: list[AccountInfo]) -> list[Link]:
    core = [Txn(t.id, t.account_id, t.txn_date, t.amount_paise, t.direction,  # type: ignore[arg-type]
                t.balance_after_paise, t.narration_norm, t.utr) for t in txns]
    links = [
        Link(EvidenceKind.SELF_TRANSFER, m.debit_id, m.credit_id, EvidenceLevel(m.level),
             RULE_ID, RULE_VERSION, {"window_days": WINDOW_DAYS})
        for m in match_self_transfers(core, WINDOW_DAYS)
    ]
    matched = {i for link in links for i in (link.txn_a, link.txn_b)}
    upi_ids = sorted({a.upi_id.upper() for a in accounts if a.upi_id})
    for t in txns:
        if t.id in matched:
            continue
        evidence = _own_account_evidence(t, accounts, upi_ids)
        if evidence:
            links.append(Link(EvidenceKind.SELF_TRANSFER, t.id, None, EvidenceLevel.INFERRED,
                              RULE_ID, RULE_VERSION, {"evidence": evidence}))
    return sorted_links(links)


def _own_account_evidence(t: LedgerTxn, accounts: list[AccountInfo],
                          upi_ids: list[str]) -> str | None:
    for account in accounts:
        if account.id != t.account_id and re.search(
                rf"(?<!\d){re.escape(account.mask)}(?!\d)", t.narration_norm):
            return f"account_mask:{account.mask}"
    for upi in upi_ids:
        if upi in t.narration_norm:
            return f"upi_id:{upi.lower()}"
    return None
