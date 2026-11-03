"""Assessments: an officer's documented decision about a business, as a state machine.

The app never scores businesses (see docs/specs/ml.md); an assessment records a human decision
and snapshots the metric run it was based on, so the numbers behind it can always be shown.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from khataiq import audit
from khataiq.errors import Conflict, NotFound
from khataiq.models import Assessment, AuditLog, Business
from khataiq.models.enums import AssessmentStatus
from khataiq.principal import Principal
from khataiq.services import access, metrics

D, R, A, X = (AssessmentStatus.DRAFT, AssessmentStatus.IN_REVIEW, AssessmentStatus.APPROVED,
              AssessmentStatus.REJECTED)
ALLOWED: frozenset[tuple[AssessmentStatus, AssessmentStatus]] = frozenset(
    {(D, R), (R, D), (R, A), (R, X)})
FINAL = frozenset({A, X})


def next_states(status: AssessmentStatus) -> list[AssessmentStatus]:
    return sorted((to for frm, to in ALLOWED if frm == status), key=lambda s: s.value)


def create(s: Session, p: Principal, business_id: int, note: str | None) -> Assessment:
    business: Business = access.get_business(s, p, business_id)
    run, _ = metrics.latest(s, business.id)
    assessment = Assessment(org_id=p.org_id, business_id=business.id, created_by=p.id,
                            metric_run_id=run.id if run else None, note=note)
    s.add(assessment)
    s.flush()
    audit.record(s, org_id=p.org_id, actor_id=p.id, action="assessment.create",
                 entity_type="assessment", entity_id=assessment.id,
                 after={"status": D, "metric_run_id": assessment.metric_run_id, "note": note})
    return assessment


def get(s: Session, assessment_id: int) -> Assessment:
    assessment = s.get(Assessment, assessment_id)
    if assessment is None:
        raise NotFound(f"assessment {assessment_id} not found")
    return assessment


def list_for_business(s: Session, p: Principal, business_id: int) -> list[Assessment]:
    access.get_business(s, p, business_id)
    return list(s.scalars(select(Assessment).where(Assessment.business_id == business_id)
                          .order_by(Assessment.id.desc())))


def transition(s: Session, p: Principal, assessment_id: int, to: AssessmentStatus,
               note: str | None) -> Assessment:
    """Move an assessment. An illegal move is a 409 and changes nothing, audit included."""
    assessment = s.get(Assessment, assessment_id, with_for_update=True)
    if assessment is None:
        raise NotFound(f"assessment {assessment_id} not found")
    current = assessment.status
    if (current, to) not in ALLOWED:
        allowed = ", ".join(n.value for n in next_states(current)) or "none (final)"
        raise Conflict(f"cannot move an assessment from {current.value} to {to.value}; "
                       f"allowed: {allowed}")
    assessment.status = to
    if note:
        assessment.note = note
    if to in FINAL:
        assessment.decided_at = datetime.now(UTC)
        assessment.reviewer_id = p.id
    s.flush()  # the database trigger checks the move again here
    audit.record(s, org_id=p.org_id, actor_id=p.id, action="assessment.transition",
                 entity_type="assessment", entity_id=assessment.id,
                 before={"status": current}, after={"status": to, "note": note})
    return assessment


def history(s: Session, assessment_id: int) -> list[AuditLog]:
    return list(s.scalars(select(AuditLog).where(
        AuditLog.entity_type == "assessment", AuditLog.entity_id == assessment_id)
        .order_by(AuditLog.id)))
