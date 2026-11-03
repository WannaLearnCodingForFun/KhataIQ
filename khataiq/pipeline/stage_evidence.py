"""The evidence stage: re-run the evidence engine for the upload's business."""

from __future__ import annotations

from sqlalchemy.orm import Session

from khataiq.models import Account, Upload
from khataiq.models.enums import UploadStatus
from khataiq.pipeline.runner import StageResult, register_stage
from khataiq.services.evidence import run_evidence


def stage_evidence(s: Session, upload: Upload) -> StageResult:
    account = s.get(Account, upload.account_id)
    assert account is not None
    run_evidence(s, account.business_id)
    return StageResult.CONTINUE


register_stage("evidence", stage_evidence, UploadStatus.RECONCILED)
