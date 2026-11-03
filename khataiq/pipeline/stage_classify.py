"""The classify stage: label this upload's rows. Rules first; the model for the rest.

Idempotent: a row that already has a rule or model label is skipped, so a re-run adds nothing.
Labels are append-only rows; a human label added later always wins (current_txn_labels).
"""

from __future__ import annotations

import logging

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from khataiq.classify.model import get_model
from khataiq.classify.rules import rule_label
from khataiq.models import Transaction, TxnLabelRow, Upload, UploadRow
from khataiq.models.enums import LabelMethod, TxnLabel, UploadStatus
from khataiq.pipeline.runner import StageResult, register_stage

log = logging.getLogger(__name__)


def stage_classify(s: Session, upload: Upload) -> StageResult:
    already_labelled = exists(select(TxnLabelRow.id).where(
        TxnLabelRow.txn_id == Transaction.id,
        TxnLabelRow.method.in_((LabelMethod.RULE, LabelMethod.MODEL))))
    rows = s.scalars(
        select(Transaction).join(UploadRow, UploadRow.txn_id == Transaction.id)
        .where(UploadRow.upload_id == upload.id, ~already_labelled)
        .order_by(Transaction.id)).unique().all()

    unmatched: list[Transaction] = []
    for txn in rows:
        rule = rule_label(txn.narration_norm, txn.direction.value)
        if rule is None:
            unmatched.append(txn)
            continue
        s.add(TxnLabelRow(org_id=txn.org_id, txn_id=txn.id, label=rule.label,
                          method=LabelMethod.RULE, rule_id=f"{rule.rule_id}:v{rule.version}"))

    model = get_model()
    if model is None:
        if unmatched:
            log.warning("no label model deployed; %d rows left unlabelled", len(unmatched))
        return StageResult.CONTINUE
    predictions = model.predict([(t.narration_norm, t.direction.value, t.amount_paise)
                                 for t in unmatched])
    for txn, prediction in zip(unmatched, predictions, strict=True):
        s.add(TxnLabelRow(org_id=txn.org_id, txn_id=txn.id, label=TxnLabel(prediction.label),
                          method=LabelMethod.MODEL, model_version=model.version,
                          confidence=prediction.confidence))
    return StageResult.CONTINUE


register_stage("classify", stage_classify, UploadStatus.RECONCILED)
