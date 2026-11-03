"""Celery wiring. Start a worker with:

    celery -A khataiq.pipeline.celery_app worker -l info
    celery -A khataiq.pipeline.celery_app beat -l info     # runs the outbox relay every 2 s

Reliability settings:
  task_acks_late            ack after the task finishes, so a worker crash redelivers it
  task_reject_on_worker_lost  ...including when the worker process is killed
  worker_prefetch_multiplier=1  a worker holds one message at a time, not a batch it might lose
These make delivery at-least-once; the stages are idempotent, so a redelivery is harmless.
"""

from __future__ import annotations

from typing import Any

from celery import Celery

import khataiq.pipeline.stages  # noqa: F401  (registers the stages)
from khataiq.config import get_settings
from khataiq.pipeline.outbox import pipeline_publisher, relay_once
from khataiq.pipeline.runner import Outcome, StageJob, run_stage

celery_app = Celery("khataiq", broker=get_settings().redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="pipeline",
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={"outbox-relay": {"task": "khataiq.relay_outbox", "schedule": 2.0}},
)


class CeleryDispatcher:
    def dispatch(self, job: StageJob, delay_seconds: int = 0) -> None:
        run_stage_task.apply_async(kwargs=job.to_kwargs(), countdown=delay_seconds or None)


@celery_app.task(name="khataiq.run_stage")
def run_stage_task(**kwargs: Any) -> str:
    outcome: Outcome = run_stage(StageJob.from_kwargs(kwargs), CeleryDispatcher())
    return outcome.value


@celery_app.task(name="khataiq.relay_outbox")
def relay_outbox_task() -> int:
    return relay_once(pipeline_publisher(CeleryDispatcher()))
