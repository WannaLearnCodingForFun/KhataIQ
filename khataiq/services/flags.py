"""Opening flags for officer review, with dedupe by identity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from khataiq import audit
from khataiq.errors import Conflict, NotFound, UnprocessableEntity
from khataiq.models import Flag, FlagEvidence, Transaction
from khataiq.models.enums import FlagKind, FlagStatus
from khataiq.principal import Principal


def dedupe_key(rule_id: str, rule_version: int, txn_ids: list[int],
               scope: str | None = None) -> str:
    """A flag's identity: the rule and the sorted transactions it's about (or a scope such as
    an upload id). Re-running a rule on unchanged data produces the same key."""
    subject = scope if scope is not None else ",".join(str(i) for i in sorted(set(txn_ids)))
    return f"{rule_id}:v{rule_version}:{subject}"


def open_flag(s: Session, *, org_id: int, business_id: int, kind: FlagKind, rule_id: str,
              rule_version: int, summary: str, total_paise: int, txn_ids: list[int],
              upload_id: int | None = None, scope: str | None = None,
              identity_ids: list[int] | None = None,
              details: dict[str, Any] | None = None) -> Flag | None:
    """Create a flag with its evidence rows, unless one with the same identity exists
    (open, confirmed or dismissed: a dismissed flag stays dismissed). Returns the new flag or
    None if it already existed. identity_ids, if given, define the identity instead of all
    the evidence rows."""
    if not txn_ids:
        raise ValueError("a flag needs at least one evidence transaction")
    key = dedupe_key(rule_id, rule_version, identity_ids or txn_ids, scope)
    existing = s.scalar(select(Flag).where(Flag.business_id == business_id,
                                           Flag.dedupe_key == key))
    if existing is not None:
        if _was_superseded(existing):
            _reopen(s, existing)
        return None
    flag = Flag(org_id=org_id, business_id=business_id, upload_id=upload_id, kind=kind,
                summary=summary, total_paise=total_paise, rule_id=rule_id,
                rule_version=rule_version, dedupe_key=key, details=details or {})
    s.add(flag)
    s.flush()
    s.add_all(FlagEvidence(flag_id=flag.id, txn_id=t, org_id=org_id) for t in sorted(set(txn_ids)))
    audit.record(s, org_id=org_id, actor_id=None, action="flag.open", entity_type="flag",
                 entity_id=flag.id, after={"kind": kind, "rule_id": rule_id,
                                           "total_paise": total_paise})
    return flag


# ------------------------------------------------------------------ officer review

def list_flags(s: Session, status: FlagStatus | None, kind: FlagKind | None,
               business_id: int | None, after_id: int | None, limit: int) -> list[Flag]:
    query = select(Flag).order_by(Flag.id.desc()).limit(limit + 1)
    if status is not None:
        query = query.where(Flag.status == status)
    if kind is not None:
        query = query.where(Flag.kind == kind)
    if business_id is not None:
        query = query.where(Flag.business_id == business_id)
    if after_id is not None:
        query = query.where(Flag.id < after_id)
    return list(s.scalars(query))


def get_flag(s: Session, flag_id: int) -> Flag:
    flag = s.get(Flag, flag_id)
    if flag is None:
        raise NotFound(f"flag {flag_id} not found")
    return flag


def flag_transactions(s: Session, flag_id: int) -> list[Transaction]:
    return list(s.scalars(
        select(Transaction).join(FlagEvidence, FlagEvidence.txn_id == Transaction.id)
        .where(FlagEvidence.flag_id == flag_id).order_by(Transaction.txn_date, Transaction.id)))


def resolve_flag(s: Session, actor: Principal, flag_id: int, status: FlagStatus,
                 note: str) -> Flag:
    """An officer confirms or dismisses an open flag. A note is required: the decision has to
    be explainable later. Resolved flags stay resolved."""
    flag = s.get(Flag, flag_id, with_for_update=True)
    if flag is None:
        raise NotFound(f"flag {flag_id} not found")
    if status == FlagStatus.OPEN:
        raise UnprocessableEntity("a flag can only be confirmed or dismissed")
    if flag.status != FlagStatus.OPEN:
        raise Conflict(f"flag is already {flag.status.value}")
    if not note.strip():
        raise UnprocessableEntity("a note is required")
    before = {"status": flag.status}
    flag.status = status
    flag.resolved_by = actor.id
    flag.resolved_at = datetime.now(UTC)
    flag.resolution_note = note.strip()
    audit.record(s, org_id=actor.org_id, actor_id=actor.id, action=f"flag.{status.value}",
                 entity_type="flag", entity_id=flag.id, before=before,
                 after={"status": status, "note": flag.resolution_note})
    return flag


SUPERSEDED_PREFIX = "Closed automatically"
SUPERSEDED_NOTE = (SUPERSEDED_PREFIX + ": evidence run {run} no longer finds this, usually "
                   "because more statements arrived and explained the money.")


def _was_superseded(flag: Flag) -> bool:
    """Closed by the system, not decided by an officer."""
    return (flag.status == FlagStatus.DISMISSED and flag.resolved_by is None
            and (flag.resolution_note or "").startswith(SUPERSEDED_PREFIX))


def _reopen(s: Session, flag: Flag) -> None:
    """The data changed again and the finding is back: an officer's dismissal would stand,
    but the system's own closure doesn't."""
    flag.status = FlagStatus.OPEN
    flag.resolved_at = None
    flag.resolution_note = None
    audit.record(s, org_id=flag.org_id, actor_id=None, action="flag.reopened",
                 entity_type="flag", entity_id=flag.id, before={"status": FlagStatus.DISMISSED},
                 after={"status": FlagStatus.OPEN})


def supersede_stale(s: Session, *, org_id: int, business_id: int, kinds: list[FlagKind],
                    current_keys: set[str], run_id: int) -> int:
    """Close open flags of these kinds that the latest evidence run no longer produces.

    Evidence runs after every upload, so a flag can be raised while only one account's
    statement is in and the other leg of a transfer is still missing. Leaving it open would
    ask an officer to review something the data has since explained. Flags an officer already
    confirmed or dismissed are never touched.
    """
    stale = s.scalars(select(Flag).where(Flag.business_id == business_id,
                                         Flag.kind.in_(kinds), Flag.status == FlagStatus.OPEN,
                                         Flag.dedupe_key.not_in(current_keys or {""}))).all()
    for flag in stale:
        flag.status = FlagStatus.DISMISSED
        flag.resolved_at = datetime.now(UTC)
        flag.resolution_note = SUPERSEDED_NOTE.format(run=run_id)
        audit.record(s, org_id=org_id, actor_id=None, action="flag.superseded",
                     entity_type="flag", entity_id=flag.id, before={"status": FlagStatus.OPEN},
                     after={"status": FlagStatus.DISMISSED, "evidence_run_id": run_id})
    return len(stale)
