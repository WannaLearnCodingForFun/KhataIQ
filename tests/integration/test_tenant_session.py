"""M1.3: tenant_session scoping and the dev seed script."""

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from khataiq.db import tenant_session
from khataiq.models import Business, Organization, User
from scripts.seed_dev import seed
from tests.integration import factories as f


def test_tenant_session_sees_only_its_org(owner_session: Session):
    a, b = f.world(owner_session), f.world(owner_session)
    owner_session.commit()
    with tenant_session(a["org"]) as s:
        assert s.scalars(select(Business.id)).all() == [a["business"]]
    with tenant_session(b["org"]) as s:
        assert s.scalars(select(Business.id)).all() == [b["business"]]


def test_setting_does_not_leak_between_sessions(owner_session: Session):
    a = f.world(owner_session)
    owner_session.commit()
    with tenant_session(a["org"]) as s:
        assert s.execute(text("SELECT app_org_id()")).scalar_one() == a["org"]
    from khataiq.db import get_sessionmaker
    with get_sessionmaker()() as plain:
        assert plain.execute(text("SELECT app_org_id()")).scalar_one() is None


def test_tenant_survives_a_commit_inside_the_session(owner_session: Session):
    a = f.world(owner_session)
    owner_session.commit()
    from khataiq.db import bind_tenant, get_sessionmaker
    with get_sessionmaker()() as s:
        bind_tenant(s, a["org"])
        assert s.scalars(select(Business.id)).all() == [a["business"]]
        s.commit()  # ends the first transaction; the next one must re-apply app.org_id
        assert s.scalars(select(Business.id)).all() == [a["business"]]


def test_seed_creates_org_users_and_businesses_once(owner_engine: Engine):
    assert seed(owner_engine) is True
    assert seed(owner_engine) is False
    with Session(owner_engine) as s:
        assert s.scalar(select(func.count()).select_from(Organization)) == 1
        roles = s.execute(select(User.role, func.count()).group_by(User.role)).all()
        assert sorted((r.value, n) for r, n in roles) == [("admin", 3), ("officer", 3),
                                                          ("owner", 3)]
        assert s.scalar(select(func.count()).select_from(Business)) == 2
