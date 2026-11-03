"""Who may see which business. RLS already hides other orgs; this adds the in-org rule that
owners only see their own businesses. Anything not visible is NotFound, never Forbidden."""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from khataiq.errors import NotFound
from khataiq.models import Account, Business, Upload
from khataiq.principal import Principal


def visible_businesses(user: Principal) -> Select[Business]:
    query = select(Business)
    if user.is_owner:
        query = query.where(Business.owner_user_id == user.id)
    return query


def get_business(s: Session, user: Principal, business_id: int) -> Business:
    business = s.scalar(visible_businesses(user).where(Business.id == business_id))
    if business is None:
        raise NotFound(f"business {business_id} not found")
    return business


def get_account(s: Session, user: Principal, account_id: int) -> Account:
    account = s.get(Account, account_id)
    if account is None:
        raise NotFound(f"account {account_id} not found")
    try:
        get_business(s, user, account.business_id)
    except NotFound:
        raise NotFound(f"account {account_id} not found") from None
    return account


def get_upload(s: Session, user: Principal, upload_id: int) -> Upload:
    upload = s.get(Upload, upload_id)
    if upload is None:
        raise NotFound(f"upload {upload_id} not found")
    try:
        get_account(s, user, upload.account_id)
    except NotFound:
        raise NotFound(f"upload {upload_id} not found") from None
    return upload
