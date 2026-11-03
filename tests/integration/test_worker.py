"""M4.4: a real Celery worker, with Redis as the broker, processes an upload end to end.
Runs wherever KHATAIQ_TEST_REDIS_URL is set (always in CI)."""

import os
import subprocess
import sys
import time
from datetime import date

import pytest
from sqlalchemy.orm import Session

from khataiq.config import get_settings
from khataiq.models import Upload
from khataiq.models.enums import UploadStatus
from tests.integration.conftest import TEST_REDIS_URL
from tests.integration.pipeline_helpers import make_shop, statement, upload

pytestmark = pytest.mark.skipif(not TEST_REDIS_URL, reason="KHATAIQ_TEST_REDIS_URL is not set")


def test_worker_processes_an_upload_end_to_end(owner_session: Session, local_store, app_url,
                                               monkeypatch):
    import redis

    from khataiq.pipeline.celery_app import CeleryDispatcher, celery_app
    from khataiq.pipeline.outbox import pipeline_publisher, relay_once

    redis.Redis.from_url(TEST_REDIS_URL).flushdb()
    settings = get_settings()
    env = {**os.environ,
           "KHATAIQ_DATABASE_URL": app_url,
           "KHATAIQ_REDIS_URL": TEST_REDIS_URL,
           "KHATAIQ_STORAGE_BACKEND": "local",
           "KHATAIQ_LOCAL_STORAGE_DIR": settings.local_storage_dir}
    worker = subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "khataiq.pipeline.celery_app", "worker",
         "--pool=solo", "-Q", "pipeline", "-l", "warning", "--without-heartbeat",
         "--without-gossip", "--without-mingle"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    status = None
    try:
        shop = make_shop(owner_session)
        upload_id = upload(shop, statement(date(2026, 10, 1), 5))
        monkeypatch.setattr(celery_app.conf, "broker_url", TEST_REDIS_URL)
        assert relay_once(pipeline_publisher(CeleryDispatcher())) == 1

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            owner_session.expire_all()
            status = owner_session.get(Upload, upload_id).status
            if status in (UploadStatus.PROCESSED, UploadStatus.FAILED,
                          UploadStatus.NEEDS_REVIEW):
                break
            time.sleep(0.5)
        assert status == UploadStatus.PROCESSED
    finally:
        worker.terminate()
        try:
            output, _ = worker.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            output, _ = worker.communicate()
        if status != UploadStatus.PROCESSED:
            print(output.decode(errors="replace")[-3000:])
