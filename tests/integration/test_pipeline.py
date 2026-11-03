"""M4.1-M4.3: outbox relay, stage framework, parse -> persist -> reconcile."""

import threading
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from khataiq.models import AuditLog, Flag, FlagEvidence, Outbox, PipelineRun, Transaction, Upload
from khataiq.models.enums import FlagKind, PipelineStatus, UploadStatus
from khataiq.pipeline import runner
from khataiq.pipeline.outbox import OutboxMessage, relay_once
from khataiq.pipeline.parsers.demo_csv import render_demo_csv
from khataiq.pipeline.runner import InlineDispatcher, Outcome, StageJob
from tests.integration.pipeline_helpers import (
    daily_rows,
    make_shop,
    run_pipeline,
    state_digest,
    statement,
    upload,
)

pytestmark = pytest.mark.usefixtures("migrated", "local_store")

OCT = date(2026, 10, 1)


# ------------------------------------------------------------------ outbox relay (M4.1)

def test_relay_publishes_once_and_marks_published(owner_session: Session):
    shop = make_shop(owner_session)
    upload(shop, statement(OCT, 3))
    seen: list[OutboxMessage] = []
    assert relay_once(seen.append) == 1
    assert relay_once(seen.append) == 0
    assert len(seen) == 1 and seen[0].payload["upload_id"]
    assert owner_session.scalar(select(Outbox.published_at)) is not None


def test_failed_publish_leaves_rows_for_the_next_tick(owner_session: Session):
    shop = make_shop(owner_session)
    upload(shop, statement(OCT, 3))

    def broken(message: OutboxMessage) -> None:
        raise ConnectionError("broker down")

    with pytest.raises(ConnectionError):
        relay_once(broken)
    assert relay_once(lambda m: None) == 1


def test_two_relays_at_once_publish_each_row_exactly_once(owner_session: Session):
    shop = make_shop(owner_session)
    for i in range(10):
        upload(shop, statement(OCT, 2 + i))
    published: list[int] = []
    lock = threading.Lock()
    a_claimed, b_done = threading.Event(), threading.Event()

    def slow_publish(message: OutboxMessage) -> None:
        a_claimed.set()
        b_done.wait(timeout=10)  # hold A's row locks while B runs
        with lock:
            published.append(message.id)

    def fast_publish(message: OutboxMessage) -> None:
        with lock:
            published.append(message.id)

    a = threading.Thread(target=relay_once, args=(slow_publish, 4))
    a.start()
    assert a_claimed.wait(timeout=10)
    b_count = relay_once(fast_publish, 4)  # must skip A's 4 locked rows, take the next 4
    b_done.set()
    a.join(timeout=10)
    while relay_once(fast_publish, 4):
        pass
    assert b_count == 4
    assert sorted(published) == sorted(set(published)) and len(published) == 10


# ------------------------------------------------------------------ whole chain (M4.2/M4.3)

def test_clean_statement_runs_every_stage(owner_session: Session):
    shop = make_shop(owner_session)
    upload_id = upload(shop, statement(OCT, 5))
    outcomes = run_pipeline()
    assert [(j.stage, o) for j, o in outcomes] == [
        (stage, Outcome.SUCCEEDED) for stage in runner.PIPELINE]
    up = owner_session.get(Upload, upload_id)
    assert up.status == UploadStatus.PROCESSED
    assert (up.parser_version, up.period_start, up.period_end) == ("demo-csv/1", OCT,
                                                                    date(2026, 10, 5))
    assert owner_session.scalar(select(func.count()).select_from(Transaction)) == 7
    t = owner_session.scalars(select(Transaction).order_by(Transaction.source_line)).first()
    assert (t.channel, t.counterparty_key, t.utr) == ("upi", "vpa:c0@okaxis", "412300000000")
    statuses = owner_session.scalars(select(AuditLog.after["status"].astext).where(
        AuditLog.action == "upload.status").order_by(AuditLog.id)).all()
    assert statuses == ["parsing", "parsed", "reconciled", "processed"]


