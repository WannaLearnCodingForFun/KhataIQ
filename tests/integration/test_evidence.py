"""M5: the evidence engine on real ledgers built by the pipeline, flags and the officer API."""

from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from khataiq.db import tenant_session
from khataiq.models import EvidenceRun, Flag, FlagEvidence, Transaction, Upload
from khataiq.models.enums import EvidenceKind, EvidenceLevel, FlagKind, FlagStatus, UploadStatus
from khataiq.pipeline.parsers.demo_csv import render_demo_csv
from khataiq.services.evidence import current_links, load_ledger, run_evidence
from tests.integration.conftest import People, login
from tests.integration.pipeline_helpers import make_shop, run_pipeline, upload

pytestmark = pytest.mark.usefixtures("migrated", "local_store")

D = date(2026, 10, 1)


def day(n: int) -> date:
    return date(2026, 10, n)


def links_of(shop, kind=None):
    with tenant_session(shop.owner.org_id) as s:
        _, rows = current_links(s, shop.business_id, kind)
        return [(r.kind, r.level, r.txn_a, r.txn_b) for r in rows]


def txn_id(s: Session, narration: str) -> int:
    return s.scalar(select(Transaction.id).where(Transaction.narration == narration))


def test_verified_transfer_between_own_accounts(owner_session: Session):
    shop = make_shop(owner_session, masks=("1234", "5678"))
    acct1, acct2 = shop.account_ids
    upload(shop, render_demo_csv(10_000_000, [
        (day(2), "UPI/412300000777/SELF/owner@okaxis", 5_000_000, 0),
        (day(3), "UPI/412300000001/CUSTOMER/c@okaxis", 0, 120_000)]), acct1)
    upload(shop, render_demo_csv(1_000_000, [
        (day(3), "UPI/412300000777/FROM SELF/owner@okaxis", 0, 5_000_000)]), acct2)
    run_pipeline()
    debit = txn_id(owner_session, "UPI/412300000777/SELF/owner@okaxis")
    credit = txn_id(owner_session, "UPI/412300000777/FROM SELF/owner@okaxis")
    assert links_of(shop, EvidenceKind.SELF_TRANSFER) == [
        (EvidenceKind.SELF_TRANSFER, EvidenceLevel.VERIFIED, debit, credit)]
    assert owner_session.scalar(select(func.count()).select_from(Flag)) == 0


def test_ambiguous_transfer_opens_one_flag_with_all_candidates(owner_session: Session):
    shop = make_shop(owner_session, masks=("1234", "5678", "9012"))
    a1, a2, a3 = shop.account_ids
    upload(shop, render_demo_csv(10_000_000, [(day(2), "NEFT DR TRANSFER OUT", 700_000, 0)]), a1)
    upload(shop, render_demo_csv(0, [(day(2), "NEFT CR TRANSFER IN A", 0, 700_000)]), a2)
    upload(shop, render_demo_csv(0, [(day(3), "NEFT CR TRANSFER IN B", 0, 700_000)]), a3)
    run_pipeline()
    levels = {lvl for _, lvl, _, _ in links_of(shop, EvidenceKind.SELF_TRANSFER)}
    assert levels == {EvidenceLevel.UNRESOLVED}
    flag = owner_session.scalars(select(Flag)).one()
    assert flag.kind == FlagKind.UNRESOLVED_TRANSFER and flag.total_paise == 700_000
    evidence = owner_session.scalars(select(FlagEvidence.txn_id).where(
        FlagEvidence.flag_id == flag.id)).all()
    assert len(evidence) == 3


def test_round_trip_through_a_counterparty_opens_a_cycle_flag(owner_session: Session):
    shop = make_shop(owner_session)
    upload(shop, render_demo_csv(10_000_000, [
        (day(2), "NEFT DR-HDFC0001234-RAVI TRADERS-ADV", 2_500_000, 0),
        (day(9), "NEFT CR-HDFC0001234-RAVI TRADERS-ADV RET", 0, 2_400_000),
    ]))
    run_pipeline()
    flag = owner_session.scalars(select(Flag)).one()
    assert flag.kind == FlagKind.CYCLE
    assert flag.details["path"] == [f"ACCT:{shop.account_id}", "name:RAVI TRADERS"]
    assert flag.total_paise == 2_500_000


