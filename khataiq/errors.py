"""Domain errors. Services raise these; the API turns them into RFC 9457 problem+json."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status: int = 500
    title: str = "Internal server error"
    slug: str = "internal"

    def __init__(self, detail: str | None = None, *, headers: dict[str, str] | None = None,
                 extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra or {}


class BadRequest(AppError):
    status, title, slug = 400, "Bad request", "bad-request"


class Unauthorized(AppError):
    status, title, slug = 401, "Unauthorized", "unauthorized"

    def __init__(self, detail: str | None = None, **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)
        self.headers.setdefault("WWW-Authenticate", "Bearer")


class Forbidden(AppError):
    status, title, slug = 403, "Forbidden", "forbidden"


class NotFound(AppError):
    """Also used for rows in another tenant, so ids can't be probed."""

    status, title, slug = 404, "Not found", "not-found"


class Conflict(AppError):
    status, title, slug = 409, "Conflict", "conflict"


class PayloadTooLarge(AppError):
    status, title, slug = 413, "Payload too large", "payload-too-large"


class UnsupportedMediaType(AppError):
    status, title, slug = 415, "Unsupported media type", "unsupported-media-type"


class UnprocessableEntity(AppError):
    status, title, slug = 422, "Unprocessable entity", "unprocessable-entity"


class TooManyRequests(AppError):
    status, title, slug = 429, "Too many requests", "rate-limited"


class ServiceUnavailable(AppError):
    status, title, slug = 503, "Service unavailable", "unavailable"