def test_running_the_chain_twice_leaves_identical_state(owner_session: Session):
    shop = make_shop(owner_session)
    upload_id = upload(shop, statement(OCT, 10))
    run_pipeline()
    before = state_digest(owner_session)

    # A duplicate outbox delivery: every stage sees it already succeeded and skips.
    again = InlineDispatcher()
    again.dispatch(StageJob(upload_id, shop.owner.org_id, runner.PIPELINE[0]))
    assert {o for _, o in again.drain()} == {Outcome.SKIPPED}
    assert state_digest(owner_session) == before

    # Force every stage to really execute again (as if its success record were lost).
    owner_session.execute(text("DELETE FROM pipeline_runs"))
    owner_session.commit()
    forced = InlineDispatcher()
    forced.dispatch(StageJob(upload_id, shop.owner.org_id, runner.PIPELINE[0]))
    assert {o for _, o in forced.drain()} == {Outcome.SUCCEEDED}
    assert state_digest(owner_session) == before


def test_unbalanced_statement_stops_at_reconcile(owner_session: Session):
    shop = make_shop(owner_session)
    good = statement(OCT, 6).decode().splitlines()
    # Line 5 is the third transaction; change its printed balance by one rupee.
    cells = good[4].rsplit(",", 1)
    rupees, paise = cells[1].split(".")
    good[4] = f"{cells[0]},{int(rupees) + 1}.{paise}"
    upload_id = upload(shop, ("\n".join(good) + "\n").encode())

    outcomes = run_pipeline()
    assert [(j.stage, o) for j, o in outcomes] == [
        ("parse", Outcome.SUCCEEDED), ("persist", Outcome.SUCCEEDED),
        ("reconcile", Outcome.STOPPED)]
    up = owner_session.get(Upload, upload_id)
    assert up.status == UploadStatus.NEEDS_REVIEW
    assert (up.recon_reason, up.recon_break_line) == ("running_balance", 5)
    assert up.recon_actual_paise - up.recon_expected_paise == 100

    flag = owner_session.scalars(select(Flag)).one()
    assert flag.kind == FlagKind.NEEDS_REVIEW_UPLOAD and flag.total_paise == 100
    evidence_txn = owner_session.scalar(select(Transaction).join(
        FlagEvidence, FlagEvidence.txn_id == Transaction.id))
    assert evidence_txn.source_line == 5
    later = runner.PIPELINE[runner.PIPELINE.index("reconcile") + 1:]
    assert owner_session.scalar(select(func.count()).select_from(PipelineRun).where(
        PipelineRun.stage.in_(later))) == 0

    # A redelivered job must not push past the closed gate either.
    again = InlineDispatcher()
    again.dispatch(StageJob(upload_id, shop.owner.org_id, "reconcile"))
    again.drain()
    assert not again.queue and owner_session.scalar(select(func.count()).select_from(Flag)) == 1


def test_overlapping_statements_add_no_duplicate_transactions(owner_session: Session):
    shop = make_shop(owner_session)
    rows = daily_rows(OCT, 46)  # 1 Oct .. 15 Nov
    october = [r for r in rows if r[0].month == 10]
    opening = 5_000_000
    first = render_demo_csv(opening, october)
    # The second statement starts on 15 Oct, opening with the balance before that day.
    before_15th = [r for r in october if r[0].day < 15]
    opening_15th = opening + sum(c - d for _, _, d, c in before_15th)
    second = render_demo_csv(opening_15th, [r for r in rows if r[0] >= date(2026, 10, 15)])

    a, b = upload(shop, first), upload(shop, second)
    run_pipeline()
    assert owner_session.scalar(select(func.count()).select_from(Transaction)) == len(rows)
    for upload_id in (a, b):
        assert owner_session.get(Upload, upload_id).status == UploadStatus.PROCESSED
    dupes = owner_session.execute(text(
        "SELECT txn_date, amount_paise, narration FROM transactions "
        "GROUP BY 1, 2, 3 HAVING count(*) > 1")).all()
    assert dupes == []


# ------------------------------------------------------------------ failures and retries

