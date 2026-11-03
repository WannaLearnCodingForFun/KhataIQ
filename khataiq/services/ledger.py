"""Reading the ledger: transactions with labels and evidence, the money-flow graph, and human
relabelling."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import exists, select, tuple_
from sqlalchemy.orm import Session

from khataiq import audit
from khataiq.errors import BadRequest, NotFound
from khataiq.evidence import cycles
from khataiq.evidence.types import Link
from khataiq.models import Account, Transaction, TxnLabelRow, Upload, UploadRow
from khataiq.models.enums import EvidenceKind, EvidenceLevel, LabelMethod, TxnLabel
from khataiq.principal import Principal
from khataiq.services import access
from khataiq.services.evidence import (
    LEDGER_STATUSES,
    current_labels,
    current_links,
    explained_by_reversals,
    load_ledger,
)

_LEVEL_RANK = {EvidenceLevel.VERIFIED: 0, EvidenceLevel.INFERRED: 1, EvidenceLevel.UNRESOLVED: 2}


@dataclass(frozen=True)
class TxnEvidence:
    level: EvidenceLevel
    kinds: tuple[EvidenceKind, ...]


@dataclass(frozen=True)
class TxnFilters:
    since: date | None = None
    until: date | None = None
    account_id: int | None = None
    label: TxnLabel | None = None
    evidence_level: str | None = None  # verified | inferred | unresolved | none
    direction: str | None = None
    min_paise: int | None = None


def evidence_by_txn(s: Session, business_id: int) -> dict[int, TxnEvidence]:
    """Each transaction's strongest evidence level in the current run (verified beats inferred
    beats unresolved), and every kind of link it's part of."""
    _, links = current_links(s, business_id)
    levels: dict[int, EvidenceLevel] = {}
    kinds: dict[int, set[EvidenceKind]] = {}
    for link in links:
        for txn_id in (link.txn_a, link.txn_b):
            if txn_id is None:
                continue
            kinds.setdefault(txn_id, set()).add(link.kind)
            if txn_id not in levels or _LEVEL_RANK[link.level] < _LEVEL_RANK[levels[txn_id]]:
                levels[txn_id] = link.level
    return {i: TxnEvidence(levels[i], tuple(sorted(kinds[i], key=lambda k: k.value)))
            for i in levels}


def _encode(row_date: date, row_id: int) -> str:
    raw = json.dumps({"d": row_date.isoformat(), "id": row_id})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode(cursor: str | None) -> tuple[date, int] | None:
    if not cursor:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return date.fromisoformat(data["d"]), int(data["id"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise BadRequest("invalid cursor") from exc


@dataclass(frozen=True)
class TxnRow:
    txn: Transaction
    label: str | None
    label_method: str | None
    evidence: TxnEvidence | None


def list_transactions(s: Session, p: Principal, business_id: int, f: TxnFilters,
                      cursor: str | None, limit: int) -> tuple[list[TxnRow], str | None]:
    """Ledger rows (backed by a reconciled statement), newest first, keyset-paginated on
    (txn_date, id) so pages stay stable while new rows arrive."""
    access.get_business(s, p, business_id)
    account_ids = list(s.scalars(select(Account.id).where(Account.business_id == business_id)))
    evidence = evidence_by_txn(s, business_id)
    query = (
        select(Transaction, current_labels.c.label, current_labels.c.method)
        .outerjoin(current_labels, current_labels.c.txn_id == Transaction.id)
        .where(Transaction.account_id.in_(account_ids),
               exists(select(UploadRow.txn_id).join(Upload, Upload.id == UploadRow.upload_id)
                      .where(UploadRow.txn_id == Transaction.id,
                             Upload.status.in_(LEDGER_STATUSES))))
        .order_by(Transaction.txn_date.desc(), Transaction.id.desc())
        .limit(limit + 1)
    )
    if f.since:
        query = query.where(Transaction.txn_date >= f.since)
    if f.until:
        query = query.where(Transaction.txn_date <= f.until)
    if f.account_id:
        query = query.where(Transaction.account_id == f.account_id)
    if f.direction:
        query = query.where(Transaction.direction == f.direction)
    if f.min_paise:
        query = query.where(Transaction.amount_paise >= f.min_paise)
    if f.label:
        query = query.where(current_labels.c.label == f.label)
    if f.evidence_level == "none":
        query = query.where(Transaction.id.not_in(list(evidence) or [0]))
    elif f.evidence_level:
        wanted = EvidenceLevel(f.evidence_level)
        query = query.where(Transaction.id.in_(
            [i for i, e in evidence.items() if e.level == wanted] or [0]))
    after = _decode(cursor)
    if after is not None:
        query = query.where(tuple_(Transaction.txn_date, Transaction.id) < tuple_(*after))

    rows = s.execute(query).all()
    items = [TxnRow(t, label.value if label else None, method.value if method else None,
                    evidence.get(t.id)) for t, label, method in rows[:limit]]
    next_cursor = (_encode(items[-1].txn.txn_date, items[-1].txn.id)
                   if len(rows) > limit else None)
    return items, next_cursor


def relabel(s: Session, p: Principal, txn_id: int, label: TxnLabel, note: str | None) -> None:
    """Append a human label (labels are never updated in place; human beats rule and model)."""
    txn = s.get(Transaction, txn_id)
    if txn is None:
        raise NotFound(f"transaction {txn_id} not found")
    access.get_account(s, p, txn.account_id)
    s.add(TxnLabelRow(org_id=p.org_id, txn_id=txn.id, label=label, method=LabelMethod.HUMAN,
                      note=note, created_by=p.id))
    audit.record(s, org_id=p.org_id, actor_id=p.id, action="transaction.relabel",
                 entity_type="transaction", entity_id=txn.id,
                 after={"label": label, "note": note})


@dataclass(frozen=True)
class GraphView:
    start: date
    end: date  # exclusive
    nodes: list[tuple[str, str, str]]  # (id, label, kind)
    edges: list[tuple[str, str, int, list[int]]]
    cycles: list[list[str]]


def graph(s: Session, p: Principal, business_id: int, since: date | None,
          until: date | None) -> GraphView:
    """The money-flow graph for a window (default: the ledger's last 30 days)."""
    access.get_business(s, p, business_id)
    txns, accounts = load_ledger(s, business_id)
    if until is None:
        until = max((t.txn_date for t in txns), default=date.today())
    if since is None:
        since = until - timedelta(days=cycles.WINDOW_DAYS - 1)
    if since > until:
        raise BadRequest("from must not be after to")
    end = until + timedelta(days=1)
    _, rows = current_links(s, business_id)
    pairs = [(r.txn_a, r.txn_b) for r in rows
             if r.kind == EvidenceKind.SELF_TRANSFER and r.txn_b is not None]
    explained = explained_by_reversals([
        Link(r.kind, r.txn_a, r.txn_b, r.level, r.rule_id, r.rule_version)
        for r in rows if r.kind == EvidenceKind.REVERSAL])
    edges = cycles.build_graph(txns, pairs, since, end, explained)
    masks = {cycles.account_node(a.id): f"A/c ••{a.mask}" for a in accounts}
    node_ids = sorted({n for edge in edges for n in edge})
    nodes = [(n, masks.get(n, n.split(":", 1)[-1]),
              "account" if n.startswith("ACCT:") else "counterparty") for n in node_ids]
    window = [t for t in txns if since <= t.txn_date < end]
    found = cycles.find_cycles(window, pairs, explained)
    return GraphView(
        since, end, nodes,
        [(u, v, e.total_paise, sorted(e.txn_ids)) for (u, v), e in sorted(edges.items())],
        [list(f.path) for f in found])
