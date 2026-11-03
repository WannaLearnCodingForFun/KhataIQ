"""Helpers to drive the pipeline in-process in integration tests."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

import khataiq.pipeline.stages  # noqa: F401  (registers the stages)
from khataiq.models.enums import UserRole
from khataiq.pipeline.outbox import pipeline_publisher, relay_once
from khataiq.pipeline.parsers.demo_csv import render_demo_csv
from khataiq.pipeline.runner import InlineDispatcher, Outcome, StageJob
from khataiq.principal import Principal
from khataiq.services.uploads import create_upload
from tests.integration import factories as f


@dataclass
class Shop:
    owner: Principal
    business_id: int
    account_id: int
    account_ids: tuple[int, ...] = ()


def make_shop(s: Session, masks: tuple[str, ...] = ("1234",)) -> Shop:
    o = f.org(s)
    u = f.user(s, o.id, UserRole.OWNER)
    b = f.business(s, o.id, u.id)
    accounts = [f.account(s, o.id, b.id, mask=m) for m in masks]
    s.commit()
    return Shop(Principal(u.id, o.id, UserRole.OWNER), b.id, accounts[0].id,
                tuple(a.id for a in accounts))


def upload(shop: Shop, data: bytes, account_id: int | None = None) -> int:
    result = create_upload(shop.owner, account_id or shop.account_id, str(uuid.uuid4()), data)
    return result.upload.id


def run_pipeline(dispatcher: InlineDispatcher | None = None) -> list[tuple[StageJob, Outcome]]:
    dispatcher = dispatcher or InlineDispatcher()
    relay_once(pipeline_publisher(dispatcher))
    return dispatcher.drain()


def daily_rows(start: date, days: int, seed: int = 0) -> list[tuple[date, str, int, int]]:
    """A plausible run of sales credits and supplier debits, one or two per day."""
    rows = []
    for d in range(days):
        day = start + timedelta(days=d)
        rows.append((day, f"UPI/41230{seed}{d:06d}/CUSTOMER {d}/c{d}@okaxis", 0,
                     100_000 + d * 1_000))
        if d % 3 == 0:
            rows.append((day, f"NEFT DR-SBIN0004321-SUPPLIER {d}", 60_000 + d * 500, 0))
    return rows


def statement(start: date, days: int, opening: int = 5_000_000) -> bytes:
    return render_demo_csv(opening, daily_rows(start, days))


DATA_TABLES = ["uploads", "transactions", "upload_rows", "flags", "flag_evidence"]


def state_digest(s: Session) -> dict[str, tuple[int, str]]:
    """(row count, hash of every row's content) for each ledger table. Timestamps that a
    re-run legitimately doesn't touch are included, so any rewrite shows up."""
    digest = {}
    for table in DATA_TABLES:
        rows = s.execute(text(f"SELECT t::text FROM {table} t ORDER BY 1")).scalars().all()
        digest[table] = (len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest())
    return digest
