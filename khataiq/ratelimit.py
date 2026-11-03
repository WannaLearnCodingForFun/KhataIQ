"""Token-bucket rate limiting in Redis.

Each (bucket, identity) pair is a Redis hash {tokens, ts}. A Lua script refills it by elapsed
time, spends one token if it can and reports how long until the next token. Running it as one
script makes check-and-spend atomic across API processes, and using Redis's own clock (TIME)
keeps API servers with skewed clocks consistent.

If Redis is unreachable the limiter fails open (allows the request) and logs a warning:
rate limiting protects capacity, and an outage of the limiter shouldn't become an outage of
the API.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import lru_cache

import redis

from khataiq.config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bucket:
    name: str
    capacity: int
    period_seconds: int


def general_bucket() -> Bucket:
    return Bucket("general", get_settings().rate_limit_general_per_minute, 60)


def uploads_bucket() -> Bucket:
    return Bucket("uploads", get_settings().rate_limit_uploads_per_minute, 60)


def copilot_bucket() -> Bucket:
    return Bucket("copilot", get_settings().rate_limit_copilot_per_hour, 3600)


_TOKEN_BUCKET = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])          -- tokens per second
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1]) or capacity
local ts = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + (now - ts) * rate)
local allowed = 0
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  wait = (1 - tokens) / rate
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(capacity / rate) + 1)
return {allowed, tostring(wait)}
"""


class RateLimiter:
    def __init__(self, client: redis.Redis) -> None:
        self.client = client
        self.script = client.register_script(_TOKEN_BUCKET)

    def hit(self, bucket: Bucket, identity: str) -> tuple[bool, int]:
        """Spend one token. Returns (allowed, seconds to wait before retrying)."""
        rate = bucket.capacity / bucket.period_seconds
        key = f"ratelimit:{bucket.name}:{identity}"
        try:
            allowed, wait = self.script(keys=[key], args=[bucket.capacity, rate])
        except redis.RedisError:
            log.warning("rate limiter unavailable; allowing request", exc_info=True)
            return True, 0
        return bool(int(allowed)), max(1, math.ceil(float(wait))) if not int(allowed) else 0


@lru_cache
def get_limiter() -> RateLimiter:
    client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5,
                                  socket_connect_timeout=0.5)
    return RateLimiter(client)
