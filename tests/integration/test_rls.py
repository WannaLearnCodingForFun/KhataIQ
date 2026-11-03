"""M1.2: row-level security and the app role's privileges."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from tests.integration import factories as f


def two_orgs(s: Session) -> tuple[dict[str, int], dict[str, int]]:
    a, b = f.world(s), f.world(s)
    for w in (a, b):
        f.txn(s, w["org"], w["account"], w["upload"])
    s.commit()
    return a, b


def as_org(conn, org_id: int) -> None:
    conn.execute(text("SELECT set_config('app.org_id', :v, true)"), {"v": str(org_id)})


def test_app_role_only_sees_its_own_org(owner_session: Session, app_engine: Engine):
    a, b = two_orgs(owner_session)
    with app_engine.begin() as conn:
        as_org(conn, a["org"])
        assert conn.execute(text("SELECT org_id FROM transactions")).scalars().all() == [a["org"]]
        other = conn.execute(text("SELECT * FROM businesses WHERE id = :b"), {"b": b["business"]})
        assert other.first() is None


def test_no_org_set_means_no_rows(owner_session: Session, app_engine: Engine):
    two_orgs(owner_session)
    with app_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM transactions")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM organizations")).scalar_one() == 0


def test_app_role_cannot_insert_into_another_org(owner_session: Session, app_engine: Engine):
    a, b = two_orgs(owner_session)
    with pytest.raises(ProgrammingError, match="row-level security"), app_engine.begin() as conn:
        as_org(conn, a["org"])
        conn.execute(text(
            "INSERT INTO businesses (org_id, owner_user_id, name, category) "
            "VALUES (:o, :u, 'x', 'y')"), {"o": b["org"], "u": b["user"]})


def test_app_role_cannot_update_audit_log(owner_session: Session, app_engine: Engine):
    w = f.world(owner_session)
    owner_session.execute(text(
        "INSERT INTO audit_log (org_id, action, entity_type) VALUES (:o, 'test', 'x')"),
        {"o": w["org"]})
    owner_session.commit()
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        as_org(conn, w["org"])
        conn.execute(text("UPDATE audit_log SET action = 'tampered'"))
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        as_org(conn, w["org"])
        conn.execute(text("DELETE FROM audit_log"))


def test_app_role_can_append_to_audit_log(owner_session: Session, app_engine: Engine):
    w = f.world(owner_session)
    owner_session.commit()
    with app_engine.begin() as conn:
        as_org(conn, w["org"])
        conn.execute(text(
            "INSERT INTO audit_log (org_id, action, entity_type) VALUES (:o, 'ok', 'x')"),
            {"o": w["org"]})


def test_labels_view_respects_rls(owner_session: Session, app_engine: Engine):
    a, b = f.world(owner_session), f.world(owner_session)
    for w in (a, b):
        t = f.txn(owner_session, w["org"], w["account"], w["upload"])
        owner_session.execute(text(
            "INSERT INTO txn_labels (org_id, txn_id, label, method) "
            "VALUES (:o, :t, 'sales', 'rule')"), {"o": w["org"], "t": t.id})
    owner_session.commit()
    with app_engine.begin() as conn:
        as_org(conn, a["org"])
        orgs = conn.execute(text("SELECT org_id FROM current_txn_labels")).scalars().all()
    assert orgs == [a["org"]]


def test_auth_lookup_works_without_tenant_context(owner_session: Session, app_engine: Engine):
    w = f.world(owner_session)
    f.user(owner_session, w["org"], email="officer@example.com")
    owner_session.commit()
    with app_engine.begin() as conn:
        row = conn.execute(text("SELECT org_id FROM auth_find_user('Officer@Example.com')")).one()
    assert row.org_id == w["org"]


def test_app_role_cannot_bypass_rls(app_engine: Engine):
    with app_engine.begin() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("SET row_security = off; SELECT * FROM transactions"))
