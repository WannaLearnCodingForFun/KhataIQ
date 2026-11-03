"""ASGI middleware: request ids, request metrics and a request-body size cap."""

from __future__ import annotations

import json
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from khataiq.observability import HTTP_LATENCY
from khataiq.request_context import request_id_var

_VALID_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class RequestIdMiddleware:
    """Take X-Request-ID from the client if it's well formed, else make one; expose it to the
    rest of the request through a context variable and echo it on the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class BodySizeLimitMiddleware:
    """Reject bodies over max_bytes before they are parsed or spooled to disk.

    FastAPI parses a multipart body before any route code or dependency runs, so a size check
    inside the route would only fire after a huge upload had been read. This checks
    Content-Length up front and also counts bytes as they stream in (Content-Length can be
    absent or wrong).
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(scope, send)
            return

        received = 0
        too_large = False

        async def counting_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, counting_receive, send)
        except _BodyTooLarge:
            if too_large:
                await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        body = json.dumps({
            "type": "https://khataiq.dev/problems/payload-too-large",
            "title": "Payload too large", "status": 413,
            "detail": f"request body is larger than {self.max_bytes} bytes",
            "instance": scope.get("path"), "request_id": request_id_var.get(),
        }).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/problem+json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass


class MetricsMiddleware:
    """Request latency by method, route *template* (/v1/uploads/{upload_id}, never the raw path,
    which would create one time series per id) and status."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", "unmatched")
            if template != "/metrics":
                HTTP_LATENCY.labels(scope["method"], template, str(status)).observe(
                    time.perf_counter() - started)
