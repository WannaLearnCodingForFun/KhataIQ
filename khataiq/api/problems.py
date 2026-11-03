"""RFC 9457 problem+json responses for every error the API returns."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from khataiq.errors import AppError
from khataiq.request_context import current_request_id

log = logging.getLogger(__name__)
PROBLEM_BASE = "https://khataiq.dev/problems/"
MEDIA_TYPE = "application/problem+json"


def problem(request: Request, status: int, title: str, slug: str, detail: str | None = None,
            headers: dict[str, str] | None = None, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + slug,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "request_id": current_request_id(),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=MEDIA_TYPE, headers=headers)


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return problem(request, exc.status, exc.title, exc.slug, exc.detail, exc.headers,
                   **exc.extra)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Report where and what, never the submitted value (it may be a password or PII).
    errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    return problem(request, 422, "Validation failed", "validation", "request is invalid",
                   errors=errors)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    slug = {404: "not-found", 405: "method-not-allowed"}.get(exc.status_code, "http-error")
    return problem(request, exc.status_code, str(exc.detail), slug, None,
                   dict(exc.headers or {}))


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", extra={"request_id": current_request_id()})
    return problem(request, 500, "Internal server error", "internal")


def install(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
