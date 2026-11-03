"""Small helpers that insert valid rows, so each test only spells out what it cares about."""

from __future__ import annotations

import hashlib
from datetime import date
from itertools import count

from sqlalchemy.orm import Session

from khataiq.models import Account, Business, Organization, Transaction, Upload, User
from khataiq.models.enums import TxnDirection, UserRole

_seq = count(1)


def org(s: Session, name: str = "Lender") -> Organization:
    row = Organization(name=f"{name} {next(_seq)}")
    s.add(row)
    s.flush()
    return row


def user(s: Session, org_id: int, role: UserRole = UserRole.OWNER,
         email: str | None = None, password_hash: str = "x") -> User:
    row = User(org_id=org_id, email=email or f"user{next(_seq)}@example.com",
               password_hash=password_hash, role=role)
    s.add(row)
    s.flush()
    return row


def business(s: Session, org_id: int, owner_user_id: int, name: str = "Shop") -> Business:
    row = Business(org_id=org_id, owner_user_id=owner_user_id, name=name, category="kirana")
    s.add(row)
    s.flush()
    return row


def account(s: Session, org_id: int, business_id: int, mask: str | None = None,
            bank: str = "demo", fmt: str = "csv", upi_id: str | None = None) -> Account:
    row = Account(org_id=org_id, business_id=business_id, bank=bank, format=fmt,
                  account_mask=mask or f"{next(_seq) % 10000:04d}", account_type="current",
                  upi_id=upi_id)
    s.add(row)
    s.flush()
    return row


def upload(s: Session, org_id: int, account_id: int, created_by: int) -> Upload:
    digest = hashlib.sha256(str(next(_seq)).encode()).hexdigest()
    row = Upload(org_id=org_id, account_id=account_id, storage_key=f"k/{digest}", sha256=digest,
                 content_type="text/csv", size_bytes=10, created_by=created_by)
    s.add(row)
    s.flush()
    return row


def txn(s: Session, org_id: int, account_id: int, upload_id: int, amount_paise: int = 100_00,
        direction: TxnDirection = TxnDirection.CREDIT, fingerprint: str | None = None,
        txn_date: date = date(2026, 10, 1), narration: str = "UPI/TEST") -> Transaction:
    row = Transaction(
        org_id=org_id, account_id=account_id, upload_id=upload_id, txn_date=txn_date,
        amount_paise=amount_paise, direction=direction, balance_after_paise=0,
        narration=narration, narration_norm=narration.upper(),
        fingerprint=fingerprint or hashlib.sha256(str(next(_seq)).encode()).hexdigest(),
        source_line=1,
    )
    s.add(row)
    s.flush()
    return row


def world(s: Session) -> dict[str, int]:
    """One org with an owner, a business, an account and an upload. Returns their ids."""
    o = org(s)
    u = user(s, o.id)
    b = business(s, o.id, u.id)
    a = account(s, o.id, b.id)
    up = upload(s, o.id, a.id, u.id)
    return {"org": o.id, "user": u.id, "business": b.id, "account": a.id, "upload": up.id}
