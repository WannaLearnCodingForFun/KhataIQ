"""Seed a development database: one org, three users of each role, two businesses.

    python scripts/seed_dev.py

Runs as the migration (owner) role because creating an organization is not something the app
role may do. Safe to run twice: if the org already exists, nothing is added.
Every seeded user's password is DEV_PASSWORD; never use this against a real deployment.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from khataiq.config import get_settings
from khataiq.models import Account, Business, Organization, User
from khataiq.models.enums import UserRole
from khataiq.security import hash_password

ORG_NAME = "Demo Lender"
DEV_PASSWORD = "khataiq-dev-password"
DOMAIN = "demo.khataiq.dev"


def seed(engine: Engine) -> bool:
    """Insert the dev data. Returns False if it was already there."""
    with Session(engine) as session, session.begin():
        if session.scalar(select(Organization).where(Organization.name == ORG_NAME)):
            return False
        org = Organization(name=ORG_NAME)
        session.add(org)
        session.flush()

        password_hash = hash_password(DEV_PASSWORD)
        users: dict[str, User] = {}
        for role in UserRole:
            for n in range(1, 4):
                email = f"{role.value}{n}@{DOMAIN}"
                users[email] = User(org_id=org.id, email=email, password_hash=password_hash,
                                    role=role)
        session.add_all(users.values())
        session.flush()

        shops = [("Sharma Kirana Store", "kirana", "owner1", ["4321", "8765"]),
                 ("Mehta Medicals", "pharmacy", "owner2", ["1111"])]
        for name, category, owner, masks in shops:
            business = Business(org_id=org.id, owner_user_id=users[f"{owner}@{DOMAIN}"].id,
                                name=name, category=category)
            session.add(business)
            session.flush()
            for mask in masks:
                session.add(Account(org_id=org.id, business_id=business.id, bank="demo",
                                    format="csv", account_mask=mask, account_type="current"))
    return True


if __name__ == "__main__":
    created = seed(create_engine(get_settings().migration_database_url))
    if created:
        print(f"Seeded {ORG_NAME}: users <role><1-3>@{DOMAIN}, password {DEV_PASSWORD!r}")
    else:
        print(f"{ORG_NAME} already exists; nothing to do")
