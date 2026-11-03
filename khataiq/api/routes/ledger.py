"""The ledger: transactions, monthly metrics and the money-flow graph."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from khataiq.api.deps import Ctx, ctx, officer_ctx, rate_limit
from khataiq.api.pagination import Page, clamp_limit
from khataiq.api.schemas.ledger import (
    GraphEdgeOut,
    GraphNodeOut,
    GraphOut,
    GraphWindowOut,
    MetricsOut,
    MonthOut,
    RelabelIn,
    TransactionOut,
)
from khataiq.models.enums import TxnLabel
from khataiq.ratelimit import general_bucket
from khataiq.services import access, ledger, metrics

router = APIRouter(prefix="/v1", tags=["ledger"],
                   dependencies=[Depends(rate_limit(general_bucket()))])


def transaction_out(row: ledger.TxnRow) -> TransactionOut:
    out = TransactionOut.model_validate(row.txn)
    out.direction = row.txn.direction.value
    out.label, out.label_method = row.label, row.label_method
    if row.evidence is not None:
        out.evidence_level = row.evidence.level
        out.evidence_kinds = list(row.evidence.kinds)
    return out


@router.get("/businesses/{business_id}/transactions", response_model=Page[TransactionOut])
def list_transactions(
    business_id: int,
    c: Ctx = Depends(ctx),
    since: date | None = Query(default=None, alias="from"),
    until: date | None = Query(default=None, alias="to"),
    account_id: int | None = None,
    label: TxnLabel | None = None,
    evidence_level: Literal["verified", "inferred", "unresolved", "none"] | None = None,
    direction: Literal["debit", "credit"] | None = None,
    cursor: str | None = None,
    limit: int | None = Query(default=None),
) -> Page[TransactionOut]:
    filters = ledger.TxnFilters(since, until, account_id, label, evidence_level, direction)
    with c.session() as s:
        rows, next_cursor = ledger.list_transactions(s, c.user, business_id, filters, cursor,
                                                     clamp_limit(limit))
        return Page[TransactionOut](items=[transaction_out(r) for r in rows],
                                    next_cursor=next_cursor)


@router.patch("/transactions/{txn_id}/label", status_code=status.HTTP_204_NO_CONTENT)
def relabel(txn_id: int, body: RelabelIn, c: Ctx = Depends(officer_ctx)) -> None:
    with c.session() as s:
        ledger.relabel(s, c.user, txn_id, body.label, body.note)


@router.get("/businesses/{business_id}/metrics", response_model=MetricsOut)
def get_metrics(business_id: int, c: Ctx = Depends(ctx)) -> MetricsOut:
    with c.session() as s:
        access.get_business(s, c.user, business_id)
        run, months = metrics.latest(s, business_id)
        return MetricsOut(
            run_id=run.id if run else None,
            evidence_run_id=run.evidence_run_id if run else None,
            computed_at=run.created_at if run else None,
            months=[MonthOut.model_validate(m) for m in months])


@router.get("/businesses/{business_id}/graph", response_model=GraphOut)
def get_graph(business_id: int, c: Ctx = Depends(officer_ctx),
              since: date | None = Query(default=None, alias="from"),
              until: date | None = Query(default=None, alias="to")) -> GraphOut:
    with c.session() as s:
        view = ledger.graph(s, c.user, business_id, since, until)
    # 'from' is a Python keyword, so these models alias it; build them from dicts.
    return GraphOut(
        nodes=[GraphNodeOut.model_validate({"id": i, "label": label, "kind": kind})
               for i, label, kind in view.nodes],
        edges=[GraphEdgeOut.model_validate({"from": u, "to": v, "total_paise": t,
                                            "txn_ids": ids})
               for u, v, t, ids in view.edges],
        window=GraphWindowOut.model_validate({"from": view.start,
                                              "to": view.end - timedelta(days=1)}),
        cycles=view.cycles)
