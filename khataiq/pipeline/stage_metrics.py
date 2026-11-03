"""The metrics stage: recompute the business's monthly metrics under a new run."""

from __future__ import annotations

from sqlalchemy.orm import Session

from khataiq.models import Account, Upload
from khataiq.models.enums import UploadStatus
from khataiq.pipeline.runner import StageResult, register_stage
from khataiq.services.metrics import recompute


def stage_metrics(s: Session, upload: Upload) -> StageResult:
    account = s.get(Account, upload.account_id)
    assert account is not None
    recompute(s, account.business_id)
    return StageResult.CONTINUE


register_stage("metrics", stage_metrics, UploadStatus.RECONCILED)
