"""M4.4: dead-letter list and retry; audit search."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from khataiq.models import PipelineRun, Upload, User
from khataiq.models.enums import PipelineStatus, UploadStatus, UserRole
from khataiq.pipeline.dispatch import get_dispatcher
from khataiq.pipeline.runner import InlineDispatcher
from tests.integration.conftest import People, login
from tests.integration.pipeline_helpers import Shop, run_pipeline, statement, upload

pytestmark = pytest.mark.usefixtures("local_store")


@pytest.fixture()
def dead_upload(api, people: People, owner_session: Session, monkeypatch, local_store):
    """An upload in org A whose parse stage died after 5 attempts."""
    from datetime import date

    from khataiq.principal import Principal
    from tests.integration import factories as f

    owner = owner_session.scalar(select(User).where(User.email == people.owner1))
    business = f.business(owner_session, people.org_a, owner.id)
    account = f.account(owner_session, people.org_a, business.id)
    owner_session.commit()
    shop = Shop(Principal(owner.id, people.org_a, UserRole.OWNER), business.id, account.id)
    upload_id = upload(shop, statement(date(2026, 10, 1), 3))

    real_get = local_store.get_object
    monkeypatch.setattr(local_store, "get_object",
                        lambda key: (_ for _ in ()).throw(ConnectionError("storage down")))
    run_pipeline()
    monkeypatch.setattr(local_store, "get_object", real_get)
    return upload_id


def test_admin_lists_and_retries_a_dead_stage(api, people: People, dead_upload,
                                              owner_session: Session):
    admin = login(api, people.admin)
    items = api.get("/v1/admin/dead-letters", headers=admin).json()["items"]
    assert [(i["upload_id"], i["stage"], i["attempt_no"]) for i in items] == [
        (dead_upload, "parse", 5)]

    inline = InlineDispatcher()
    api.app.dependency_overrides[get_dispatcher] = lambda: inline
    r = api.post(f"/v1/admin/dead-letters/{items[0]['run_id']}/retry", headers=admin)
    assert r.status_code == 202 and r.json() == {"upload_id": dead_upload, "stage": "parse",
                                                 "attempt": 6}
    inline.drain()
    owner_session.expire_all()
    assert owner_session.get(Upload, dead_upload).status == UploadStatus.PROCESSED
    assert api.get("/v1/admin/dead-letters", headers=admin).json()["items"] == []
    # The old run can't be retried twice.
    again = api.post(f"/v1/admin/dead-letters/{items[0]['run_id']}/retry", headers=admin)
    assert again.status_code == 409


def test_dead_letters_are_admin_only_and_tenant_scoped(api, people: People, dead_upload,
                                                       owner_session: Session, password_hash):
    from tests.integration import factories as f

    assert api.get("/v1/admin/dead-letters",
                   headers=login(api, people.officer)).status_code == 403
    run_id = api.get("/v1/admin/dead-letters",
                     headers=login(api, people.admin)).json()["items"][0]["run_id"]
    f.user(owner_session, people.org_b, UserRole.ADMIN, email="admin@b.example.com",
           password_hash=password_hash)
    owner_session.commit()
    other_admin = login(api, "admin@b.example.com")
    assert api.get("/v1/admin/dead-letters", headers=other_admin).json()["items"] == []
    r = api.post(f"/v1/admin/dead-letters/{run_id}/retry", headers=other_admin)
    assert r.status_code == 404


def test_retry_of_a_non_dead_run_is_409(api, people: People, owner_session: Session,
                                        dead_upload):
    owner_session.add(PipelineRun(org_id=people.org_a, upload_id=dead_upload, stage="persist",
                                  attempt_no=1, status=PipelineStatus.SUCCEEDED))
    owner_session.commit()
    run_id = owner_session.scalar(select(PipelineRun.id).where(PipelineRun.stage == "persist"))
    r = api.post(f"/v1/admin/dead-letters/{run_id}/retry", headers=login(api, people.admin))
    assert r.status_code == 409


def test_audit_search(api, people: People, dead_upload):
    admin = login(api, people.admin)
    r = api.get(f"/v1/admin/audit?entity_type=upload&entity_id={dead_upload}", headers=admin)
    actions = [a["action"] for a in r.json()["items"]]
    assert "upload.create" in actions and "upload.status" in actions
    assert all(a["entity_id"] == dead_upload for a in r.json()["items"])
    assert api.get("/v1/admin/audit", headers=login(api, people.officer)).status_code == 403
