"""Admin operations: the dead-letter queue and the audit log."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, aliased

from khataiq import audit
from khataiq.errors import Conflict, NotFound
from khataiq.models import Account, AuditLog, PipelineRun, Upload
from khataiq.models.enums import PipelineStatus
from khataiq.pipeline.runner import STATUS_BEFORE, StageJob, set_status
from khataiq.principal import Principal


@dataclass(frozen=True)
class DeadLetter:
    run_id: int
    upload_id: int
    business_id: int
    stage: str
    attempt_no: int
    error: str | None
    finished_at: datetime | None


def _is_latest_attempt() -> ColumnElement[bool]:
    later = aliased(PipelineRun)
    return ~select(later.id).where(
        later.upload_id == PipelineRun.upload_id, later.stage == PipelineRun.stage,
        later.attempt_no > PipelineRun.attempt_no).exists()


def list_dead_letters(s: Session, after_id: int | None, limit: int) -> list[DeadLetter]:
    """Dead runs that haven't been retried since (a retry adds a later attempt)."""
    query = (select(PipelineRun, Account.business_id)
             .join(Upload, Upload.id == PipelineRun.upload_id)
             .join(Account, Account.id == Upload.account_id)
             .where(PipelineRun.status == PipelineStatus.DEAD, _is_latest_attempt())
             .order_by(PipelineRun.id.desc()).limit(limit + 1))
    if after_id is not None:
        query = query.where(PipelineRun.id < after_id)
    return [DeadLetter(run.id, run.upload_id, business_id, run.stage, run.attempt_no,
                       run.error, run.finished_at)
            for run, business_id in s.execute(query).all()]


def prepare_retry(s: Session, actor: Principal, run_id: int) -> StageJob:
    """Reset the upload and return the job to dispatch. The caller dispatches it after
    commit, so the worker never sees the upload before the reset is visible."""
    run = s.get(PipelineRun, run_id)
    if run is None:
        raise NotFound(f"pipeline run {run_id} not found")
    newer = s.scalar(select(func.max(PipelineRun.attempt_no)).where(
        PipelineRun.upload_id == run.upload_id, PipelineRun.stage == run.stage))
    if run.status != PipelineStatus.DEAD or newer != run.attempt_no:
        raise Conflict("only the latest attempt of a dead stage can be retried")
    upload = s.get(Upload, run.upload_id)
    assert upload is not None
    set_status(s, upload, STATUS_BEFORE[run.stage], None)
    audit.record(s, org_id=actor.org_id, actor_id=actor.id, action="pipeline.retry",
                 entity_type="pipeline_run", entity_id=run.id,
                 after={"stage": run.stage, "next_attempt": run.attempt_no + 1})
    return StageJob(run.upload_id, run.org_id, run.stage, run.attempt_no + 1)


def search_audit(s: Session, *, entity_type: str | None, entity_id: int | None,
                 actor_id: int | None, since: datetime | None, until: datetime | None,
                 after_id: int | None, limit: int) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    if entity_type is not None:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    if actor_id is not None:
        query = query.where(AuditLog.actor_id == actor_id)
    if since is not None:
        query = query.where(AuditLog.at >= since)
    if until is not None:
        query = query.where(AuditLog.at < until)
    if after_id is not None:
        query = query.where(AuditLog.id < after_id)
    return list(s.scalars(query))
