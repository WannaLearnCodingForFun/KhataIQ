"""Officer review: flags and evidence links."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from khataiq.api.deps import Ctx, officer_ctx, rate_limit
from khataiq.api.pagination import Page, build_page, clamp_limit, decode_cursor
from khataiq.api.schemas.ledger import (
    EvidenceLinkOut,
    EvidenceOut,
    FlagDetailOut,
    FlagOut,
    FlagResolveIn,
    TransactionOut,
)
from khataiq.models.enums import EvidenceKind, EvidenceLevel, FlagKind, FlagStatus
from khataiq.ratelimit import general_bucket
from khataiq.services import access, evidence, flags

router = APIRouter(prefix="/v1", tags=["evidence"],
                   dependencies=[Depends(rate_limit(general_bucket()))])


@router.get("/flags", response_model=Page[FlagOut])
def list_flags(c: Ctx = Depends(officer_ctx), status: FlagStatus | None = None,
               kind: FlagKind | None = None, business_id: int | None = None,
               cursor: str | None = None,
               limit: int | None = Query(default=None)) -> Page[FlagOut]:
    size = clamp_limit(limit)
    with c.session() as s:
        rows = flags.list_flags(s, status, kind, business_id, decode_cursor(cursor), size)
        items, next_cursor = build_page(rows, size, key=lambda f: f.id)
        return Page[FlagOut](items=[FlagOut.model_validate(f) for f in items],
                             next_cursor=next_cursor)


@router.get("/flags/{flag_id}", response_model=FlagDetailOut)
def get_flag(flag_id: int, c: Ctx = Depends(officer_ctx)) -> FlagDetailOut:
    with c.session() as s:
        flag = flags.get_flag(s, flag_id)
        return FlagDetailOut(
            **FlagOut.model_validate(flag).model_dump(),
            evidence=[TransactionOut.model_validate(t)
                      for t in flags.flag_transactions(s, flag.id)])


@router.patch("/flags/{flag_id}", response_model=FlagOut)
def resolve_flag(flag_id: int, body: FlagResolveIn, c: Ctx = Depends(officer_ctx)) -> FlagOut:
    with c.session() as s:
        flag = flags.resolve_flag(s, c.user, flag_id, FlagStatus(body.status), body.note)
        return FlagOut.model_validate(flag)


@router.get("/businesses/{business_id}/evidence", response_model=EvidenceOut)
def business_evidence(business_id: int, c: Ctx = Depends(officer_ctx),
                      kind: EvidenceKind | None = None,
                      level: EvidenceLevel | None = None) -> EvidenceOut:
    with c.session() as s:
        access.get_business(s, c.user, business_id)
        run_id, links = evidence.current_links(s, business_id, kind, level)
        return EvidenceOut(run_id=run_id,
                           links=[EvidenceLinkOut.model_validate(link) for link in links])
