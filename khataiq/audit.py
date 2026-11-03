"""Append-only audit trail. Callers pass explicit dicts of what changed; never whole rows,
so secrets (password hashes, token hashes) can't end up in the log by accident."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from khataiq.models import AuditLog
from khataiq.request_context import current_request_id


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def record(session: Session, *, org_id: int, actor_id: int | None, action: str,
           entity_type: str, entity_id: int | None, before: dict[str, Any] | None = None,
           after: dict[str, Any] | None = None) -> None:
    session.add(AuditLog(
        org_id=org_id, actor_id=actor_id, action=action, entity_type=entity_type,
        entity_id=entity_id, before=_jsonable(before), after=_jsonable(after),
        request_id=current_request_id(),
    ))
