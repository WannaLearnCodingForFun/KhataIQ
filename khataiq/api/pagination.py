"""Opaque cursor pagination: the cursor is the last id seen, base64-encoded so clients treat
it as a token rather than arithmetic. Lists are ordered by id descending (newest first)."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from typing import Generic, TypeVar

from pydantic import BaseModel

from khataiq.errors import BadRequest

T = TypeVar("T")
MAX_LIMIT = 100
DEFAULT_LIMIT = 50


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None


def encode_cursor(last_id: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"id": last_id}).encode()).decode()


def decode_cursor(cursor: str | None) -> int | None:
    if not cursor:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode()))["id"]
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise BadRequest("invalid cursor") from exc
    if not isinstance(value, int):
        raise BadRequest("invalid cursor")
    return value


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if not 1 <= limit <= MAX_LIMIT:
        raise BadRequest(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def build_page(
    rows: Sequence[T], limit: int, key: Callable[[T], int]
) -> tuple[list[T], str | None]:
    """rows were fetched with limit + 1; the extra row only tells us another page exists."""
    items = list(rows[:limit])
    next_cursor = encode_cursor(key(items[-1])) if len(rows) > limit else None
    return items, next_cursor
