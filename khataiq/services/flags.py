"""Opening flags for officer review, with dedupe by identity."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from khataiq import audit
from khataiq.models import Flag, FlagEvidence
from khataiq.models.enums import FlagKind


def dedupe_key(rule_id: str, rule_version: int, txn_ids: list[int],
               scope: str | None = None) -> str:
    """A flag's identity: the rule and the sorted transactions it's about (or a scope such as
    an upload id). Re-running a rule on unchanged data produces the same key."""
    subject = scope if scope is not None else ",".join(str(i) for i in sorted(set(txn_ids)))
    return f"{rule_id}:v{rule_version}:{subject}"


def open_flag(s: Session, *, org_id: int, business_id: int, kind: FlagKind, rule_id: str,
              rule_version: int, summary: str, total_paise: int, txn_ids: list[int],
              upload_id: int | None = None, scope: str | None = None,
              details: dict[str, Any] | None = None) -> Flag | None:
    """Create a flag with its evidence rows, unless one with the same identity exists
    (open, confirmed or dismissed: a dismissed flag stays dismissed). Returns the new flag or
    None if it already existed."""
    if not txn_ids:
        raise ValueError("a flag needs at least one evidence transaction")
    key = dedupe_key(rule_id, rule_version, txn_ids, scope)
    if s.scalar(select(Flag.id).where(Flag.business_id == business_id,
                                      Flag.dedupe_key == key)) is not None:
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
