"""Businesses, their accounts, and the parser catalogue."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from khataiq.api.deps import Ctx, ctx, owner_ctx, rate_limit, require_role
from khataiq.api.pagination import Page, build_page, clamp_limit, decode_cursor
from khataiq.api.schemas.businesses import (
    AccountCreateIn,
    AccountOut,
    BusinessCreateIn,
    BusinessDetailOut,
    BusinessOut,
    BusinessUpdateIn,
    ParserOut,
)
from khataiq.api.schemas.convert import account_out
from khataiq.models.enums import UserRole
from khataiq.pipeline.parsers import supported_parsers
from khataiq.ratelimit import general_bucket
from khataiq.services import access, businesses

router = APIRouter(prefix="/v1", tags=["businesses"],
                   dependencies=[Depends(rate_limit(general_bucket()))])
owner_or_admin = require_role(UserRole.OWNER, UserRole.ADMIN)


@router.post("/businesses", response_model=BusinessOut, status_code=status.HTTP_201_CREATED)
def create_business(body: BusinessCreateIn, c: Ctx = Depends(owner_or_admin)) -> BusinessOut:
    with c.session() as s:
        business = businesses.create_business(s, c.user, body.name, body.category,
                                              body.owner_user_id)
        return BusinessOut.model_validate(business)


@router.get("/businesses", response_model=Page[BusinessOut])
def list_businesses(c: Ctx = Depends(ctx), cursor: str | None = None,
                    limit: int | None = Query(default=None)) -> Page[BusinessOut]:
    size = clamp_limit(limit)
    with c.session() as s:
        rows = businesses.list_businesses(s, c.user, decode_cursor(cursor), size)
        items, next_cursor = build_page(rows, size, key=lambda b: b.id)
        return Page[BusinessOut](items=[BusinessOut.model_validate(b) for b in items],
                                 next_cursor=next_cursor)


@router.get("/businesses/{business_id}", response_model=BusinessDetailOut)
def get_business(business_id: int, c: Ctx = Depends(ctx)) -> BusinessDetailOut:
    with c.session() as s:
        business = access.get_business(s, c.user, business_id)
        return BusinessDetailOut(
            **BusinessOut.model_validate(business).model_dump(),
            accounts=[account_out(a) for a in businesses.business_accounts(s, business.id)],
            latest_metric_run_id=businesses.latest_metric_run_id(s, business.id),
        )


@router.patch("/businesses/{business_id}", response_model=BusinessOut)
def update_business(business_id: int, body: BusinessUpdateIn,
                    c: Ctx = Depends(owner_or_admin)) -> BusinessOut:
    with c.session() as s:
        business = businesses.update_business(s, c.user, business_id, body.name, body.category)
        return BusinessOut.model_validate(business)


@router.post("/businesses/{business_id}/accounts", response_model=AccountOut,
             status_code=status.HTTP_201_CREATED)
def create_account(business_id: int, body: AccountCreateIn,
                   c: Ctx = Depends(owner_ctx)) -> AccountOut:
    with c.session() as s:
        account = businesses.create_account(s, c.user, business_id, body.bank, body.format,
                                             body.account_number, body.type, body.upi_id)
        return account_out(account)


@router.get("/parsers", response_model=list[ParserOut])
def list_parsers(_: Ctx = Depends(ctx)) -> list[ParserOut]:
    return [ParserOut(bank=b, format=f, version=v) for b, f, v in supported_parsers()]
