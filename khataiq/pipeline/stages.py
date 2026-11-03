"""The ingestion stages: parse -> persist -> reconcile (classify, evidence and metrics are
registered by their own modules). Every stage is idempotent: running it again on the same
upload leaves the database exactly as it was.

The parsed statement isn't passed between stages (it could be large, and messages should stay
small). Each stage re-reads the stored file and re-parses it; parsers are pure and
deterministic, so every stage sees the same rows.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from khataiq.core.ledger import Txn, fingerprint, normalize_narration, reconcile
from khataiq.models import Account, Transaction, Upload, UploadRow
from khataiq.models.enums import FlagKind, UploadStatus
from khataiq.pipeline.enrich import channel_of, counterparty_key
from khataiq.pipeline.parsers import get_parser
from khataiq.pipeline.parsers.base import ParsedRow, ParsedStatement, ParseError
from khataiq.pipeline.runner import (
    PermanentStageError,
    StageResult,
    register_stage,
    set_status,
)
from khataiq.services.flags import open_flag
from khataiq.storage import get_store

RECON_RULE = ("RECONCILIATION", 1)


def load_statement(s: Session, upload: Upload) -> tuple[Account, ParsedStatement]:
    account = s.get(Account, upload.account_id)
    assert account is not None
    try:
        parser = get_parser(account.bank, account.format)
    except KeyError as exc:
        raise PermanentStageError(str(exc)) from exc
    data = get_store().get_object(upload.storage_key)  # network errors are transient: retried
    try:
        return account, parser.parse(data)
    except ParseError as exc:
        raise PermanentStageError(str(exc)) from exc


def as_txn(account_id: int, row: ParsedRow, txn_id: int = 0) -> Txn:
    return Txn(txn_id, account_id, row.txn_date, row.amount_paise, row.direction,
               row.balance_after_paise, row.narration, row.utr)


def stage_parse(s: Session, upload: Upload) -> StageResult:
    _, statement = load_statement(s, upload)
    upload.parser_version = statement.parser_version
    upload.opening_paise = statement.opening_paise
    upload.closing_paise = statement.closing_paise
    if statement.rows:
        upload.period_start = min(r.txn_date for r in statement.rows)
        upload.period_end = max(r.txn_date for r in statement.rows)
    set_status(s, upload, UploadStatus.PARSED)
    return StageResult.CONTINUE


def stage_persist(s: Session, upload: Upload) -> StageResult:
    """Insert every row; rows already present (same account and fingerprint, e.g. from an
    overlapping earlier statement) are skipped by ON CONFLICT DO NOTHING. Then link every line
    of this statement to its transaction in upload_rows, whoever inserted it."""
    account, statement = load_statement(s, upload)
    values: list[dict[str, object]] = []
    prints: list[str] = []
    for row in statement.rows:
        norm = normalize_narration(row.narration)
        channel = channel_of(norm)
        prints.append(fingerprint(as_txn(account.id, row)))
        values.append({
            "org_id": upload.org_id, "account_id": account.id, "upload_id": upload.id,
            "txn_date": row.txn_date, "amount_paise": row.amount_paise,
            "direction": row.direction, "balance_after_paise": row.balance_after_paise,
            "narration": row.narration, "narration_norm": norm, "channel": channel,
            "utr": row.utr, "counterparty_key": counterparty_key(row.narration, channel),
            "fingerprint": prints[-1], "source_line": row.line_no,
        })
    if not values:
        return StageResult.CONTINUE
    s.execute(insert(Transaction).values(values)
              .on_conflict_do_nothing(index_elements=["account_id", "fingerprint"]))
    ids = dict(s.execute(select(Transaction.fingerprint, Transaction.id).where(
        Transaction.account_id == account.id, Transaction.fingerprint.in_(prints))).all())
    s.execute(insert(UploadRow).values([
        {"upload_id": upload.id, "line_no": row.line_no, "txn_id": ids[fp],
         "org_id": upload.org_id}
        for row, fp in zip(statement.rows, prints, strict=True)
    ]).on_conflict_do_nothing(index_elements=["upload_id", "line_no"]))
    return StageResult.CONTINUE


def stage_reconcile(s: Session, upload: Upload) -> StageResult:
    """The hard gate. Runs core.ledger.reconcile over this statement's rows in order, using
    the persisted transaction ids, so a break points at a real row an officer can open."""
    account, statement = load_statement(s, upload)
    prints = [fingerprint(as_txn(account.id, row)) for row in statement.rows]
    ids = dict(s.execute(select(Transaction.fingerprint, Transaction.id).where(
        Transaction.account_id == account.id, Transaction.fingerprint.in_(prints))).all())
    missing = [fp for fp in prints if fp not in ids]
    if missing:
        raise RuntimeError(f"{len(missing)} parsed rows are not persisted yet")
    txns = [as_txn(account.id, row, ids[fp]) for row, fp in zip(statement.rows, prints,
                                                                 strict=True)]
    result = reconcile(statement.opening_paise, statement.closing_paise, txns)

    upload.recon_reason = result.reason
    upload.recon_expected_paise = result.expected_paise
    upload.recon_actual_paise = result.actual_paise
    upload.recon_break_line = (statement.rows[result.break_index].line_no
                               if result.break_index is not None else None)
    if result.ok:
        set_status(s, upload, UploadStatus.RECONCILED)
        return StageResult.CONTINUE

    set_status(s, upload, UploadStatus.NEEDS_REVIEW)
    evidence_index = result.break_index if result.break_index is not None else len(txns) - 1
    if evidence_index >= 0:
        expected = result.expected_paise or 0
        actual = result.actual_paise or 0
        where = (f"line {upload.recon_break_line}" if upload.recon_break_line is not None
                 else "the closing balance")
        open_flag(
            s, org_id=upload.org_id, business_id=account.business_id,
            kind=FlagKind.NEEDS_REVIEW_UPLOAD, rule_id=RECON_RULE[0],
            rule_version=RECON_RULE[1], upload_id=upload.id, scope=f"upload:{upload.id}",
            summary=f"Upload {upload.id} does not reconcile at {where}: expected "
                    f"{expected} paise, statement shows {actual} paise",
            total_paise=abs(expected - actual), txn_ids=[txns[evidence_index].id],
            details={"reason": result.reason, "break_line": upload.recon_break_line},
        )
    return StageResult.STOP


register_stage("parse", stage_parse, UploadStatus.RECEIVED)
register_stage("persist", stage_persist, UploadStatus.PARSED)
register_stage("reconcile", stage_reconcile, UploadStatus.PARSED)

# Later stages live in their own modules; importing them here registers them in order.
import khataiq.pipeline.stage_classify  # noqa: E402, F401
import khataiq.pipeline.stage_evidence  # noqa: E402, F401
import khataiq.pipeline.stage_metrics  # noqa: E402, F401