def test_rerunning_evidence_creates_no_new_flags_and_keeps_dismissals(owner_session: Session):
    shop = make_shop(owner_session)
    upload(shop, render_demo_csv(10_000_000, [
        (day(2), "NEFT DR-HDFC0001234-RAVI TRADERS-ADV", 2_500_000, 0),
        (day(9), "NEFT CR-HDFC0001234-RAVI TRADERS-ADV RET", 0, 2_400_000),
    ]))
    run_pipeline()
    owner_session.execute(text("UPDATE flags SET status = 'dismissed'"))
    owner_session.commit()
    for _ in range(2):
        with tenant_session(shop.owner.org_id) as s:
            result = run_evidence(s, shop.business_id)
            assert result.flags_opened == 0 and len(result.cycles) == 1
    assert owner_session.scalars(select(Flag.status)).all() == [FlagStatus.DISMISSED]
    assert owner_session.scalar(select(func.count()).select_from(EvidenceRun)) == 3
    assert owner_session.execute(text(
        "SELECT count(*) FROM flags f WHERE NOT EXISTS "
        "(SELECT 1 FROM flag_evidence e WHERE e.flag_id = f.id)")).scalar_one() == 0


def test_a_run_that_finds_nothing_is_still_current(owner_session: Session):
    shop = make_shop(owner_session, masks=("1234", "5678"))
    acct1, acct2 = shop.account_ids
    upload(shop, render_demo_csv(10_000_000, [(day(2), "UPI/X/SELF", 50_000, 0)]), acct1)
    upload(shop, render_demo_csv(0, [(day(2), "UPI/X/IN", 0, 50_000)]), acct2)
    run_pipeline()
    assert len(links_of(shop)) == 1
    owner_session.execute(text("UPDATE uploads SET status = 'needs_review'"))
    owner_session.commit()
    with tenant_session(shop.owner.org_id) as s:
        run_evidence(s, shop.business_id)
    assert links_of(shop) == []  # the newest run is empty, and it is the current one


def test_rows_from_an_unreconciled_statement_stay_out_until_a_good_one_arrives(
        owner_session: Session):
    shop = make_shop(owner_session)
    rows = [(day(d), f"UPI/41230000000{d}/C{d}/c{d}@okaxis", 0, 100_000) for d in range(1, 6)]
    good = render_demo_csv(1_000_000, rows).decode().splitlines()
    bad = list(good)
    bad[-2] = bad[-2].replace("15000.00", "15000.01")  # last row's balance is off by a paisa
    upload(shop, ("\n".join(bad) + "\n").encode())
    run_pipeline()
    with tenant_session(shop.owner.org_id) as s:
        assert load_ledger(s, shop.business_id)[0] == []

    corrected = upload(shop, ("\n".join(good) + "\n").encode())
    run_pipeline()
    assert owner_session.get(Upload, corrected).status == UploadStatus.PROCESSED
    with tenant_session(shop.owner.org_id) as s:
        ledger, _ = load_ledger(s, shop.business_id)
    # Four rows are shared with the bad upload (stored once, under it); all five count now.
    assert len(ledger) == 5
    assert owner_session.scalar(select(func.count()).select_from(Transaction)) == 6


# ------------------------------------------------------------------ officer API (M5.4)

@pytest.fixture()
def flagged(api, people: People, owner_session: Session):
    from khataiq.models import User
    from khataiq.models.enums import UserRole
    from khataiq.principal import Principal
    from tests.integration import factories as f
    from tests.integration.pipeline_helpers import Shop

    owner = owner_session.scalar(select(User).where(User.email == people.owner1))
    business = f.business(owner_session, people.org_a, owner.id)
    account = f.account(owner_session, people.org_a, business.id)
    owner_session.commit()
    shop = Shop(Principal(owner.id, people.org_a, UserRole.OWNER), business.id, account.id)
    upload(shop, render_demo_csv(10_000_000, [
        (day(2), "NEFT DR-HDFC0001234-RAVI TRADERS-ADV", 2_500_000, 0),
        (day(9), "NEFT CR-HDFC0001234-RAVI TRADERS-ADV RET", 0, 2_400_000)]))
    run_pipeline()
    return owner_session.scalar(select(Flag.id))


def test_officer_reviews_and_resolves_a_flag(api, people: People, flagged):
    officer = login(api, people.officer)
    queue = api.get("/v1/flags?status=open", headers=officer).json()["items"]
    assert [f["id"] for f in queue] == [flagged]
    detail = api.get(f"/v1/flags/{flagged}", headers=officer).json()
    assert len(detail["evidence"]) == 2 and detail["kind"] == "cycle"

    no_note = api.patch(f"/v1/flags/{flagged}", json={"status": "dismissed", "note": ""},
                        headers=officer)
    assert no_note.status_code == 422
    r = api.patch(f"/v1/flags/{flagged}", headers=officer,
                  json={"status": "dismissed", "note": "Advance refunded, invoice seen"})
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    again = api.patch(f"/v1/flags/{flagged}", headers=officer,
                      json={"status": "confirmed", "note": "changed my mind"})
    assert again.status_code == 409
    audit = api.get(f"/v1/admin/audit?entity_type=flag&entity_id={flagged}",
                    headers=login(api, people.admin)).json()["items"]
    assert audit[0]["action"] == "flag.dismissed"


