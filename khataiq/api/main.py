"""FastAPI application. Run with: uvicorn khataiq.api.main:app --reload"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import khataiq.pipeline.stages  # noqa: F401  (registers pipeline stages for admin retries)
from khataiq.api import problems
from khataiq.api.middleware import BodySizeLimitMiddleware, MetricsMiddleware, RequestIdMiddleware
from khataiq.api.routes import (
    admin,
    assessments,
    auth,
    businesses,
    copilot,
    evidence,
    ledger,
    ops,
    uploads,
)
from khataiq.config import get_settings
from khataiq.observability import configure_logging, configure_tracing


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    configure_tracing("khataiq-api")
    app = FastAPI(title="KhataIQ", version="0.1.0",
                  description="Cash-flow evidence platform for small-business lending.")
    problems.install(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # the refresh cookie
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    # Room for multipart framing around a maximum-size file.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes + 64 * 1024)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIdMiddleware)  # added last = outermost, so 413s carry an id too

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
    app.include_router(ops.router)

    app.include_router(auth.router)
    app.include_router(businesses.router)
    app.include_router(uploads.router)
    app.include_router(ledger.router)
    app.include_router(evidence.router)
    app.include_router(assessments.router)
    app.include_router(copilot.router)
    app.include_router(admin.router)
    return app


app = create_app()
