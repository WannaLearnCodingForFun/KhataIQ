"""M1.1: the initial schema's constraints, view and triggers."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from khataiq.models import Flag, FlagEvidence, TxnLabelRow
from khataiq.models.enums import FlagKind, LabelMethod, TxnLabel
from tests.integration import factories as f


def test_duplicate_account_fingerprint_is_rejected(owner_session: Session):
    w = f.world(owner_session)
    f.txn(owner_session, w["org"], w["account"], w["upload"], fingerprint="a" * 64)
    with pytest.raises(IntegrityError, match="uq_transactions_account_id"):
        f.txn(owner_session, w["org"], w["account"], w["upload"], fingerprint="a" * 64)


def test_same_fingerprint_in_another_account_is_fine(owner_session: Session):
    w = f.world(owner_session)
    other = f.account(owner_session, w["org"], w["business"])
    f.txn(owner_session, w["org"], w["account"], w["upload"], fingerprint="b" * 64)
    f.txn(owner_session, w["org"], other.id, w["upload"], fingerprint="b" * 64)


def test_zero_amount_violates_check(owner_session: Session):
    w = f.world(owner_session)
    with pytest.raises(IntegrityError, match="ck_transactions_amount_positive"):
        f.txn(owner_session, w["org"], w["account"], w["upload"], amount_paise=0)


def test_duplicate_upload_hash_per_account_is_rejected(owner_session: Session):
    w = f.world(owner_session)
    sha = owner_session.execute(text("SELECT sha256 FROM uploads")).scalar_one()
    with pytest.raises(IntegrityError, match="uq_uploads_account_id"):
        owner_session.execute(text(
            "INSERT INTO uploads (org_id, account_id, storage_key, sha256, content_type, "
            "size_bytes, created_by) VALUES (:o, :a, 'k', :s, 'text/csv', 1, :u)"),
            {"o": w["org"], "a": w["account"], "s": sha, "u": w["user"]})


def test_account_mask_must_be_four_digits(owner_session: Session):
    w = f.world(owner_session)
    with pytest.raises(IntegrityError, match="mask_is_last_4_digits"):
        f.account(owner_session, w["org"], w["business"], mask="12AB")


def test_flag_without_evidence_fails_at_commit(owner_session: Session):
    w = f.world(owner_session)
    owner_session.add(Flag(org_id=w["org"], business_id=w["business"],
                           kind=FlagKind.CYCLE, summary="s", total_paise=1, rule_id="CYCLE",
                           rule_version=1, dedupe_key="CYCLE:1:x"))
    owner_session.flush()  # deferred: the INSERT itself succeeds
    with pytest.raises(IntegrityError, match="has no evidence rows"):
        owner_session.commit()


def test_flag_with_evidence_commits(owner_session: Session):
    w = f.world(owner_session)
    t = f.txn(owner_session, w["org"], w["account"], w["upload"])
    flag = Flag(org_id=w["org"], business_id=w["business"], kind=FlagKind.CYCLE,
                summary="s", total_paise=1, rule_id="CYCLE", rule_version=1,
                dedupe_key="CYCLE:1:x")
    owner_session.add(flag)
    owner_session.flush()
    owner_session.add(FlagEvidence(flag_id=flag.id, txn_id=t.id, org_id=w["org"]))
    owner_session.commit()


def test_current_label_prefers_human_then_rule_then_model(owner_session: Session):
    w = f.world(owner_session)
    t = f.txn(owner_session, w["org"], w["account"], w["upload"])

    def add(label: TxnLabel, method: LabelMethod) -> None:
        owner_session.add(TxnLabelRow(org_id=w["org"], txn_id=t.id, label=label, method=method))
        owner_session.flush()

    def current() -> str:
        return owner_session.execute(
            text("SELECT label FROM current_txn_labels WHERE txn_id = :t"), {"t": t.id}
        ).scalar_one()

    add(TxnLabel.SALES, LabelMethod.MODEL)
    assert current() == "sales"
    add(TxnLabel.RENT, LabelMethod.RULE)
    add(TxnLabel.OTHER, LabelMethod.MODEL)  # newer, but a model label never beats a rule
    assert current() == "rent"
    add(TxnLabel.SUPPLIER_PAYMENT, LabelMethod.HUMAN)
    assert current() == "supplier_payment"
