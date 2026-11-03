"""Uploaded statements, request idempotency, the transactional outbox and pipeline runs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from khataiq.db import Base
from khataiq.models.base import created_at_column, id_column, org_id_column
from khataiq.models.enums import PipelineStatus, UploadStatus, pg_enum


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    storage_key: Mapped[str]
    sha256: Mapped[str] = mapped_column(CHAR(64))
    content_type: Mapped[str]
    size_bytes: Mapped[int]
    status: Mapped[UploadStatus] = mapped_column(
        pg_enum(UploadStatus, "upload_status"), server_default=UploadStatus.RECEIVED.value
    )
    parser_version: Mapped[str | None]
    period_start: Mapped[date | None]
    period_end: Mapped[date | None]
    opening_paise: Mapped[int | None]
    closing_paise: Mapped[int | None]
    recon_reason: Mapped[str | None]
    recon_break_line: Mapped[int | None] = mapped_column(Integer)
    recon_expected_paise: Mapped[int | None]
    recon_actual_paise: Mapped[int | None]
    error: Mapped[str | None]
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (UniqueConstraint("account_id", "sha256"),)


class IdempotencyKey(Base):
    """One row per (org, Idempotency-Key). Replaying the same key returns the stored response;
    the same key with a different request body is a 409. Rows older than 24 h are ignored."""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128))
    org_id: Mapped[int] = org_id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    request_hash: Mapped[str] = mapped_column(CHAR(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (PrimaryKeyConstraint("org_id", "key"),)


class Outbox(Base):
    """Jobs written in the same transaction as the row that caused them, published later."""

    __tablename__ = "outbox"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    topic: Mapped[str]
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = created_at_column()
    published_at: Mapped[datetime | None]

    __table_args__ = (
        Index("ix_outbox_unpublished", "id", postgresql_where=text("published_at IS NULL")),
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"))
    stage: Mapped[str]
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[PipelineStatus] = mapped_column(pg_enum(PipelineStatus, "pipeline_status"))
    error: Mapped[str | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("upload_id", "stage", "attempt_no"),
        Index("ix_pipeline_runs_upload_stage", "upload_id", "stage"),
    )
