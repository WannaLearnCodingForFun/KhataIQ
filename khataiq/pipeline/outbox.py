"""The outbox relay: move committed jobs from the outbox table to the broker.

One transaction per batch: claim rows (locked, SKIP LOCKED), publish each, mark them
published, commit. If publishing fails the transaction rolls back and the rows are picked up
again on the next tick. If the commit fails after publishing, the rows are published again
later: harmless, because every stage is idempotent. So delivery is at-least-once, never zero.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from khataiq.db import get_sessionmaker
from khataiq.pipeline.runner import PIPELINE, Dispatcher, StageJob


@dataclass(frozen=True)
class OutboxMessage:
    id: int
    org_id: int
    topic: str
    payload: dict[str, Any]


Publisher = Callable[[OutboxMessage], None]


def relay_once(publish: Publisher, batch_size: int = 100) -> int:
    """Publish up to batch_size unpublished messages. Returns how many were published."""
    with get_sessionmaker()() as s, s.begin():
        rows = s.execute(text("SELECT id, org_id, topic, payload FROM outbox_claim(:n)"),
                         {"n": batch_size}).all()
        for row in rows:
            publish(OutboxMessage(row.id, row.org_id, row.topic, row.payload))
        if rows:
            s.execute(text("SELECT outbox_mark_published(:ids)"), {"ids": [r.id for r in rows]})
    return len(rows)


def pipeline_publisher(dispatcher: Dispatcher) -> Publisher:
    """Turn 'pipeline.start' messages into the first stage job of that upload."""

    def publish(message: OutboxMessage) -> None:
        if message.topic != "pipeline.start":
            raise ValueError(f"unknown outbox topic {message.topic!r}")
        dispatcher.dispatch(StageJob(
            upload_id=int(message.payload["upload_id"]), org_id=message.org_id,
            stage=PIPELINE[0], request_id=message.payload.get("request_id")))

    return publish
