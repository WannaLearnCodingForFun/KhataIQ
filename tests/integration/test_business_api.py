"""M2.3: businesses and accounts — visibility rules, masking, audit."""

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from khataiq.models import AuditLog
from tests.integration.conftest import People, login


def make_business(api, headers, name="Sharma Kirana", **extra):
    r = api.post("/v1/businesses", json={"name": name, "category": "kirana", **extra},
                 headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_owner_cannot_see_another_owners_business(api, people: People):
    mine = make_business(api, login(api, people.owner1))
    other = login(api, people.owner2)
    assert api.get(f"/v1/businesses/{mine['id']}", headers=other).status_code == 404
    assert api.get("/v1/businesses", headers=other).json()["items"] == []


def test_officer_sees_every_business_in_the_org(api, people: People):
    make_business(api, login(api, people.owner1), "One")
    make_business(api, login(api, people.owner2), "Two")
    r = api.get("/v1/businesses", headers=login(api, people.officer))
    assert sorted(b["name"] for b in r.json()["items"]) == ["One", "Two"]


def test_cross_org_access_is_404(api, people: People):
    mine = make_business(api, login(api, people.owner1))
    outsider = login(api, people.owner_b)
    assert api.get(f"/v1/businesses/{mine['id']}", headers=outsider).status_code == 404
    r = api.post(f"/v1/businesses/{mine['id']}/accounts", headers=outsider,
                 json={"bank": "demo", "format": "csv", "account_number": "123456789012"})
    assert r.status_code == 404


def test_account_keeps_only_last_four_digits(api, people: People, owner_session: Session):
    owner = login(api, people.owner1)
    business = make_business(api, owner)
    r = api.post(f"/v1/businesses/{business['id']}/accounts", headers=owner,
                 json={"bank": "demo", "format": "csv", "account_number": "5010 0123 4567 89"})
    assert r.status_code == 201
    assert r.json()["account_mask"] == "6789"
    dump = owner_session.execute(text(
        "SELECT string_agg(t::text, '') FROM (SELECT * FROM accounts) t")).scalar_one()
    audit_dump = owner_session.execute(text(
        "SELECT string_agg(t::text, '') FROM (SELECT * FROM audit_log) t")).scalar_one()
    assert "50100123456789" not in dump and "50100123456789" not in audit_dump
    detail = api.get(f"/v1/businesses/{business['id']}", headers=owner).json()
    assert [a["account_mask"] for a in detail["accounts"]] == ["6789"]


def test_unknown_parser_is_rejected(api, people: People):
    owner = login(api, people.owner1)
    business = make_business(api, owner)
    r = api.post(f"/v1/businesses/{business['id']}/accounts", headers=owner,
                 json={"bank": "nobank", "format": "csv", "account_number": "123456789012"})
    assert r.status_code == 422


def test_only_owner_adds_accounts(api, people: People):
    business = make_business(api, login(api, people.owner1))
    r = api.post(f"/v1/businesses/{business['id']}/accounts", headers=login(api, people.officer),
                 json={"bank": "demo", "format": "csv", "account_number": "123456789012"})
    assert r.status_code == 403


def test_create_and_update_are_audited(api, people: People, owner_session: Session):
    owner = login(api, people.owner1)
    business = make_business(api, owner)
    r = api.patch(f"/v1/businesses/{business['id']}", json={"name": "Renamed"}, headers=owner)
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    rows = owner_session.scalars(
        select(AuditLog).where(AuditLog.entity_type == "business").order_by(AuditLog.id)).all()
    assert [r.action for r in rows] == ["business.create", "business.update"]
    assert rows[1].before == {"name": "Sharma Kirana", "category": "kirana"}
    assert rows[1].after["name"] == "Renamed"
    assert rows[1].request_id


def test_admin_creates_business_for_an_owner(api, people: People, owner_session: Session):
    owner_id = owner_session.execute(
        text("SELECT id FROM users WHERE email = :e"), {"e": people.owner2}).scalar_one()
    admin = login(api, people.admin)
    assert api.post("/v1/businesses", json={"name": "X", "category": "y"},
                    headers=admin).status_code == 400
    created = make_business(api, admin, owner_user_id=owner_id)
    assert created["owner_user_id"] == owner_id


def test_cursor_pagination(api, people: People):
    owner = login(api, people.owner1)
    for i in range(5):
        make_business(api, owner, f"B{i}")
    first = api.get("/v1/businesses?limit=2", headers=owner).json()
    second = api.get(f"/v1/businesses?limit=2&cursor={first['next_cursor']}",
                     headers=owner).json()
    third = api.get(f"/v1/businesses?limit=2&cursor={second['next_cursor']}",
                    headers=owner).json()
    names = [b["name"] for page in (first, second, third) for b in page["items"]]
    assert names == ["B4", "B3", "B2", "B1", "B0"] and third["next_cursor"] is None
    assert api.get("/v1/businesses?cursor=garbage", headers=owner).status_code == 400
    assert api.get("/v1/businesses?limit=500", headers=owner).status_code == 400


def test_parsers_catalogue(api, people: People):
    r = api.get("/v1/parsers", headers=login(api, people.owner1))
    assert {"bank": "sbi_like", "format": "csv", "version": "sbi-like-csv/1"} in r.json()
