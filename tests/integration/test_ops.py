"""M11.1: readiness and Prometheus metrics."""

from khataiq.observability import QUEUE_DEPTH  # noqa: F401  (registers the metrics)
from tests.integration.conftest import People, login


def test_readyz_checks_database_and_redis(api, redis_available):
    r = api.get("/readyz")
    if redis_available:
        assert r.status_code == 200 and r.json()["checks"] == {"database": "ok", "redis": "ok"}
    else:
        assert r.status_code == 503 and r.json()["checks"]["redis"] == "unavailable"


def test_metrics_expose_latency_by_route_template_and_queue_counts(api, people: People):
    headers = login(api, people.officer)
    api.get("/v1/me", headers=headers)
    api.get("/v1/businesses/12345", headers=headers)
    text = api.get("/metrics").text
    assert 'route="/v1/me"' in text
    assert 'route="/v1/businesses/{business_id}"' in text and "/v1/businesses/12345" not in text
    assert "khataiq_outbox_unpublished" in text and "khataiq_dead_letters" in text
    assert "khataiq_stage_seconds" in text


def test_healthz_needs_nothing(api):
    assert api.get("/healthz").json() == {"status": "ok"}
