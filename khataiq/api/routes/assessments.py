"""Assessments and their state transitions (officers only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from khataiq.api.deps import Ctx, officer_ctx, rate_limit
from khataiq.api.schemas.assessments import (
    AssessmentCreateIn,
    AssessmentOut,
    HistoryEntryOut,
    TransitionIn,
)
from khataiq.models import Assessment
from khataiq.ratelimit import general_bucket
from khataiq.services import assessments

router = APIRouter(prefix="/v1", tags=["assessments"],
                   dependencies=[Depends(rate_limit(general_bucket()))])


def assessment_out(s: Session, a: Assessment, with_history: bool = True) -> AssessmentOut:
    out = AssessmentOut.model_validate(a)
    out.allowed_transitions = assessments.next_states(a.status)
    if with_history:
        out.history = [HistoryEntryOut(action=h.action, actor_id=h.actor_id, at=h.at,
                                       before=h.before, after=h.after)
                       for h in assessments.history(s, a.id)]
    return out


@router.post("/businesses/{business_id}/assessments", response_model=AssessmentOut,
             status_code=status.HTTP_201_CREATED)
def create(business_id: int, body: AssessmentCreateIn,
           c: Ctx = Depends(officer_ctx)) -> AssessmentOut:
    with c.session() as s:
        return assessment_out(s, assessments.create(s, c.user, business_id, body.note))


@router.get("/businesses/{business_id}/assessments", response_model=list[AssessmentOut])
def list_for_business(business_id: int, c: Ctx = Depends(officer_ctx)) -> list[AssessmentOut]:
    with c.session() as s:
        return [assessment_out(s, a, with_history=False)
                for a in assessments.list_for_business(s, c.user, business_id)]


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut)
def get(assessment_id: int, c: Ctx = Depends(officer_ctx)) -> AssessmentOut:
    with c.session() as s:
        return assessment_out(s, assessments.get(s, assessment_id))


@router.post("/assessments/{assessment_id}/transitions", response_model=AssessmentOut)
def transition(assessment_id: int, body: TransitionIn,
               c: Ctx = Depends(officer_ctx)) -> AssessmentOut:
    with c.session() as s:
        return assessment_out(
            s, assessments.transition(s, c.user, assessment_id, body.to, body.note))
