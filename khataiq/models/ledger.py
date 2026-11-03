"""Transactions and their (append-only) labels."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from khataiq.db import Base
from khataiq.models.base import created_at_column, id_column, org_id_column
from khataiq.models.enums import LabelMethod, TxnDirection, TxnLabel, pg_enum


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), index=True)
    txn_date: Mapped[date]
    amount_paise: Mapped[int]
    direction: Mapped[TxnDirection] = mapped_column(pg_enum(TxnDirection, "txn_direction"))
    balance_after_paise: Mapped[int]
    narration: Mapped[str]
    narration_norm: Mapped[str]
    channel: Mapped[str | None]
    utr: Mapped[str | None]
    counterparty_key: Mapped[str | None]
    fingerprint: Mapped[str] = mapped_column(CHAR(64))
    source_line: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("account_id", "fingerprint"),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
        Index("ix_transactions_account_date", "account_id", "txn_date"),
        Index("ix_transactions_org_amount_date", "org_id", "amount_paise", "txn_date"),
        Index("ix_transactions_utr", "utr", postgresql_where=text("utr IS NOT NULL")),
    )


class UploadRow(Base):
    """Which statements contain which transactions. A transaction is stored once per account
    (by fingerprint), but overlapping statements both contain it; this table records every
    occurrence, so "is this row backed by a reconciled statement?" has an exact answer."""

    __tablename__ = "upload_rows"

    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    org_id: Mapped[int] = org_id_column()

    __table_args__ = (PrimaryKeyConstraint("upload_id", "line_no"),)


class TxnLabelRow(Base):
    """Append-only: a relabel is a new row. The view current_txn_labels picks the winner
    (human > rule > model, then newest)."""

    __tablename__ = "txn_labels"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    label: Mapped[TxnLabel] = mapped_column(pg_enum(TxnLabel, "txn_label"))
    method: Mapped[LabelMethod] = mapped_column(pg_enum(LabelMethod, "label_method"))
    rule_id: Mapped[str | None]
    model_version: Mapped[str | None]
    confidence: Mapped[float | None]  # model probability, not money
    note: Mapped[str | None]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
