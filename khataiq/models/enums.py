"""Enumerations stored as native Postgres ENUM types."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class UserRole(StrEnum):
    OWNER = "owner"
    OFFICER = "officer"
    ADMIN = "admin"


class UploadStatus(StrEnum):
    RECEIVED = "received"
    PARSING = "parsing"
    PARSED = "parsed"
    RECONCILED = "reconciled"
    NEEDS_REVIEW = "needs_review"
    PROCESSED = "processed"
    FAILED = "failed"


class PipelineStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


class TxnDirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class LabelMethod(StrEnum):
    RULE = "rule"
    MODEL = "model"
    HUMAN = "human"


class TxnLabel(StrEnum):
    SALES = "sales"
    SUPPLIER_PAYMENT = "supplier_payment"
    RENT = "rent"
    SALARY_PAID = "salary_paid"
    EMI = "emi"
    LOAN_IN = "loan_in"
    UTILITIES = "utilities"
    CASH_DEPOSIT = "cash_deposit"
    CASH_WITHDRAWAL = "cash_withdrawal"
    TAX = "tax"
    BANK_CHARGES = "bank_charges"
    PERSONAL = "personal"
    TRANSFER = "transfer"
    REFUND = "refund"
    OTHER = "other"


class EvidenceKind(StrEnum):
    SELF_TRANSFER = "self_transfer"
    REVERSAL = "reversal"
    DUPLICATE = "duplicate"
    LOAN_DISBURSAL = "loan_disbursal"


class EvidenceLevel(StrEnum):
    VERIFIED = "verified"
    INFERRED = "inferred"
    UNRESOLVED = "unresolved"


class FlagKind(StrEnum):
    CYCLE = "cycle"
    UNRESOLVED_TRANSFER = "unresolved_transfer"
    NEEDS_REVIEW_UPLOAD = "needs_review_upload"


class FlagStatus(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class AssessmentStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """A Postgres ENUM that stores the members' values ('owner'), not their names ('OWNER')."""
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )
