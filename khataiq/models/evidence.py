"""Evidence links between transactions, and flags for officer review."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Sequence,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from khataiq.db import Base
from khataiq.models.base import created_at_column, id_column, org_id_column
from khataiq.models.enums import EvidenceKind, EvidenceLevel, FlagKind, FlagStatus, pg_enum

EVIDENCE_RUN_SEQ = Sequence("evidence_run_id_seq", metadata=Base.metadata)


class EvidenceRun(Base):
    """One run of the evidence engine for one business. The business's latest run is current,
    even when it found nothing (which is why runs need their own row)."""

    __tablename__ = "evidence_runs"

    id: Mapped[int] = mapped_column(BigInteger, EVIDENCE_RUN_SEQ,
                                    server_default=EVIDENCE_RUN_SEQ.next_value(),
                                    primary_key=True)
    org_id: Mapped[int] = org_id_column()
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    link_count: Mapped[int] = mapped_column(Integer)
    txn_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_evidence_runs_business", "business_id", "id"),)


class EvidenceLink(Base):
    __tablename__ = "evidence_links"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    run_id: Mapped[int] = mapped_column(ForeignKey("evidence_runs.id"))
    kind: Mapped[EvidenceKind] = mapped_column(pg_enum(EvidenceKind, "evidence_kind"))
    txn_a: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    txn_b: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    level: Mapped[EvidenceLevel] = mapped_column(pg_enum(EvidenceLevel, "evidence_level"))
    rule_id: Mapped[str]
    rule_version: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_evidence_links_business_run", "business_id", "run_id"),)


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    kind: Mapped[FlagKind] = mapped_column(pg_enum(FlagKind, "flag_kind"))
    status: Mapped[FlagStatus] = mapped_column(
        pg_enum(FlagStatus, "flag_status"), server_default=FlagStatus.OPEN.value
    )
    summary: Mapped[str]
    total_paise: Mapped[int]
    rule_id: Mapped[str]
    rule_version: Mapped[int] = mapped_column(Integer)
    # rule_id:rule_version:sorted txn ids (or the upload id) — a flag's identity, for dedupe
    dedupe_key: Mapped[str]
    details: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None]
    resolution_note: Mapped[str | None]
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("business_id", "dedupe_key"),
        Index("ix_flags_open", "org_id", "status", postgresql_where=text("status = 'open'")),
    )


class FlagEvidence(Base):
    __tablename__ = "flag_evidence"

    flag_id: Mapped[int] = mapped_column(ForeignKey("flags.id", ondelete="CASCADE"))
    txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    org_id: Mapped[int] = org_id_column()

    __table_args__ = (PrimaryKeyConstraint("flag_id", "txn_id"),)
