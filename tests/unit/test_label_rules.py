"""M8.1: the rule labeller."""

import pytest

from khataiq.classify.rules import RULES, rule_label
from khataiq.core.ledger import normalize_narration
from khataiq.models.enums import TxnLabel


@pytest.mark.parametrize("narration, direction, label", [
    ("UPI/REFUND/ZOMATO/zomato@ybl/412300000001", "credit", TxnLabel.REFUND),
    ("ACH D- BAJAJ FINANCE EMI", "debit", TxnLabel.EMI),
    ("NEFT/HDFC0000001/BAJAJ FINANCE LOAN DISB", "credit", TxnLabel.LOAN_IN),
    ("NEFT/ICIC0000001/SALARY OCT RAMESH", "debit", TxnLabel.SALARY_PAID),
    ("IMPS/P2A/612345678901/RENT", "debit", TxnLabel.RENT),
    ("CASH DEP MG ROAD", "credit", TxnLabel.CASH_DEPOSIT),
    ("ATM WDL KORAMANGALA", "debit", TxnLabel.CASH_WITHDRAWAL),
    ("GST PMT CBIC CHALLAN", "debit", TxnLabel.TAX),
    ("SMS ALERT CHARGES", "debit", TxnLabel.BANK_CHARGES),
    ("UPI/BESCOM/bescom@ybl/412300000002", "debit", TxnLabel.UTILITIES),
])
def test_rules(narration, direction, label):
    rule = rule_label(normalize_narration(narration), direction)
    assert rule is not None and rule.label == label


@pytest.mark.parametrize("narration, direction", [
    ("UPI/RAMESH SHARMA/ramesh12@okaxis/412300000003", "credit"),  # a sale: left to the model
    ("NEFT/SBIN0000001/SHARMA TRADERS", "debit"),
    ("ACH D- BAJAJ FINANCE EMI", "credit"),                        # direction must match
    ("NEFT REVENUE SHARE", "credit"),                              # REV only as a whole word
    ("CURRENT AFFAIRS MAGAZINE", "debit"),                         # RENT only as a whole word
])
def test_no_rule(narration, direction):
    assert rule_label(normalize_narration(narration), direction) is None


def test_rule_ids_are_unique_and_versioned():
    assert len({r.rule_id for r in RULES}) == len(RULES)
    assert all(r.version >= 1 for r in RULES)
