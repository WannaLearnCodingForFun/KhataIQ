"""M2.4: Redis token bucket, request ids, problem+json."""

import pytest

from tests.integration.conftest import People, login


def test_61st_request_in_a_minute_is_429_with_retry_after(api, people: People,
                                                          redis_available: bool):
    if not redis_available:
        pytest.skip("KHATAIQ_TEST_REDIS_URL is not set")
    headers = login(api, people.officer)  # login spends from the per-IP bucket, not this one
    statuses = [api.get("/v1/me", headers=headers).status_code for _ in range(61)]
    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429
    last = api.get("/v1/me", headers=headers)
    assert last.status_code == 429
    assert int(last.headers["retry-after"]) >= 1
    assert last.json()["type"].endswith("/rate-limited")


def test_limits_are_per_user(api, people: People, redis_available: bool):
    if not redis_available:
        pytest.skip("KHATAIQ_TEST_REDIS_URL is not set")
    busy, quiet = login(api, people.officer), login(api, people.admin)
    for _ in range(61):
        api.get("/v1/me", headers=busy)
    assert api.get("/v1/me", headers=quiet).status_code == 200


def test_limiter_fails_open_without_redis(api, people: People, monkeypatch):
    import redis

    from khataiq.ratelimit import RateLimiter, get_limiter
    get_limiter.cache_clear()
    monkeypatch.setattr("khataiq.api.deps.get_limiter",
                        lambda: RateLimiter(redis.Redis.from_url("redis://127.0.0.1:1/0",
                                                                 socket_connect_timeout=0.2)))
    assert api.get("/v1/me", headers=login(api, people.officer)).status_code == 200


def test_request_id_is_echoed_or_generated(api):
    given = api.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert given.headers["x-request-id"] == "abc-123"
    made = api.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert made.headers["x-request-id"] != "bad id with spaces"
    assert len(made.headers["x-request-id"]) == 32


def test_unknown_route_is_problem_json(api):
    r = api.get("/v1/nope")
    assert r.status_code == 404 and r.headers["content-type"] == "application/problem+json"
