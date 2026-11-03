"""Businesses and their bank accounts."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from khataiq import audit
from khataiq.errors import BadRequest, Conflict, UnprocessableEntity
from khataiq.models import Account, Business, MetricRun, User
from khataiq.models.enums import UserRole
from khataiq.pipeline.parsers import get_parser
from khataiq.principal import Principal
from khataiq.services.access import get_business, visible_businesses

_DIGITS = re.compile(r"[0-9]{6,18}")


def create_business(s: Session, actor: Principal, name: str, category: str,
                    owner_user_id: int | None = None) -> Business:
    if actor.is_owner:
        owner_id = actor.id
    else:
        if owner_user_id is None:
            raise BadRequest("owner_user_id is required when an admin creates a business")
        owner = s.get(User, owner_user_id)
        if owner is None or owner.role != UserRole.OWNER:
            raise UnprocessableEntity("owner_user_id must be an owner in your organization")
        owner_id = owner.id
    business = Business(org_id=actor.org_id, owner_user_id=owner_id, name=name.strip(),
                        category=category.strip())
    s.add(business)
    s.flush()
    audit.record(s, org_id=actor.org_id, actor_id=actor.id, action="business.create",
                 entity_type="business", entity_id=business.id,
                 after={"name": business.name, "category": business.category,
                        "owner_user_id": owner_id})
    return business


def list_businesses(s: Session, actor: Principal, after_id: int | None,
                    limit: int) -> list[Business]:
    query = visible_businesses(actor).order_by(Business.id.desc()).limit(limit + 1)
    if after_id is not None:
        query = query.where(Business.id < after_id)
    return list(s.scalars(query))


def update_business(s: Session, actor: Principal, business_id: int, name: str | None,
                    category: str | None) -> Business:
    business = get_business(s, actor, business_id)
    before = {"name": business.name, "category": business.category}
    if name is not None:
        business.name = name.strip()
    if category is not None:
        business.category = category.strip()
    after = {"name": business.name, "category": business.category}
    if after != before:
        audit.record(s, org_id=actor.org_id, actor_id=actor.id, action="business.update",
                     entity_type="business", entity_id=business.id, before=before, after=after)
    return business


def business_accounts(s: Session, business_id: int) -> list[Account]:
    return list(s.scalars(select(Account).where(Account.business_id == business_id)
                          .order_by(Account.id)))


def latest_metric_run_id(s: Session, business_id: int) -> int | None:
    return s.scalar(select(func.max(MetricRun.id)).where(MetricRun.business_id == business_id))


def mask_account_number(account_number: str) -> str:
    """Keep only the last 4 digits; the full number never reaches the database or logs."""
    digits = account_number.replace(" ", "").replace("-", "")
    if not _DIGITS.fullmatch(digits):
        raise UnprocessableEntity("account_number must be 6 to 18 digits")
    return digits[-4:]


def create_account(s: Session, actor: Principal, business_id: int, bank: str, fmt: str,
                   account_number: str, account_type: str, upi_id: str | None) -> Account:
    business = get_business(s, actor, business_id)
    try:
        get_parser(bank, fmt)
    except KeyError as exc:
        raise UnprocessableEntity(f"no parser for bank={bank!r} format={fmt!r}; "
                                  "see GET /v1/parsers") from exc
    account = Account(org_id=actor.org_id, business_id=business.id, bank=bank.lower(),
                      format=fmt.lower(), account_mask=mask_account_number(account_number),
                      account_type=account_type, upi_id=upi_id.strip().lower() if upi_id else None)
    s.add(account)
    try:
        with s.begin_nested():
            s.flush()
    except IntegrityError as exc:
        raise Conflict("this business already has that account") from exc
    audit.record(s, org_id=actor.org_id, actor_id=actor.id, action="account.create",
                 entity_type="account", entity_id=account.id,
                 after={"business_id": business.id, "bank": account.bank,
                        "format": account.format, "account_mask": account.account_mask})
    return account
