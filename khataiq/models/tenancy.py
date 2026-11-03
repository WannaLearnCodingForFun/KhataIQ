"""Organizations (tenants), users, businesses and their bank accounts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from khataiq.db import Base
from khataiq.models.base import created_at_column, id_column, org_id_column
from khataiq.models.enums import UserRole, pg_enum


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = id_column()
    name: Mapped[str]
    created_at: Mapped[datetime] = created_at_column()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str]
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str]
    category: Mapped[str]
    created_at: Mapped[datetime] = created_at_column()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    bank: Mapped[str]
    format: Mapped[str]
    account_mask: Mapped[str] = mapped_column(String(4))
    account_type: Mapped[str] = mapped_column("type")
    upi_id: Mapped[str | None]
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("business_id", "bank", "account_mask"),
        CheckConstraint("account_mask ~ '^[0-9]{4}$'", name="mask_is_last_4_digits"),
    )
