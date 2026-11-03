"""Load-test data: the seeded dev org plus six months of synthetic history for business 1."""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import khataiq.pipeline.stages  # noqa: F401
from khataiq.config import get_settings
from khataiq.models import Account, Business, User
from khataiq.models.enums import UserRole
from khataiq.pipeline.outbox import pipeline_publisher, relay_once
from khataiq.pipeline.runner import InlineDispatcher
from khataiq.principal import Principal
from khataiq.services.uploads import create_upload
from synthetic.generator import GenConfig, generate

if __name__ == "__main__":
    engine = create_engine(get_settings().migration_database_url)
    with Session(engine) as s:
        business = s.scalars(select(Business).order_by(Business.id)).first()
        assert business is not None, "run scripts/seed_dev.py first"
        owner = s.get(User, business.owner_user_id)
        accounts = list(s.scalars(select(Account).where(Account.business_id == business.id)
                                  .order_by(Account.id)))
    assert owner is not None
    principal = Principal(owner.id, owner.org_id, UserRole.OWNER)
    biz = generate(42, GenConfig(min_accounts=2, max_accounts=2))
    for st in sorted(biz.statements, key=lambda s: (s.statement_index, s.account_index)):
        create_upload(principal, accounts[st.account_index].id, str(uuid.uuid4()), st.csv)
        dispatcher = InlineDispatcher()
        relay_once(pipeline_publisher(dispatcher))
        dispatcher.drain()
    print(f"business {business.id}: loaded {len(biz.rows)} rows; accounts "
          f"{[a.id for a in accounts]}")
