from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from khataiq.models.enums import UserRole


class LoginIn(BaseModel):
    # Not EmailStr: a malformed address should fail like any unknown one (401), not reveal
    # validation rules with a 422.
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: UserRole
    org_id: int


class UserCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    role: UserRole
