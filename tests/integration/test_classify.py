"""M8.2: the classify stage — rules, model, idempotency, and the loan rule it unlocks."""

from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from khataiq.models import Transaction, TxnLabelRow
from khataiq.models.enums import EvidenceKind, LabelMethod
from khataiq.pipeline.parsers.demo_csv import render_demo_csv
from khataiq.pipeline.runner import InlineDispatcher, StageJob
from tests.integration.pipeline_helpers import make_shop, run_pipeline, upload

pytestmark = pytest.mark.usefixtures("migrated", "local_store")


def day(n: int) -> date:
    return date(2026, 10, n)


ROWS = [
    (day(1), "UPI/RAMESH SHARMA/ramesh12@okaxis/412300000001", 0, 123_456),
    (day(2), "NEFT/HDFC0000001/BAJAJ FINANCE LOAN DISB", 0, 50_000_000),
    (day(7), "ACH D- BAJAJ FINANCE EMI", 2_100_000, 0),
    (day(9), "SMS ALERT CHARGES", 1_770, 0),
]


def labels(s: Session) -> dict[str, tuple[str, str]]:
    rows = s.execute(text(
        "SELECT t.narration, l.label, l.method FROM current_txn_labels l "
        "JOIN transactions t ON t.id = l.txn_id")).all()
    return {n: (str(label), str(method)) for n, label, method in rows}


def test_rules_then_model_label_every_row(owner_session: Session):
    shop = make_shop(owner_session)
    upload(shop, render_demo_csv(1_000_000, ROWS))
    run_pipeline()
    got = labels(owner_session)
    assert got["NEFT/HDFC0000001/BAJAJ FINANCE LOAN DISB"] == ("loan_in", "rule")
    assert got["ACH D- BAJAJ FINANCE EMI"] == ("emi", "rule")
    assert got["SMS ALERT CHARGES"] == ("bank_charges", "rule")
    assert got["UPI/RAMESH SHARMA/ramesh12@okaxis/412300000001"] == ("sales", "model")
    model_row = owner_session.scalars(select(TxnLabelRow).where(
        TxnLabelRow.method == LabelMethod.MODEL)).one()
    assert model_row.model_version == "label-v1" and 0.6 <= model_row.confidence <= 1


def test_loan_disbursal_is_excluded_once_labelled(owner_session: Session):
    shop = make_shop(owner_session)
    upload(shop, render_demo_csv(1_000_000, ROWS))
    run_pipeline()
    kinds = owner_session.execute(text(
        "SELECT kind FROM evidence_links WHERE run_id = (SELECT max(id) FROM evidence_runs)"
    )).scalars().all()
    assert kinds == [EvidenceKind.LOAN_DISBURSAL.value]


def test_classify_is_idempotent_and_humans_win(owner_session: Session):
    shop = make_shop(owner_session)
    upload_id = upload(shop, render_demo_csv(1_000_000, ROWS))
    run_pipeline()
    before = owner_session.scalar(select(func.count()).select_from(TxnLabelRow))
    owner_session.execute(text("DELETE FROM pipeline_runs WHERE stage = 'classify'"))
    owner_session.commit()
    again = InlineDispatcher()
    again.dispatch(StageJob(upload_id, shop.owner.org_id, "classify"))
    again.drain()
    assert owner_session.scalar(select(func.count()).select_from(TxnLabelRow)) == before

    sale = owner_session.scalar(select(Transaction).where(Transaction.amount_paise == 123_456))
    owner_session.add(TxnLabelRow(org_id=sale.org_id, txn_id=sale.id, label="other",
                                  method=LabelMethod.HUMAN))
    owner_session.commit()
    assert labels(owner_session)["UPI/RAMESH SHARMA/ramesh12@okaxis/412300000001"] == (
        "other", "human")
