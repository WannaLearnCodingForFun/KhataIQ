"""Run the evidence engine for one business and store the result as a new run.

The ledger is every transaction of the business's accounts that appears in at least one
reconciled statement (via upload_rows), with its current label. Rows only seen in a statement
that failed reconciliation never reach evidence or metrics: that is the reconciliation gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import column, exists, select, table
from sqlalchemy.orm import Session

from khataiq.evidence import cycles
from khataiq.evidence.duplicate import duplicate_links
from khataiq.evidence.loan import loan_links
from khataiq.evidence.reversal import reversal_links
from khataiq.evidence.self_transfer import self_transfer_links
from khataiq.evidence.types import AccountInfo, LedgerTxn, Link
from khataiq.models import (
    Account,
    Business,
    EvidenceLink,
    EvidenceRun,
    Transaction,
    Upload,
    UploadRow,
)
from khataiq.models.enums import (
    EvidenceKind,
    EvidenceLevel,
    FlagKind,
    LabelMethod,
    TxnLabel,
    UploadStatus,
    pg_enum,
)
from khataiq.services.flags import open_flag

LEDGER_STATUSES = (UploadStatus.RECONCILED, UploadStatus.PROCESSED)

# The view is read-only and owned by migrations, so it isn't an ORM model (that would make
# Alembic try to create it as a table).
current_labels = table(
    "current_txn_labels",
    column("txn_id"),
    column("label", pg_enum(TxnLabel, "txn_label")),
    column("method", pg_enum(LabelMethod, "label_method")),
)


def load_ledger(s: Session, business_id: int) -> tuple[list[LedgerTxn], list[AccountInfo]]:
    accounts = list(s.scalars(select(Account).where(Account.business_id == business_id)
                              .order_by(Account.id)))
    backed_by_reconciled_statement = exists(
        select(UploadRow.txn_id)
        .join(Upload, Upload.id == UploadRow.upload_id)
        .where(UploadRow.txn_id == Transaction.id, Upload.status.in_(LEDGER_STATUSES)))
    rows = s.execute(
        select(Transaction, current_labels.c.label)
        .outerjoin(current_labels, current_labels.c.txn_id == Transaction.id)
        .where(Transaction.account_id.in_([a.id for a in accounts]),
               backed_by_reconciled_statement)
        .order_by(Transaction.id)
    ).all()
    txns = [LedgerTxn(id=t.id, account_id=t.account_id, upload_id=t.upload_id,
                      txn_date=t.txn_date, amount_paise=t.amount_paise,
                      direction=t.direction.value, balance_after_paise=t.balance_after_paise,
                      narration_norm=t.narration_norm, utr=t.utr,
                      counterparty_key=t.counterparty_key, fingerprint=t.fingerprint,
                      label=label.value if label is not None else None)
            for t, label in rows]
    return txns, [AccountInfo(a.id, a.account_mask, a.upi_id) for a in accounts]


@dataclass(frozen=True)
class EvidenceResult:
    run_id: int
    links: list[Link]
    cycles: list[cycles.CycleFinding]
    flags_opened: int


def run_evidence(s: Session, business_id: int) -> EvidenceResult:
    # One evidence run per business at a time: two uploads finishing together would otherwise
    # race on flag dedupe.
    business = s.get(Business, business_id, with_for_update=True)
    assert business is not None
    txns, accounts = load_ledger(s, business_id)

    transfers = self_transfer_links(txns, accounts)
    links = transfers + reversal_links(txns) + duplicate_links(txns) + loan_links(txns)
    run = EvidenceRun(org_id=business.org_id, business_id=business_id, link_count=len(links),
                      txn_count=len(txns))
    s.add(run)
    s.flush()
    s.add_all(EvidenceLink(org_id=business.org_id, business_id=business_id, run_id=run.id,
                           kind=link.kind, txn_a=link.txn_a, txn_b=link.txn_b, level=link.level,
                           rule_id=link.rule_id, rule_version=link.rule_version,
                           details=link.details)
              for link in links)

    by_id = {t.id: t for t in txns}
    opened = 0
    for group in _unresolved_transfer_groups(transfers):
        amount = max(by_id[i].amount_paise for i in group)
        if open_flag(s, org_id=business.org_id, business_id=business_id,
                     kind=FlagKind.UNRESOLVED_TRANSFER, rule_id="SELF_TRANSFER", rule_version=1,
                     summary=f"{len(group)} transactions of {amount} paise could be transfers "
                             "between the business's own accounts, but they can't be paired "
                             "with certainty", total_paise=amount, txn_ids=sorted(group)):
            opened += 1

    pairs = [(link.txn_a, link.txn_b) for link in transfers if link.txn_b is not None]
    found = cycles.find_cycles(txns, pairs)
    for finding in found:
        if open_flag(s, org_id=business.org_id, business_id=business_id, kind=FlagKind.CYCLE,
                     rule_id=cycles.RULE_ID, rule_version=cycles.RULE_VERSION,
                     summary=cycles.describe(finding), total_paise=finding.out_paise,
                     txn_ids=list(finding.txn_ids),
                     details={"path": list(finding.path),
                              "window": [finding.window_start.isoformat(),
                                         finding.window_end.isoformat()],
                              "back_paise": finding.back_paise}):
            opened += 1
    return EvidenceResult(run.id, links, found, opened)


def _unresolved_transfer_groups(transfers: list[Link]) -> list[set[int]]:
    """Connected groups of transactions joined by unresolved self-transfer links."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for link in transfers:
        if link.level == EvidenceLevel.UNRESOLVED and link.txn_b is not None:
            parent[find(link.txn_a)] = find(link.txn_b)
    groups: dict[int, set[int]] = {}
    for node in list(parent):
        groups.setdefault(find(node), set()).add(node)
    return sorted(groups.values(), key=min)


def current_run_id(s: Session, business_id: int) -> int | None:
    from sqlalchemy import func

    return s.scalar(select(func.max(EvidenceRun.id)).where(EvidenceRun.business_id == business_id))


def current_links(s: Session, business_id: int,
                  kind: EvidenceKind | None = None,
                  level: EvidenceLevel | None = None) -> tuple[int | None, list[EvidenceLink]]:
    run_id = current_run_id(s, business_id)
    if run_id is None:
        return None, []
    query = select(EvidenceLink).where(EvidenceLink.run_id == run_id).order_by(EvidenceLink.id)
    if kind is not None:
        query = query.where(EvidenceLink.kind == kind)
    if level is not None:
        query = query.where(EvidenceLink.level == level)
    return run_id, list(s.scalars(query))
