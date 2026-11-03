"""Run one pipeline stage for one upload, record the attempt, and decide what happens next.

Broker-agnostic: what to run next is handed to a Dispatcher. Celery's dispatcher enqueues a
task (with a countdown for retries); InlineDispatcher keeps a queue in memory so tests and the
synthetic evaluation can run the whole pipeline in-process.

Guarantees:
  * Each attempt is a pipeline_runs row, UNIQUE(upload_id, stage, attempt_no). If that row
    already exists and is still 'running', the message is a redelivery after a worker died
    mid-stage (late acks) or a duplicate publish racing a live worker: either way it takes the
    attempt over. Work happens under a row lock on the upload, and the "already succeeded?"
    check is repeated under that lock, so two workers on one attempt run one after the other
    and the second finds nothing to do. A finished (failed/dead) attempt is never re-run by a
    duplicate message; only the retry or admin path creates a new attempt.
  * A stage's database effects and its 'succeeded' mark commit in one transaction.
  * A stage that already succeeded is skipped, but its successor is dispatched again. With
    late acks, a worker that dies after committing but before dispatching gets its message
    redelivered, and this is what keeps the chain moving. The successor skips in turn if it
    already ran, so duplicates fade out at the end of the chain.
  * PermanentStageError (bad data, e.g. a ParseError) fails the upload at once.
    Anything else is treated as transient: retried after 2, 4, 8, 16 s; the 5th failure marks
    the run dead and the upload failed, and it appears in the admin dead-letter list.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from khataiq import audit
from khataiq.db import tenant_session
from khataiq.models import PipelineRun, Upload
from khataiq.models.enums import PipelineStatus, UploadStatus
from khataiq.observability import STAGE_DURATION, STAGE_FAILURES, stage_span
from khataiq.request_context import request_id_var

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
MAX_ERROR_CHARS = 500


def retry_delay(failed_attempt: int) -> int:
    """Seconds to wait after attempt n fails: 2, 4, 8, 16 (and 32 if MAX_ATTEMPTS grows)."""
    return int(2**failed_attempt)


class PermanentStageError(Exception):
    """The input can never succeed (e.g. the file doesn't parse). Don't retry."""


class StageResult(StrEnum):
    CONTINUE = "continue"
    STOP = "stop"  # e.g. reconciliation failed: the gate is closed, nothing after runs


StageFn = Callable[[Session, Upload], StageResult]


@dataclass(frozen=True)
class StageJob:
    upload_id: int
    org_id: int
    stage: str
    attempt: int = 1
    request_id: str | None = None

    def to_kwargs(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> StageJob:
        return cls(**kwargs)


class Dispatcher(Protocol):
    def dispatch(self, job: StageJob, delay_seconds: int = 0) -> None: ...


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    STOPPED = "stopped"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    FAILED = "failed"
    DEAD = "dead"


# The order stages run in. Each is registered by the module that implements it; PIPELINE is
# the registered subset, always in this order.
STAGE_ORDER = ["parse", "persist", "reconcile", "classify", "evidence", "metrics"]
PIPELINE: list[str] = []
STAGE_FUNCTIONS: dict[str, StageFn] = {}
# Upload status to fall back to when an admin retries a stage that died.
STATUS_BEFORE: dict[str, UploadStatus] = {}


def register_stage(name: str, fn: StageFn, status_before: UploadStatus) -> None:
    if name not in STAGE_ORDER:
        raise ValueError(f"unknown stage {name!r}")
    if name not in PIPELINE:
        PIPELINE.append(name)
        PIPELINE.sort(key=STAGE_ORDER.index)
    STAGE_FUNCTIONS[name] = fn
    STATUS_BEFORE[name] = status_before


def next_stage(stage: str) -> str | None:
    i = PIPELINE.index(stage)
    return PIPELINE[i + 1] if i + 1 < len(PIPELINE) else None


def _now() -> datetime:
    return datetime.now(UTC)


def set_status(s: Session, upload: Upload, status: UploadStatus, error: str | None = None) -> None:
    """Change an upload's status and audit the transition (actor None = the system)."""
    if upload.status == status and upload.error == error:
        return
    before = {"status": upload.status, "error": upload.error}
    upload.status = status
    upload.error = error
    audit.record(s, org_id=upload.org_id, actor_id=None, action="upload.status",
                 entity_type="upload", entity_id=upload.id, before=before,
                 after={"status": status, "error": error})


def run_stage(job: StageJob, dispatcher: Dispatcher) -> Outcome:
    token = request_id_var.set(job.request_id)
    started = time.perf_counter()
    outcome = Outcome.FAILED
    try:
        with stage_span(job.stage, job.upload_id, job.attempt):
            outcome = _run(job, dispatcher)
        return outcome
    finally:
        STAGE_DURATION.labels(job.stage, outcome.value).observe(time.perf_counter() - started)
        if outcome in (Outcome.RETRYING, Outcome.FAILED, Outcome.DEAD):
            STAGE_FAILURES.labels(job.stage, outcome.value).inc()
        request_id_var.reset(token)


def _run(job: StageJob, dispatcher: Dispatcher) -> Outcome:
    stage_fn = STAGE_FUNCTIONS[job.stage]

    # 1. Claim this attempt (its own short transaction, so 'running' is visible while we work).
    with tenant_session(job.org_id) as s:
        upload = s.get(Upload, job.upload_id)
        if upload is None:
            log.warning("upload vanished", extra={"upload_id": job.upload_id})
            return Outcome.SKIPPED
        if _already_succeeded(s, job):
            skipped_status = upload.status
            run_id = None
        else:
            existing = _attempt(s, job)
            if existing is None:
                run = PipelineRun(org_id=job.org_id, upload_id=job.upload_id, stage=job.stage,
                                  attempt_no=job.attempt, status=PipelineStatus.RUNNING,
                                  started_at=_now())
                try:
                    with s.begin_nested():
                        s.add(run)
                        s.flush()
                    existing = run
                except IntegrityError:
                    existing = _attempt(s, job)  # inserted by a concurrent delivery
            assert existing is not None
            if existing.status != PipelineStatus.RUNNING:
                return Outcome.SKIPPED  # this attempt already finished; never re-run it
            run_id = existing.id
            if job.stage == PIPELINE[0]:
                set_status(s, upload, UploadStatus.PARSING)

    if run_id is None:
        if skipped_status not in (UploadStatus.NEEDS_REVIEW, UploadStatus.FAILED):
            _dispatch_next(job, dispatcher)
        return Outcome.SKIPPED

    # 2. Do the work; the stage's effects and the success mark commit together.
    try:
        with tenant_session(job.org_id) as s:
            upload = s.get(Upload, job.upload_id, with_for_update=True)
            assert upload is not None
            if _already_succeeded(s, job):
                return Outcome.SKIPPED  # a concurrent worker finished it while we waited
            result = stage_fn(s, upload)
            _finish(s, run_id, PipelineStatus.SUCCEEDED, None)
            if result == StageResult.CONTINUE and next_stage(job.stage) is None:
                set_status(s, upload, UploadStatus.PROCESSED)
    except PermanentStageError as exc:
        _record_failure(job, run_id, str(exc), PipelineStatus.FAILED)
        return Outcome.FAILED
    except Exception as exc:  # transient until proven otherwise
        log.exception("stage failed", extra={"upload_id": job.upload_id, "stage": job.stage,
                                             "attempt": job.attempt})
        message = f"{type(exc).__name__}: {exc}"
        if job.attempt >= MAX_ATTEMPTS:
            _record_failure(job, run_id, message, PipelineStatus.DEAD)
            return Outcome.DEAD
        with tenant_session(job.org_id) as s:
            _finish(s, run_id, PipelineStatus.FAILED, message)
        dispatcher.dispatch(replace(job, attempt=job.attempt + 1), retry_delay(job.attempt))
        return Outcome.RETRYING

    if result == StageResult.STOP:
        return Outcome.STOPPED
    _dispatch_next(job, dispatcher)
    return Outcome.SUCCEEDED


def _already_succeeded(s: Session, job: StageJob) -> bool:
    return s.scalar(select(PipelineRun.id).where(
        PipelineRun.upload_id == job.upload_id, PipelineRun.stage == job.stage,
        PipelineRun.status == PipelineStatus.SUCCEEDED).limit(1)) is not None


def _attempt(s: Session, job: StageJob) -> PipelineRun | None:
    return s.scalar(select(PipelineRun).where(
        PipelineRun.upload_id == job.upload_id, PipelineRun.stage == job.stage,
        PipelineRun.attempt_no == job.attempt))


def _dispatch_next(job: StageJob, dispatcher: Dispatcher) -> None:
    following = next_stage(job.stage)
    if following is not None:
        dispatcher.dispatch(StageJob(job.upload_id, job.org_id, following, 1, job.request_id))


def _finish(s: Session, run_id: int, status: PipelineStatus, error: str | None) -> None:
    s.execute(update(PipelineRun).where(PipelineRun.id == run_id).values(
        status=status, error=error[:MAX_ERROR_CHARS] if error else None, finished_at=_now()))


def _record_failure(job: StageJob, run_id: int, message: str, status: PipelineStatus) -> None:
    with tenant_session(job.org_id) as s:
        _finish(s, run_id, status, message)
        upload = s.get(Upload, job.upload_id)
        assert upload is not None
        set_status(s, upload, UploadStatus.FAILED, f"{job.stage}: {message}"[:MAX_ERROR_CHARS])
        if status == PipelineStatus.DEAD:
            audit.record(s, org_id=job.org_id, actor_id=None, action="pipeline.dead",
                         entity_type="pipeline_run", entity_id=run_id,
                         after={"stage": job.stage, "attempt": job.attempt})


class InlineDispatcher:
    """Runs jobs in-process, in FIFO order, ignoring delays. For tests and offline evaluation."""

    def __init__(self) -> None:
        self.queue: deque[StageJob] = deque()
        self.history: list[tuple[StageJob, int]] = []

    def dispatch(self, job: StageJob, delay_seconds: int = 0) -> None:
        self.queue.append(job)
        self.history.append((job, delay_seconds))

    def drain(self, max_steps: int = 1000) -> list[tuple[StageJob, Outcome]]:
        done: list[tuple[StageJob, Outcome]] = []
        while self.queue and len(done) < max_steps:
            job = self.queue.popleft()
            done.append((job, run_stage(job, self)))
        return done
