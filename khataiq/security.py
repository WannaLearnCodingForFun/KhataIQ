"""Password hashing (argon2), access tokens (JWT) and refresh-token rules.

Everything here is pure apart from reading settings; the database side of refresh tokens
lives in khataiq/services/auth.py.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from khataiq.config import get_settings
from khataiq.models.enums import UserRole

_hasher = PasswordHasher()
JWT_ALGORITHM = "HS256"


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True if password matches. Never raises for a wrong password or a malformed hash."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with weaker parameters than the current defaults."""
    return _hasher.check_needs_rehash(password_hash)


# A real hash of a random password: verifying against it when the email is unknown makes a
# failed login take the same time whether or not the account exists.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


def burn_password_check(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


# ------------------------------------------------------------------ access tokens

class TokenError(Exception):
    """An access token is missing, malformed, tampered with or expired."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    org_id: int
    role: UserRole
    expires_at: int


def issue_access_token(user_id: int, org_id: int, role: UserRole,
                       now: int | None = None) -> tuple[str, int]:
    """Signed HS256 JWT. Returns (token, lifetime in seconds)."""
    settings = get_settings()
    issued = int(time.time()) if now is None else now
    ttl = settings.access_token_ttl_seconds
    claims = {"sub": str(user_id), "org_id": org_id, "role": role.value, "typ": "access",
              "iat": issued, "exp": issued + ttl}
    token = jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)
    return token, ttl


def verify_access_token(token: str) -> AccessClaims:
    """Check signature, expiry and shape. Raises TokenError on anything wrong."""
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],  # never let the token choose its own algorithm
            options={"require": ["exp", "sub", "org_id", "role", "typ"]},
        )
        if claims["typ"] != "access":
            raise TokenError("not an access token")
        return AccessClaims(user_id=int(claims["sub"]), org_id=int(claims["org_id"]),
                            role=UserRole(claims["role"]), expires_at=int(claims["exp"]))
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise TokenError("invalid token") from exc


# ------------------------------------------------------------------ refresh tokens

def new_refresh_token() -> str:
    """256 bits from the OS CSPRNG, URL-safe so it fits in a cookie."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex. A fast hash is fine here (unlike passwords): the token is already
    high-entropy random data, so there's nothing to brute-force."""
    return hashlib.sha256(token.encode()).hexdigest()


class RefreshVerdict(StrEnum):
    OK = "ok"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    REUSED = "reused"  # already rotated or revoked: treat as theft, revoke the family


@dataclass(frozen=True)
class StoredRefreshToken:
    expires_at: datetime
    revoked_at: datetime | None


def judge_refresh_token(stored: StoredRefreshToken | None, now: datetime) -> RefreshVerdict:
    """Decide what to do with a presented refresh token, given its stored row."""
    if stored is None:
        return RefreshVerdict.UNKNOWN
    if stored.revoked_at is not None:
        return RefreshVerdict.REUSED
    if stored.expires_at <= now:
        return RefreshVerdict.EXPIRED
    return RefreshVerdict.OK
