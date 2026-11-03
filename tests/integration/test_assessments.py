"""M6.3: the assessment state machine, in the service and in the database."""

import itertools

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from khataiq.models import AuditLog, User
from khataiq.models.enums import AssessmentStatus
from khataiq.services.assessments import ALLOWED
from tests.integration import factories as f
from tests.integration.conftest import People, login

STATES = list(AssessmentStatus)
PATH_TO = {  # how to reach each state legally from draft
    AssessmentStatus.DRAFT: [],
    AssessmentStatus.IN_REVIEW: ["in_review"],
    AssessmentStatus.APPROVED: ["in_review", "approved"],
    AssessmentStatus.REJECTED: ["in_review", "rejected"],
}


@pytest.fixture()
def business_id(people: People, owner_session: Session) -> int:
    owner = owner_session.scalar(select(User).where(User.email == people.owner1))
    business = f.business(owner_session, people.org_a, owner.id)
    owner_session.commit()
    return business.id


def new_assessment(api, headers, business_id, state: AssessmentStatus) -> int:
    r = api.post(f"/v1/businesses/{business_id}/assessments", json={}, headers=headers)
    assert r.status_code == 201
    assessment_id = r.json()["id"]
    for step in PATH_TO[state]:
        assert api.post(f"/v1/assessments/{assessment_id}/transitions", json={"to": step},
                        headers=headers).status_code == 200
    return assessment_id


def audit_rows(s: Session) -> int:
    s.expire_all()
    return s.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.entity_type == "assessment"))


@pytest.mark.parametrize("frm, to", [
    (a, b) for a, b in itertools.product(STATES, STATES) if (a, b) not in ALLOWED])
def test_every_illegal_transition_is_409_and_writes_no_audit_row(api, people, business_id,
                                                                 owner_session, frm, to):
    officer = login(api, people.officer)
    assessment_id = new_assessment(api, officer, business_id, frm)
    before = audit_rows(owner_session)
    r = api.post(f"/v1/assessments/{assessment_id}/transitions", json={"to": to.value},
                 headers=officer)
    assert r.status_code == 409
    assert audit_rows(owner_session) == before
    assert api.get(f"/v1/assessments/{assessment_id}",
                   headers=officer).json()["status"] == frm.value


def test_full_lifecycle_with_history(api, people, business_id):
    officer = login(api, people.officer)
    assessment_id = new_assessment(api, officer, business_id, AssessmentStatus.DRAFT)
    for to in ("in_review", "draft", "in_review"):
        api.post(f"/v1/assessments/{assessment_id}/transitions", json={"to": to},
                 headers=officer)
    r = api.post(f"/v1/assessments/{assessment_id}/transitions",
                 json={"to": "approved", "note": "Six months of steady net inflow"},
                 headers=officer)
    body = r.json()
    assert body["status"] == "approved" and body["decided_at"] and body["reviewer_id"]
    assert body["allowed_transitions"] == []
    assert [h["action"] for h in body["history"]] == ["assessment.create"] + [
        "assessment.transition"] * 4


def test_database_trigger_blocks_illegal_moves_from_any_writer(api, people, business_id,
                                                               app_engine: Engine):
    officer = login(api, people.officer)
    assessment_id = new_assessment(api, officer, business_id, AssessmentStatus.APPROVED)
    with pytest.raises(IntegrityError, match="illegal assessment transition"):
        with app_engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.org_id', :o, true)"),
                         {"o": str(people.org_a)})
            conn.execute(text("UPDATE assessments SET status = 'draft' WHERE id = :i"),
                         {"i": assessment_id})


def test_assessments_are_officer_only(api, people, business_id):
    r = api.post(f"/v1/businesses/{business_id}/assessments", json={},
                 headers=login(api, people.owner1))
    assert r.status_code == 403
