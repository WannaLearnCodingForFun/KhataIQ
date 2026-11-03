"""Statement uploads and their pipeline status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile
from sqlalchemy.orm import Session

from khataiq.api.deps import Ctx, ctx, owner_ctx, rate_limit
from khataiq.api.pagination import Page, build_page, clamp_limit, decode_cursor
from khataiq.api.schemas.uploads import ReconOut, StageOut, UploadOut
from khataiq.models import Upload
from khataiq.ratelimit import general_bucket, uploads_bucket
from khataiq.services import access, uploads

router = APIRouter(prefix="/v1", tags=["uploads"],
                   dependencies=[Depends(rate_limit(general_bucket()))])


def upload_out(s: Session, upload: Upload) -> UploadOut:
    recon = None
    if upload.recon_reason is not None:
        recon = ReconOut(reason=upload.recon_reason, break_line=upload.recon_break_line,
                         expected_paise=upload.recon_expected_paise,
                         actual_paise=upload.recon_actual_paise)
    return UploadOut(
        id=upload.id, account_id=upload.account_id, status=upload.status.value,
        content_type=upload.content_type, size_bytes=upload.size_bytes, sha256=upload.sha256,
        parser_version=upload.parser_version, period_start=upload.period_start,
        period_end=upload.period_end, opening_paise=upload.opening_paise,
        closing_paise=upload.closing_paise, error=upload.error, created_at=upload.created_at,
        stages=[StageOut(**vars(v)) for v in uploads.stage_views(s, upload.id)], recon=recon,
    )


@router.post("/accounts/{account_id}/uploads", response_model=UploadOut, status_code=201,
             dependencies=[Depends(rate_limit(uploads_bucket()))],
             responses={200: {"description": "This file was already uploaded (or the request "
                                             "is a replay); the existing upload is returned"}})
def create_upload(
    account_id: int,
    response: Response,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    c: Ctx = Depends(owner_ctx),
) -> UploadOut:
    key = uploads.parse_idempotency_key(idempotency_key)
    data = uploads.read_limited(file.file, uploads.max_upload_bytes())
    result = uploads.create_upload(c.user, account_id, key, data)
    response.status_code = result.status_code
    with c.session() as s:
        return upload_out(s, s.get(Upload, result.upload.id) or result.upload)


@router.get("/uploads/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: int, c: Ctx = Depends(ctx)) -> UploadOut:
    with c.session() as s:
        return upload_out(s, access.get_upload(s, c.user, upload_id))


@router.get("/businesses/{business_id}/uploads", response_model=Page[UploadOut])
def list_uploads(business_id: int, c: Ctx = Depends(ctx), cursor: str | None = None,
                 limit: int | None = Query(default=None)) -> Page[UploadOut]:
    size = clamp_limit(limit)
    with c.session() as s:
        rows = uploads.list_uploads(s, c.user, business_id, decode_cursor(cursor), size)
        items, next_cursor = build_page(rows, size, key=lambda u: u.id)
        return Page[UploadOut](items=[upload_out(s, u) for u in items], next_cursor=next_cursor)
