"""Statement uploads: validation, idempotency, storage, and the transactional outbox.

Order of operations in create_upload, and why:

  1. Short read transaction: is this Idempotency-Key a replay? Is this exact file already
     uploaded for the account? If neither, reserve the next upload id from its sequence.
  2. Write the file to object storage under org/{org}/upload/{id}/{sha256}. This is a slow
     network call, so it happens outside any DB transaction.
  3. One write transaction: the uploads row (with the reserved id), its outbox job and the
     idempotency record. Either all three exist or none do, so an upload can never exist
     without the job that processes it.

If step 3 fails, step 2 has left an object with no row pointing at it. That orphan is harmless
(nothing reads it, and a lifecycle rule can sweep objects older than a day with no row),
whereas the opposite order could leave a row pointing at a file that was never stored.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import BinaryIO

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from khataiq import audit
from khataiq.config import get_settings
from khataiq.db import tenant_session
from khataiq.errors import BadRequest, Conflict, PayloadTooLarge, UnsupportedMediaType
from khataiq.models import IdempotencyKey, Outbox, PipelineRun, Upload
from khataiq.principal import Principal
from khataiq.request_context import current_request_id
from khataiq.services import access
from khataiq.storage import get_store, upload_key

PDF = "application/pdf"
CSV = "text/csv"
FORMAT_CONTENT_TYPE = {"csv": CSV, "pdf_text": PDF}
IDEMPOTENCY_TTL = timedelta(hours=24)
PIPELINE_TOPIC = "pipeline.start"
_CHUNK = 64 * 1024


def read_limited(stream: BinaryIO, max_bytes: int) -> bytes:
    """Read at most max_bytes; one byte more means the file is too large."""
    chunks: list[bytes] = []
    size = 0
    while chunk := stream.read(_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            raise PayloadTooLarge(f"file is larger than {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def sniff_content_type(data: bytes) -> str | None:
    """Decide the type from the bytes, never from the client's filename or Content-Type."""
    if data.startswith(b"%PDF-"):
        return PDF
    head = data[:8192]
    if not head or b"\x00" in head:
        return None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text_head = head.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "," in text_head:
            return CSV
    return None


def parse_idempotency_key(raw: str | None) -> str:
    if not raw:
        raise BadRequest("Idempotency-Key header is required")
    try:
        return str(uuid.UUID(raw))
    except ValueError as exc:
        raise BadRequest("Idempotency-Key must be a UUID") from exc


@dataclass(frozen=True)
class UploadResult:
    upload: Upload
    status_code: int  # 201 created, 200 duplicate or replay of a 200


def create_upload(p: Principal, account_id: int, idempotency_key: str,
                  data: bytes) -> UploadResult:
    if not data:
        raise BadRequest("file is empty")
    sha = hashlib.sha256(data).hexdigest()
    request_hash = hashlib.sha256(f"{account_id}:{sha}".encode()).hexdigest()
    content_type = sniff_content_type(data)
    if content_type is None:
        raise UnsupportedMediaType("only CSV and PDF statements are accepted")

    with tenant_session(p.org_id) as s:
        account = access.get_account(s, p, account_id)
        expected = FORMAT_CONTENT_TYPE.get(account.format)
        if content_type != expected:
            raise UnsupportedMediaType(
                f"this account's statements are {account.format}, but the file is {content_type}")
        earlier = _earlier_result(s, p.org_id, account_id, idempotency_key, request_hash, sha)
        if earlier is not None:
            return earlier
        upload_id: int = s.execute(
            text("SELECT nextval(pg_get_serial_sequence('uploads', 'id'))")).scalar_one()

    key = upload_key(p.org_id, upload_id, sha)
    get_store().put_object(key, data, content_type)

    try:
        with tenant_session(p.org_id) as s:
            upload = _insert_upload(s, p, upload_id, account_id, key, sha, content_type,
                                    len(data), idempotency_key, request_hash)
        return UploadResult(upload, 201)
    except IntegrityError:
        # A concurrent request inserted the same file or used the same key first.
        with tenant_session(p.org_id) as s:
            earlier = _earlier_result(s, p.org_id, account_id, idempotency_key, request_hash,
                                      sha)
        if earlier is None:
            raise
        return earlier


