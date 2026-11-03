from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BusinessCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    owner_user_id: int | None = Field(default=None, description="Required when an admin creates")


class BusinessUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100)


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    owner_user_id: int
    created_at: datetime


class AccountCreateIn(BaseModel):
    bank: str = Field(min_length=1, max_length=50)
    format: str = Field(min_length=1, max_length=20)
    account_number: str = Field(min_length=6, max_length=30,
                                description="Only the last 4 digits are stored")
    type: str = Field(default="current", pattern="^(current|savings|od|cc)$")
    upi_id: str | None = Field(default=None, max_length=100)


class AccountOut(BaseModel):
    id: int
    business_id: int
    bank: str
    format: str
    account_mask: str
    type: str
    upi_id: str | None


class BusinessDetailOut(BusinessOut):
    accounts: list[AccountOut]
    latest_metric_run_id: int | None


class ParserOut(BaseModel):
    bank: str
    format: str
    version: str
