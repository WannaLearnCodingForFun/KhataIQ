"""Admin: dead-letter queue and audit log."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status

from khataiq.api.deps import Ctx, admin_ctx, rate_limit
from khataiq.api.pagination import Page, build_page, clamp_limit, decode_cursor
from khataiq.api.schemas.admin import AuditOut, DeadLetterOut, RetryOut
from khataiq.pipeline.dispatch import get_dispatcher
from khataiq.pipeline.runner import Dispatcher
from khataiq.ratelimit import general_bucket
from khataiq.services import admin

router = APIRouter(prefix="/v1/admin", tags=["admin"],
                   dependencies=[Depends(rate_limit(general_bucket()))])


@router.get("/dead-letters", response_model=Page[DeadLetterOut])
def dead_letters(c: Ctx = Depends(admin_ctx), cursor: str | None = None,
                 limit: int | None = Query(default=None)) -> Page[DeadLetterOut]:
    size = clamp_limit(limit)
    with c.session() as s:
        rows = admin.list_dead_letters(s, decode_cursor(cursor), size)
    items, next_cursor = build_page(rows, size, key=lambda d: d.run_id)
    return Page[DeadLetterOut](items=[DeadLetterOut(**vars(d)) for d in items],
                               next_cursor=next_cursor)


@router.post("/dead-letters/{run_id}/retry", response_model=RetryOut,
             status_code=status.HTTP_202_ACCEPTED)
def retry_dead_letter(run_id: int, c: Ctx = Depends(admin_ctx),
                      dispatcher: Dispatcher = Depends(get_dispatcher)) -> RetryOut:
    with c.session() as s:
        job = admin.prepare_retry(s, c.user, run_id)
    dispatcher.dispatch(job)  # after commit: the worker sees the reset upload
    return RetryOut(upload_id=job.upload_id, stage=job.stage, attempt=job.attempt)


@router.get("/audit", response_model=Page[AuditOut])
def audit_log(c: Ctx = Depends(admin_ctx), entity_type: str | None = None,
              entity_id: int | None = None, actor_id: int | None = None,
              since: datetime | None = Query(default=None, alias="from"),
              until: datetime | None = Query(default=None, alias="to"),
              cursor: str | None = None,
              limit: int | None = Query(default=None)) -> Page[AuditOut]:
    size = clamp_limit(limit)
    with c.session() as s:
        rows = admin.search_audit(s, entity_type=entity_type, entity_id=entity_id,
                                  actor_id=actor_id, since=since, until=until,
                                  after_id=decode_cursor(cursor), limit=size)
        items, next_cursor = build_page(rows, size, key=lambda a: a.id)
        return Page[AuditOut](items=[AuditOut.model_validate(a) for a in items],
                              next_cursor=next_cursor)
