"""M3.2/M3.3: uploads — idempotency, duplicates, limits, sniffing, atomicity, status."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from khataiq.models import Outbox, PipelineRun, Upload
from khataiq.models.enums import PipelineStatus
from khataiq.services import uploads as upload_service
from tests.integration.conftest import People, login

FIXTURES = Path(__file__).parent.parent / "fixtures"
CSV_BYTES = (FIXTURES / "demo_bank" / "statement_oct.csv").read_bytes()
PDF_BYTES = (FIXTURES / "demo_pdf" / "statement_dec.pdf").read_bytes()


@pytest.fixture()
def setup(api, people: People, s3):
    owner = login(api, people.owner1)
    business = api.post("/v1/businesses", json={"name": "Shop", "category": "kirana"},
                        headers=owner).json()
    account = api.post(f"/v1/businesses/{business['id']}/accounts", headers=owner,
                       json={"bank": "demo", "format": "csv",
                             "account_number": "123456789012"}).json()
    return {"owner": owner, "business": business["id"], "account": account["id"]}


def post(api, headers, account_id, data=CSV_BYTES, key=None, name="statement.csv"):
    return api.post(f"/v1/accounts/{account_id}/uploads",
                    headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
                    files={"file": (name, data, "application/octet-stream")})


def counts(s: Session) -> dict[str, int]:
    s.expire_all()
    result = upload_service.count_rows(s)
    result["audit_log"] = s.execute(text("SELECT count(*) FROM audit_log")).scalar_one()
    return result


def test_new_upload_is_201_with_outbox_job_and_stored_file(api, setup, owner_session, s3):
    r = post(api, setup["owner"], setup["account"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "received" and body["stages"] == [] and body["recon"] is None
    upload = owner_session.get(Upload, body["id"])
    assert upload.storage_key == f"org/{upload.org_id}/upload/{upload.id}/{upload.sha256}"
    assert s3.get_object(upload.storage_key) == CSV_BYTES
    job = owner_session.scalars(select(Outbox)).one()
    assert job.topic == "pipeline.start" and job.payload["upload_id"] == upload.id
    assert job.published_at is None


def test_same_file_twice_returns_200_and_adds_no_rows(api, setup, owner_session):
    first = post(api, setup["owner"], setup["account"])
    before = counts(owner_session)
    second = post(api, setup["owner"], setup["account"])  # new key, same bytes
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert counts(owner_session) == before


def test_replayed_key_returns_the_original_response(api, setup, owner_session):
    key = str(uuid.uuid4())
    first = post(api, setup["owner"], setup["account"], key=key)
    before = counts(owner_session)
    again = post(api, setup["owner"], setup["account"], key=key)
    assert (again.status_code, again.json()["id"]) == (201, first.json()["id"])
    assert counts(owner_session) == before


def test_same_key_with_a_different_file_is_409(api, setup):
    key = str(uuid.uuid4())
    assert post(api, setup["owner"], setup["account"], key=key).status_code == 201
    other = CSV_BYTES.replace(b"ZOMATO", b"SWIGGY")
    r = post(api, setup["owner"], setup["account"], data=other, key=key)
    assert r.status_code == 409


@pytest.mark.parametrize("key", [None, "not-a-uuid"])
def test_idempotency_key_is_required_and_must_be_a_uuid(api, setup, key):
    headers = dict(setup["owner"])
    if key:
        headers["Idempotency-Key"] = key
    r = api.post(f"/v1/accounts/{setup['account']}/uploads", headers=headers,
                 files={"file": ("s.csv", CSV_BYTES, "text/csv")})
    assert r.status_code == 400


def test_oversized_file_is_413(api, setup, monkeypatch):
    monkeypatch.setattr(upload_service, "max_upload_bytes", lambda: 100)
    assert post(api, setup["owner"], setup["account"]).status_code == 413


def test_oversized_body_is_rejected_before_parsing(api, setup):
    from khataiq.config import get_settings

    huge = b"a," * (get_settings().max_upload_bytes // 2 + 64 * 1024)
    r = post(api, setup["owner"], setup["account"], data=huge)
    assert r.status_code == 413
    assert r.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize("data", [b"\x89PNG\r\n\x1a\n\x00\x00binary", b"no commas here at all"])
def test_non_statement_files_are_415(api, setup, data):
    assert post(api, setup["owner"], setup["account"], data=data).status_code == 415


def test_pdf_to_a_csv_account_is_415(api, setup):
    r = post(api, setup["owner"], setup["account"], data=PDF_BYTES, name="statement.csv")
    assert r.status_code == 415 and "csv" in r.json()["detail"]


def test_db_failure_after_storage_leaves_no_upload_row(api, setup, owner_session, s3,
                                                       monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(upload_service, "_insert_upload", boom)
    from fastapi.testclient import TestClient

    from khataiq.api.main import create_app
    with TestClient(create_app(), base_url="https://testserver",
                    raise_server_exceptions=False) as client:
        r = post(client, setup["owner"], setup["account"])
    assert r.status_code == 500
    assert owner_session.scalar(select(Upload.id)) is None
    assert owner_session.scalar(select(Outbox.id)) is None
    keys = [o["Key"] for o in s3.client.list_objects_v2(Bucket=s3.bucket).get("Contents", [])]
    assert len(keys) == 1  # the orphan: harmless, swept by a bucket lifecycle rule


def test_only_the_accounts_owner_can_upload(api, setup, people: People):
    assert post(api, login(api, people.officer), setup["account"]).status_code == 403
    assert post(api, login(api, people.owner2), setup["account"]).status_code == 404
    assert post(api, login(api, people.owner_b), setup["account"]).status_code == 404


def test_status_shows_stages_and_reconciliation_break(api, setup, owner_session, people):
    upload_id = post(api, setup["owner"], setup["account"]).json()["id"]
    org_id = owner_session.get(Upload, upload_id).org_id
    for stage, attempt, status, error in [
        ("parse", 1, PipelineStatus.SUCCEEDED, None),
        ("persist", 1, PipelineStatus.FAILED, "deadlock"),
        ("persist", 2, PipelineStatus.SUCCEEDED, None),
        ("reconcile", 1, PipelineStatus.SUCCEEDED, None),
    ]:
        owner_session.add(PipelineRun(org_id=org_id, upload_id=upload_id, stage=stage,
                                      attempt_no=attempt, status=status, error=error))
    owner_session.execute(text(
        "UPDATE uploads SET status = 'needs_review', recon_reason = 'running_balance', "
        "recon_break_line = 7, recon_expected_paise = 100, recon_actual_paise = 90 "
        "WHERE id = :id"), {"id": upload_id})
    owner_session.commit()

    for viewer in (setup["owner"], login(api, people.officer)):
        body = api.get(f"/v1/uploads/{upload_id}", headers=viewer).json()
        assert body["status"] == "needs_review"
        assert [(st["stage"], st["status"], st["attempts"]) for st in body["stages"]] == [
            ("parse", "succeeded", 1), ("persist", "succeeded", 2), ("reconcile", "succeeded", 1)]
        assert body["recon"] == {"reason": "running_balance", "break_line": 7,
                                 "expected_paise": 100, "actual_paise": 90}
    assert api.get(f"/v1/uploads/{upload_id}",
                   headers=login(api, people.owner2)).status_code == 404


def test_list_business_uploads(api, setup):
    post(api, setup["owner"], setup["account"])
    post(api, setup["owner"], setup["account"], data=CSV_BYTES.replace(b"ATM", b"ATW"))
    r = api.get(f"/v1/businesses/{setup['business']}/uploads", headers=setup["owner"])
    assert r.status_code == 200 and len(r.json()["items"]) == 2
