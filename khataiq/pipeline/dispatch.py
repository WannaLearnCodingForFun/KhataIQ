"""How the API hands a pipeline job to the workers. A function so tests can override it."""

from __future__ import annotations

from khataiq.pipeline.runner import Dispatcher


def get_dispatcher() -> Dispatcher:
    from khataiq.pipeline.celery_app import CeleryDispatcher  # imports Celery only when needed

    return CeleryDispatcher()
