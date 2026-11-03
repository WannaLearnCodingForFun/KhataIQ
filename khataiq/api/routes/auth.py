"""Login, token refresh, logout and the current user."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Response, status

from khataiq.api.deps import Ctx, admin_ctx, ctx, rate_limit
from khataiq.api.schemas.auth import LoginIn, TokenOut, UserCreateIn, UserOut
from khataiq.config import get_settings
from khataiq.errors import Unauthorized
from khataiq.ratelimit import general_bucket
from khataiq.services import auth, users

REFRESH_COOKIE = "khataiq_refresh"
COOKIE_PATH = "/v1/auth"

router = APIRouter(prefix="/v1", tags=["auth"])


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE, token, max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,                   # JavaScript can't read it, so XSS can't steal it
        secure=settings.cookie_secure,   # only sent over HTTPS
        samesite="strict",               # not sent on cross-site requests (CSRF)
        path=COOKIE_PATH,                # only sent to the auth endpoints
    )


@router.post("/auth/login", response_model=TokenOut,
             dependencies=[Depends(rate_limit(general_bucket()))])
def login(body: LoginIn, response: Response) -> TokenOut:
    tokens = auth.login(body.email, body.password)
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenOut(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/auth/refresh", response_model=TokenOut,
             dependencies=[Depends(rate_limit(general_bucket()))])
def refresh(response: Response,
            khataiq_refresh: str | None = Cookie(default=None)) -> TokenOut:
    if not khataiq_refresh:
        raise Unauthorized("missing refresh cookie")
    tokens = auth.refresh(khataiq_refresh)
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenOut(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, _: Ctx = Depends(ctx),
           khataiq_refresh: str | None = Cookie(default=None)) -> Response:
    auth.logout(khataiq_refresh)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut,
            dependencies=[Depends(rate_limit(general_bucket()))])
def me(c: Ctx = Depends(ctx)) -> UserOut:
    with c.session() as s:
        return UserOut.model_validate(users.get_user(s, c.user.id))


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(rate_limit(general_bucket()))])
def create_user(body: UserCreateIn, c: Ctx = Depends(admin_ctx)) -> UserOut:
    with c.session() as s:
        return UserOut.model_validate(
            users.create_user(s, c.user, body.email, body.password, body.role))