def test_parse_error_fails_the_upload_without_retrying(owner_session: Session):
    shop = make_shop(owner_session)
    bad = statement(OCT, 3).replace(b"02/10/2026", b"31/02/2026", 1)
    upload_id = upload(shop, bad)
    dispatcher = InlineDispatcher()
    outcomes = run_pipeline(dispatcher)
    assert outcomes[-1][1] == Outcome.FAILED and len(outcomes) == 1
    up = owner_session.get(Upload, upload_id)
    assert up.status == UploadStatus.FAILED and "line 5" in up.error  # day 1 has two rows
    run = owner_session.scalars(select(PipelineRun)).one()
    assert run.status == PipelineStatus.FAILED


def test_transient_errors_are_retried_with_backoff(owner_session: Session, monkeypatch,
                                                   local_store):
    shop = make_shop(owner_session)
    upload_id = upload(shop, statement(OCT, 3))
    real_get, failures = local_store.get_object, iter([True, True])

    def flaky(key: str) -> bytes:
        if next(failures, False):
            raise ConnectionError("storage timeout")
        return real_get(key)

    monkeypatch.setattr(local_store, "get_object", flaky)
    dispatcher = InlineDispatcher()
    run_pipeline(dispatcher)
    assert owner_session.get(Upload, upload_id).status == UploadStatus.PROCESSED
    parse_runs = owner_session.scalars(select(PipelineRun).where(
        PipelineRun.stage == "parse").order_by(PipelineRun.attempt_no)).all()
    assert [r.status for r in parse_runs] == [PipelineStatus.FAILED, PipelineStatus.FAILED,
                                              PipelineStatus.SUCCEEDED]
    retry_delays = [delay for job, delay in dispatcher.history if job.attempt > 1]
    assert retry_delays == [2, 4]


def test_fifth_failure_is_dead_and_fails_the_upload(owner_session: Session, monkeypatch,
                                                    local_store):
    shop = make_shop(owner_session)
    upload_id = upload(shop, statement(OCT, 3))

    def down(key: str) -> bytes:
        raise ConnectionError("storage down")

    monkeypatch.setattr(local_store, "get_object", down)
    dispatcher = InlineDispatcher()
    outcomes = run_pipeline(dispatcher)
    assert [o for _, o in outcomes] == [Outcome.RETRYING] * 4 + [Outcome.DEAD]
    assert [d for _, d in dispatcher.history][1:] == [2, 4, 8, 16]
    up = owner_session.get(Upload, upload_id)
    assert up.status == UploadStatus.FAILED and "storage down" in up.error
    assert owner_session.scalar(select(PipelineRun.status).where(
        PipelineRun.attempt_no == 5)) == PipelineStatus.DEAD
    assert owner_session.scalar(select(AuditLog.id).where(
        AuditLog.action == "pipeline.dead")) is not None


def test_redelivery_after_a_worker_crash_takes_the_attempt_over(owner_session: Session):
    """A worker claimed attempt 1 ('running') and died; the redelivered message must finish
    the stage instead of skipping it forever."""
    shop = make_shop(owner_session)
    upload_id = upload(shop, statement(OCT, 3))
    owner_session.add(PipelineRun(org_id=shop.owner.org_id, upload_id=upload_id, stage="parse",
                                  attempt_no=1, status=PipelineStatus.RUNNING))
    owner_session.commit()
    dispatcher = InlineDispatcher()
    dispatcher.dispatch(StageJob(upload_id, shop.owner.org_id, "parse"))
    assert {o for _, o in dispatcher.drain()} == {Outcome.SUCCEEDED}
    assert owner_session.get(Upload, upload_id).status == UploadStatus.PROCESSED
    assert owner_session.scalar(select(func.count()).select_from(PipelineRun).where(
        PipelineRun.stage == "parse")) == 1


def test_duplicate_of_a_finished_attempt_is_skipped(owner_session: Session):
    shop = make_shop(owner_session)
    upload_id = upload(shop, statement(OCT, 3))
    owner_session.add(PipelineRun(org_id=shop.owner.org_id, upload_id=upload_id, stage="parse",
                                  attempt_no=1, status=PipelineStatus.FAILED, error="x"))
    owner_session.commit()
    job = StageJob(upload_id, shop.owner.org_id, "parse")
    assert runner.run_stage(job, InlineDispatcher()) == Outcome.SKIPPED