def _earlier_result(s: Session, org_id: int, account_id: int, key: str, request_hash: str,
                    sha: str) -> UploadResult | None:
    """A replayed key returns what it returned the first time; an already-uploaded file
    returns the existing upload with 200. A key reused for a different file is a 409."""
    record = s.get(IdempotencyKey, (org_id, key))
    if record is not None and record.created_at < datetime.now(UTC) - IDEMPOTENCY_TTL:
        s.execute(delete(IdempotencyKey).where(IdempotencyKey.org_id == org_id,
                                               IdempotencyKey.key == key))
        record = None
    if record is not None:
        if record.request_hash != request_hash:
            raise Conflict("this Idempotency-Key was already used for a different request")
        upload = s.get(Upload, int(record.response_body["upload_id"]))
        if upload is not None:
            return UploadResult(upload, record.response_status)
    existing = s.scalar(select(Upload).where(Upload.account_id == account_id,
                                             Upload.sha256 == sha))
    if existing is not None:
        return UploadResult(existing, 200)
    return None


def _insert_upload(s: Session, p: Principal, upload_id: int, account_id: int, key: str,
                   sha: str, content_type: str, size: int, idempotency_key: str,
                   request_hash: str) -> Upload:
    upload = Upload(id=upload_id, org_id=p.org_id, account_id=account_id, storage_key=key,
                    sha256=sha, content_type=content_type, size_bytes=size, created_by=p.id)
    s.add(upload)
    s.flush()
    s.add(Outbox(org_id=p.org_id, topic=PIPELINE_TOPIC,
                 payload={"upload_id": upload_id, "org_id": p.org_id,
                          "request_id": current_request_id()}))
    s.add(IdempotencyKey(key=idempotency_key, org_id=p.org_id, user_id=p.id,
                         request_hash=request_hash, response_status=201,
                         response_body={"upload_id": upload_id}))
    audit.record(s, org_id=p.org_id, actor_id=p.id, action="upload.create",
                 entity_type="upload", entity_id=upload_id,
                 after={"account_id": account_id, "sha256": sha, "size_bytes": size,
                        "content_type": content_type})
    s.flush()
    return upload


# ------------------------------------------------------------------ reading

@dataclass(frozen=True)
class StageView:
    stage: str
    status: str
    attempts: int
    error: str | None


STAGE_ORDER = ["parse", "persist", "reconcile", "classify", "evidence", "metrics"]


def stage_views(s: Session, upload_id: int) -> list[StageView]:
    """One entry per stage: the latest attempt's status and error, and how many attempts."""
    runs = s.scalars(select(PipelineRun).where(PipelineRun.upload_id == upload_id)
                     .order_by(PipelineRun.stage, PipelineRun.attempt_no)).all()
    latest: dict[str, PipelineRun] = {}
    for run in runs:
        latest[run.stage] = run
    order = {name: i for i, name in enumerate(STAGE_ORDER)}
    return [StageView(run.stage, run.status.value, run.attempt_no, run.error)
            for run in sorted(latest.values(), key=lambda r: order.get(r.stage, 99))]


def list_uploads(s: Session, p: Principal, business_id: int, after_id: int | None,
                 limit: int) -> list[Upload]:
    from khataiq.models import Account

    business = access.get_business(s, p, business_id)
    query = (select(Upload).join(Account, Account.id == Upload.account_id)
             .where(Account.business_id == business.id)
             .order_by(Upload.id.desc()).limit(limit + 1))
    if after_id is not None:
        query = query.where(Upload.id < after_id)
    return list(s.scalars(query))


def max_upload_bytes() -> int:
    return get_settings().max_upload_bytes


def count_rows(s: Session) -> dict[str, int]:
    """Row counts of the tables an upload writes to (used by tests to prove 'no new rows')."""
    return {model.__tablename__: s.scalar(select(func.count()).select_from(model)) or 0
            for model in (Upload, Outbox, IdempotencyKey)}
