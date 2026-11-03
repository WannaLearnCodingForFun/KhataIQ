"""Operational endpoints: liveness, readiness, Prometheus metrics. Not versioned.

/healthz  the process is up; touches nothing (a DB outage must not get healthy API processes
          restarted in a loop)
/readyz   the database and Redis answer; a load balancer stops routing here when they don't
/metrics  Prometheus text format; expose it only on the internal network (see docs/deploy.md)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from khataiq.db import get_sessionmaker
from khataiq.observability import DEAD_LETTERS, QUEUE_DEPTH
from khataiq.ratelimit import get_limiter

router = APIRouter(tags=["ops"])
log = logging.getLogger(__name__)


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        with get_sessionmaker()() as s:
            s.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        log.warning("readiness: database unavailable", exc_info=True)
        checks["database"] = "unavailable"
    try:
        get_limiter().client.ping()
        checks["redis"] = "ok"
    except Exception:
        log.warning("readiness: redis unavailable", exc_info=True)
        checks["redis"] = "unavailable"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ready" if ready else "not ready", "checks": checks},
                        status_code=200 if ready else 503)


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    try:
        with get_sessionmaker()() as s:
            row = s.execute(text("SELECT unpublished_outbox, dead_runs FROM ops_counts()")).one()
        QUEUE_DEPTH.set(row.unpublished_outbox)
        DEAD_LETTERS.set(row.dead_runs)
    except Exception:
        log.warning("metrics: could not read queue counts", exc_info=True)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