def test_owners_and_other_orgs_cannot_see_flags(api, people: People, flagged,
                                                owner_session: Session, password_hash):
    from khataiq.models.enums import UserRole
    from tests.integration import factories as f

    assert api.get("/v1/flags", headers=login(api, people.owner1)).status_code == 403
    f.user(owner_session, people.org_b, UserRole.OFFICER, email="officer@b.example.com",
           password_hash=password_hash)
    owner_session.commit()
    outsider = login(api, "officer@b.example.com")
    assert api.get(f"/v1/flags/{flagged}", headers=outsider).status_code == 404
    assert api.get("/v1/flags", headers=outsider).json()["items"] == []
    r = api.patch(f"/v1/flags/{flagged}", headers=outsider,
                  json={"status": "confirmed", "note": "not mine to judge"})
    assert r.status_code == 404


def test_business_evidence_endpoint(api, people: People, flagged, owner_session: Session):
    business_id = owner_session.scalar(select(Flag.business_id))
    r = api.get(f"/v1/businesses/{business_id}/evidence", headers=login(api, people.officer))
    assert r.status_code == 200 and r.json()["run_id"] is not None


def test_flag_is_superseded_when_a_later_statement_explains_it(owner_session: Session):
    """Account 1's statement alone looks like money out to 'MEENA PILLAI' and back; account
    2's statement shows both legs were transfers between the owner's own accounts."""
    from khataiq.models import AuditLog

    shop = make_shop(owner_session, masks=("1234", "5678"))
    acct1, acct2 = shop.account_ids
    upload(shop, render_demo_csv(10_000_000, [
        (day(2), "NEFT/HDFC0001234/MEENA PILLAI", 2_000_000, 0),
        (day(9), "NEFT/HDFC0001234/MEENA PILLAI", 0, 2_000_000)]), acct1)
    run_pipeline()
    flag = owner_session.scalars(select(Flag)).one()
    assert (flag.kind, flag.status) == (FlagKind.CYCLE, FlagStatus.OPEN)

    upload(shop, render_demo_csv(5_000_000, [
        (day(2), "NEFT/SBIN0004321/MEENA PILLAI", 0, 2_000_000),
        (day(9), "NEFT/SBIN0004321/MEENA PILLAI", 2_000_000, 0)]), acct2)
    run_pipeline()
    owner_session.expire_all()
    flag = owner_session.get(Flag, flag.id)
    assert flag.status == FlagStatus.DISMISSED and flag.resolved_by is None
    assert "no longer finds this" in flag.resolution_note
    assert owner_session.scalar(select(AuditLog.id).where(
        AuditLog.action == "flag.superseded", AuditLog.entity_id == flag.id)) is not None


def test_superseding_never_touches_a_decided_flag(owner_session: Session):
    shop = make_shop(owner_session, masks=("1234", "5678"))
    acct1, acct2 = shop.account_ids
    upload(shop, render_demo_csv(10_000_000, [
        (day(2), "NEFT/HDFC0001234/MEENA PILLAI", 2_000_000, 0),
        (day(9), "NEFT/HDFC0001234/MEENA PILLAI", 0, 2_000_000)]), acct1)
    run_pipeline()
    owner_session.execute(text("UPDATE flags SET status = 'confirmed', resolution_note = 'x'"))
    owner_session.commit()
    upload(shop, render_demo_csv(5_000_000, [
        (day(2), "NEFT/SBIN0004321/MEENA PILLAI", 0, 2_000_000),
        (day(9), "NEFT/SBIN0004321/MEENA PILLAI", 2_000_000, 0)]), acct2)
    run_pipeline()
    owner_session.expire_all()
    assert owner_session.scalars(select(Flag.status)).all() == [FlagStatus.CONFIRMED]


def test_a_superseded_flag_reopens_when_the_finding_returns(owner_session: Session):
    from khataiq.services import flags as flag_service

    shop = make_shop(owner_session)
    upload(shop, render_demo_csv(10_000_000, [
        (day(2), "NEFT DR-HDFC0001234-RAVI TRADERS-ADV", 2_500_000, 0),
        (day(9), "NEFT CR-HDFC0001234-RAVI TRADERS-ADV RET", 0, 2_400_000)]))
    run_pipeline()
    flag_id = owner_session.scalar(select(Flag.id))
    with tenant_session(shop.owner.org_id) as s:  # as if a run had stopped finding it
        flag_service.supersede_stale(s, org_id=shop.owner.org_id, business_id=shop.business_id,
                                     kinds=[FlagKind.CYCLE], current_keys=set(), run_id=0)
    with tenant_session(shop.owner.org_id) as s:
        run_evidence(s, shop.business_id)
    owner_session.expire_all()
    assert owner_session.get(Flag, flag_id).status == FlagStatus.OPEN
