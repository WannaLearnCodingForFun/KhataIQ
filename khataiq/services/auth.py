"""Login, refresh-token rotation with family revocation, and logout.

Flow of a refresh:
  1. Find the token row by its hash (auth_find_refresh_token: no tenant needed yet).
  2. judge_refresh_token decides OK / UNKNOWN / EXPIRED / REUSED.
  3. OK: in the user's tenant session, revoke this token *only if it is still unrevoked*
     (one UPDATE ... WHERE revoked_at IS NULL), then issue its successor in the same family.
     If that UPDATE touches no row, another request rotated it first: that's reuse too.
  4. REUSED: someone presented a token that was already rotated. Either the legitimate client
     or a thief holds the newer one; we can't tell which, so the whole family is revoked and
     both must log in again.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from khataiq import audit
from khataiq.config import get_settings
from khataiq.db import get_sessionmaker, tenant_session
from khataiq.errors import Unauthorized
from khataiq.models import RefreshToken, User
from khataiq.models.enums import UserRole
from khataiq.security import (
    RefreshVerdict,
    StoredRefreshToken,
    burn_password_check,
    hash_refresh_token,
    issue_access_token,
    judge_refresh_token,
    new_refresh_token,
    verify_password,
)

log = logging.getLogger(__name__)
INVALID_LOGIN = "invalid email or password"


@dataclass(frozen=True)
class Tokens:
    access_token: str
    expires_in: int
    refresh_token: str


@dataclass(frozen=True)
class _FoundToken:
    id: int
    org_id: int
    user_id: int
    family_id: uuid.UUID
    stored: StoredRefreshToken


def _now() -> datetime:
    return datetime.now(UTC)


def login(email: str, password: str) -> Tokens:
    with get_sessionmaker()() as s:
        row = s.execute(
            text("SELECT id, org_id, password_hash, role, is_active FROM auth_find_user(:e)"),
            {"e": email.strip()},
        ).first()
    if row is None:
        burn_password_check(password)  # same timing whether or not the account exists
        raise Unauthorized(INVALID_LOGIN)
    if not verify_password(row.password_hash, password) or not row.is_active:
        raise Unauthorized(INVALID_LOGIN)

    with tenant_session(row.org_id) as s:
        refresh = _store_new_token(s, row.org_id, row.id, uuid.uuid4())
        audit.record(s, org_id=row.org_id, actor_id=row.id, action="auth.login",
                     entity_type="user", entity_id=row.id)
    access, ttl = issue_access_token(row.id, row.org_id, UserRole(row.role))
    return Tokens(access, ttl, refresh)


def refresh(presented: str) -> Tokens:
    found = _find(presented)
    verdict = judge_refresh_token(found.stored if found else None, _now())
    if found is None or verdict in (RefreshVerdict.UNKNOWN, RefreshVerdict.EXPIRED):
        raise Unauthorized("refresh token is invalid or expired")
    if verdict == RefreshVerdict.REUSED:
        _revoke_family(found, reason="reuse")
        raise Unauthorized("refresh token was already used; please log in again")

    with tenant_session(found.org_id) as s:
        rotated = s.execute(
            update(RefreshToken)
            .where(RefreshToken.id == found.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
            .returning(RefreshToken.id)
        ).first()
        user = s.get(User, found.user_id)
        if rotated is not None and user is not None and user.is_active:
            new_token = _store_new_token(s, found.org_id, found.user_id, found.family_id)
            role = user.role
        else:
            new_token = None
    if new_token is None:
        # Lost a race with a concurrent refresh of the same token, or the user was disabled.
        _revoke_family(found, reason="race-or-inactive")
        raise Unauthorized("refresh token was already used; please log in again")
    access, ttl = issue_access_token(found.user_id, found.org_id, role)
    return Tokens(access, ttl, new_token)


def logout(presented: str | None) -> None:
    """Revoke the cookie's whole family. Unknown or missing tokens are a silent no-op."""
    if not presented:
        return
    found = _find(presented)
    if found is not None:
        _revoke_family(found, reason="logout")


def _find(presented: str) -> _FoundToken | None:
    with get_sessionmaker()() as s:
        row = s.execute(
            text("SELECT id, org_id, user_id, family_id, expires_at, revoked_at "
                 "FROM auth_find_refresh_token(:h)"),
            {"h": hash_refresh_token(presented)},
        ).first()
    if row is None:
        return None
    return _FoundToken(row.id, row.org_id, row.user_id, row.family_id,
                       StoredRefreshToken(row.expires_at, row.revoked_at))


def _store_new_token(s: Session, org_id: int, user_id: int, family_id: uuid.UUID) -> str:
    token = new_refresh_token()
    days = get_settings().refresh_token_ttl_days
    s.add(RefreshToken(org_id=org_id, user_id=user_id, family_id=family_id,
                       token_hash=hash_refresh_token(token),
                       expires_at=_now() + timedelta(days=days)))
    return token


def _revoke_family(found: _FoundToken, reason: str) -> None:
    with tenant_session(found.org_id) as s:
        s.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == found.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        audit.record(s, org_id=found.org_id, actor_id=found.user_id,
                     action=f"auth.refresh_family_revoked.{reason}", entity_type="user",
                     entity_id=found.user_id)
    if reason != "logout":
        log.warning("refresh token family revoked", extra={"reason": reason,
                                                            "user_id": found.user_id})


def family_tokens(s: Session, family_id: uuid.UUID) -> list[RefreshToken]:
    """All tokens of a family (used by tests and the admin view)."""
    return list(s.scalars(select(RefreshToken).where(RefreshToken.family_id == family_id)))
