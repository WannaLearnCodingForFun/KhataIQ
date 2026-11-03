"""ORM row -> response schema conversions that aren't a plain attribute copy."""

from __future__ import annotations

from khataiq.api.schemas.businesses import AccountOut
from khataiq.models import Account


def account_out(account: Account) -> AccountOut:
    return AccountOut(id=account.id, business_id=account.business_id, bank=account.bank,
                      format=account.format, account_mask=account.account_mask,
                      type=account.account_type, upi_id=account.upi_id)
