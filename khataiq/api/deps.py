"""FastAPI dependencies: who is calling, what they may do, and their tenant session."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from khataiq.db import tenant_session
from khataiq.errors import Forbidden, TooManyRequests, Unauthorized
from khataiq.models.enums import UserRole
from khataiq.principal import Principal
from khataiq.ratelimit import Bucket, get_limiter
from khataiq.security import TokenError, verify_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Ctx:
    """What a route needs to do work: the caller, and a way to open their tenant transaction.

    Routes open the transaction explicitly (`with ctx.session() as s:`) so it commits before
    the response is built: a failed commit can never follow a 201 the client already has.
    """

    user: Principal

    @contextmanager
    def session(self) -> Iterator[Session]:
        with tenant_session(self.user.org_id) as s:
            yield s


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if credentials is None:
        raise Unauthorized("missing bearer token")
    try:
        claims = verify_access_token(credentials.credentials)
    except TokenError as exc:
        raise Unauthorized(str(exc)) from exc
    return Principal(id=claims.user_id, org_id=claims.org_id, role=claims.role)


def rate_limit(bucket: Bucket) -> Callable[..., None]:
    """Dependency: spend one token from the caller's bucket, or 429 with Retry-After."""

    def check(request: Request,
              credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
        identity = _rate_limit_identity(request, credentials)
        allowed, retry_after = get_limiter().hit(bucket, identity)
        if not allowed:
            raise TooManyRequests(f"rate limit for {bucket.name} exceeded",
                                  headers={"Retry-After": str(retry_after)})

    return check


def _rate_limit_identity(request: Request,
                         credentials: HTTPAuthorizationCredentials | None) -> str:
    """Per user when the token is valid, else per client address (e.g. the login route)."""
    if credentials is not None:
        try:
            return f"user:{verify_access_token(credentials.credentials).user_id}"
        except TokenError:
            pass
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def ctx(user: Principal = Depends(current_user)) -> Ctx:
    return Ctx(user)


def require_role(*roles: UserRole) -> Callable[..., Ctx]:
    """Dependency factory: the caller must have one of roles, else 403."""
    allowed = frozenset(roles)

    def check(user: Principal = Depends(current_user)) -> Ctx:
        if user.role not in allowed:
            raise Forbidden(f"requires role: {', '.join(sorted(r.value for r in allowed))}")
        return Ctx(user)

    return check


officer_ctx = require_role(UserRole.OFFICER, UserRole.ADMIN)
admin_ctx = require_role(UserRole.ADMIN)
owner_ctx = require_role(UserRole.OWNER)
