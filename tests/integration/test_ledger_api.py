"""M6.2: metrics stage, transactions view with filters, relabelling, the graph."""

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from khataiq.models import MetricRun, MonthlyMetric, Transaction, User
from khataiq.models.enums import UserRole
from khataiq.pipeline.parsers.demo_csv import render_demo_csv
from khataiq.principal import Principal
from tests.integration import factories as f
from tests.integration.conftest import People, login
from tests.integration.pipeline_helpers import Shop, run_pipeline, upload

pytestmark = pytest.mark.usefixtures("local_store")


def d(month: int, day: int) -> date:
    return date(2026, month, day)


@pytest.fixture()
def shop(api, people: People, owner_session: Session) -> Shop:
    """Two accounts in org A, owned by owner1, with two months of activity processed."""
    owner = owner_session.scalar(select(User).where(User.email == people.owner1))
    business = f.business(owner_session, people.org_a, owner.id)
    a1 = f.account(owner_session, people.org_a, business.id, mask="1111")
    a2 = f.account(owner_session, people.org_a, business.id, mask="2222")
    owner_session.commit()
    shop = Shop(Principal(owner.id, people.org_a, UserRole.OWNER), business.id, a1.id,
                (a1.id, a2.id))
    upload(shop, render_demo_csv(10_000_000, [
        (d(10, 2), "UPI/412300000001/CUST A/a@okaxis", 0, 500_000),
        (d(10, 3), "UPI/412300000777/TO SAVINGS/own@okaxis", 2_000_000, 0),
        (d(10, 5), "NEFT DR-HDFC0001234-RAVI TRADERS-ADV", 2_500_000, 0),
        (d(10, 12), "NEFT CR-HDFC0001234-RAVI TRADERS-ADV RET", 0, 2_400_000),
        (d(11, 1), "ACH D- BAJAJ FIN EMI", 300_000, 0),
        (d(11, 4), "UPI/412300000002/CUST B/b@okaxis", 0, 800_000),
    ]), a1.id)
    upload(shop, render_demo_csv(0, [
        (d(10, 4), "UPI/412300000777/FROM CURRENT/own@okaxis", 0, 2_000_000),
    ]), a2.id)
    run_pipeline()
    return shop


def test_metrics_stage_runs_after_evidence(api, people, shop, owner_session: Session):
    runs = owner_session.scalar(select(func.count()).select_from(MetricRun))
    assert runs == 2  # one per upload; the latest is current
    r = api.get(f"/v1/businesses/{shop.business_id}/metrics", headers=login(api, people.owner1))
    body = r.json()
    assert r.status_code == 200 and body["evidence_run_id"] is not None
    october, november = body["months"]
    assert october["month"] == "2026-10-01" and november["month"] == "2026-11-01"
    assert october["gross_inflow_paise"] == 500_000 + 2_400_000 + 2_000_000
    # The verified self-transfer credit is excluded; nothing else is uncertain.
    assert october["net_business_inflow_paise"] == 500_000 + 2_400_000
    assert october["outflow_paise"] == 2_500_000
    assert november["net_business_inflow_paise"] == 800_000
    latest = owner_session.scalar(select(func.max(MetricRun.id)))
    assert owner_session.scalar(select(func.count()).select_from(MonthlyMetric).where(
        MonthlyMetric.run_id == latest)) == 2


def test_transactions_view_filters_and_paginates(api, people, shop):
    owner = login(api, people.owner1)
    url = f"/v1/businesses/{shop.business_id}/transactions"
    everything = api.get(url, headers=owner).json()["items"]
    assert len(everything) == 7
    assert [t["txn_date"] for t in everything] == sorted(
        (t["txn_date"] for t in everything), reverse=True)

    verified = api.get(f"{url}?evidence_level=verified", headers=owner).json()["items"]
    assert {t["narration"] for t in verified} == {"UPI/412300000777/TO SAVINGS/own@okaxis",
                                                  "UPI/412300000777/FROM CURRENT/own@okaxis"}
    assert all(t["evidence_kinds"] == ["self_transfer"] for t in verified)
    credits_nov = api.get(f"{url}?direction=credit&from=2026-11-01", headers=owner).json()
    assert [t["amount_paise"] for t in credits_nov["items"]] == [800_000]

    seen, cursor = [], None
    while True:
        page = api.get(url + "?limit=3" + (f"&cursor={cursor}" if cursor else ""),
                       headers=owner).json()
        seen += [t["id"] for t in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [t["id"] for t in everything]


def test_officer_relabels_and_owner_cannot(api, people, shop, owner_session: Session):
    txn = owner_session.scalar(select(Transaction.id).where(
        Transaction.narration == "ACH D- BAJAJ FIN EMI"))
    body = {"label": "emi", "note": "Bajaj Finance loan"}
    assert api.patch(f"/v1/transactions/{txn}/label", json=body,
                     headers=login(api, people.owner1)).status_code == 403
    assert api.patch(f"/v1/transactions/{txn}/label", json=body,
                     headers=login(api, people.officer)).status_code == 204
    rows = api.get(f"/v1/businesses/{shop.business_id}/transactions?label=emi",
                   headers=login(api, people.officer)).json()["items"]
    assert [(r["id"], r["label"], r["label_method"]) for r in rows] == [(txn, "emi", "human")]


def test_graph_shows_flows_and_highlights_the_cycle(api, people, shop):
    officer = login(api, people.officer)
    r = api.get(f"/v1/businesses/{shop.business_id}/graph?from=2026-10-01&to=2026-10-30",
                headers=officer)
    body = r.json()
    assert body["window"] == {"from": "2026-10-01", "to": "2026-10-30"}
    kinds = {n["id"]: n["kind"] for n in body["nodes"]}
    assert kinds[f"ACCT:{shop.account_ids[0]}"] == "account"
    assert kinds["name:RAVI TRADERS"] == "counterparty"
    labels = {n["id"]: n["label"] for n in body["nodes"]}
    assert labels[f"ACCT:{shop.account_ids[0]}"] == "A/c ••1111"
    internal = [e for e in body["edges"] if e["from"].startswith("ACCT:")
                and e["to"].startswith("ACCT:")]
    assert len(internal) == 1 and internal[0]["total_paise"] == 2_000_000
    assert body["cycles"] == [[f"ACCT:{shop.account_ids[0]}", "name:RAVI TRADERS"]]
    assert api.get(f"/v1/businesses/{shop.business_id}/graph",
                   headers=login(api, people.owner1)).status_code == 403


def test_other_owner_and_other_org_get_404(api, people, shop):
    for who in (people.owner2, people.owner_b):
        headers = login(api, who)
        for path in ("metrics", "transactions"):
            assert api.get(f"/v1/businesses/{shop.business_id}/{path}",
                           headers=headers).status_code == 404
