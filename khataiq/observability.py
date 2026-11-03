"""Logs, metrics and traces.

Logs: structlog, one JSON object per line, with request_id on every line (it travels from the
API through the outbox payload into the worker). A masking processor runs last before
rendering, so nothing can log a secret by accident:
  * values under sensitive keys (passwords, tokens, narrations, file contents...) are replaced;
  * any run of 8-18 digits in any string is masked to its last 4 (account numbers, cards).

Metrics: Prometheus counters and histograms, served at /metrics by the API and on
KHATAIQ_METRICS_PORT by each worker.

Traces: OpenTelemetry spans for API requests and pipeline stages, exported over OTLP when
OTEL_EXPORTER_OTLP_ENDPOINT is set (and not at all otherwise).
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

import structlog
from opentelemetry import trace
from prometheus_client import Counter, Gauge, Histogram

from khataiq.request_context import current_request_id

# ------------------------------------------------------------------ masking

SENSITIVE_KEYS = frozenset({
    "password", "password_hash", "token", "access_token", "refresh_token", "authorization",
    "cookie", "set-cookie", "narration", "narration_norm", "account_number", "content", "file",
    "body", "api_key", "secret", "jwt_secret",
})
_LONG_DIGITS = re.compile(r"(?<!\d)\d{4,14}(\d{4})(?!\d)")
REDACTED = "[redacted]"


def mask_text(text: str) -> str:
    """Mask every run of 8-18 digits to its last 4: '50100123456789' -> 'XXXX6789'."""
    return _LONG_DIGITS.sub(lambda m: "XXXX" + m.group(1), text)


def _mask(value: Any) -> Any:
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: REDACTED if str(k).lower() in SENSITIVE_KEYS else _mask(v)
                for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_mask(v) for v in value]
    return value


def mask_processor(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        event[key] = REDACTED if key.lower() in SENSITIVE_KEYS else _mask(event[key])
    return event


def _add_request_id(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    request_id = current_request_id()
    if request_id and "request_id" not in event:
        event["request_id"] = request_id
    span = trace.get_current_span().get_span_context()
    if span.is_valid:
        event.setdefault("trace_id", format(span.trace_id, "032x"))
    return event


def configure_logging(level: str | None = None) -> None:
    """Route stdlib logging and structlog through one JSON renderer with masking."""
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_request_id,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.format_exc_info,
        mask_processor,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer()],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level or os.environ.get("KHATAIQ_LOG_LEVEL", "INFO"))


# ------------------------------------------------------------------ metrics

HTTP_LATENCY = Histogram("khataiq_http_request_seconds", "API request latency",
                         ["method", "route", "status"],
                         buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
STAGE_DURATION = Histogram("khataiq_stage_seconds", "Pipeline stage duration",
                           ["stage", "outcome"],
                           buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60))
STAGE_FAILURES = Counter("khataiq_stage_failures_total", "Failed stage attempts",
                         ["stage", "kind"])
QUEUE_DEPTH = Gauge("khataiq_outbox_unpublished", "Outbox rows not yet published")
DEAD_LETTERS = Gauge("khataiq_dead_letters", "Pipeline runs in the dead state")


# ------------------------------------------------------------------ traces

_tracing_configured = False


def configure_tracing(service_name: str) -> None:
    """Export spans over OTLP/HTTP if OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise spans are
    created (cheap no-ops) but go nowhere."""
    global _tracing_configured
    if _tracing_configured or not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracing_configured = True


tracer = trace.get_tracer("khataiq")


@contextmanager
def stage_span(stage: str, upload_id: int, attempt: int) -> Iterator[None]:
    with tracer.start_as_current_span(f"stage.{stage}") as span:
        span.set_attribute("khataiq.upload_id", upload_id)
        span.set_attribute("khataiq.attempt", attempt)
        request_id = current_request_id()
        if request_id:
            span.set_attribute("khataiq.request_id", request_id)
        yield
