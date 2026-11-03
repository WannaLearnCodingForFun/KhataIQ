import pytest

from khataiq.core.ledger import normalize_narration
from khataiq.pipeline.enrich import channel_of, counterparty_key


@pytest.mark.parametrize("narration, channel", [
    ("UPI/412345678901/ZOMATO/zomato@hdfcbank", "upi"),
    ("NEFT CR-SBIN0001234-SHARMA TRADERS", "neft"),
    ("IMPS/P2A/612345678901/RENT", "imps"),
    ("ACH D- BAJAJ FINANCE EMI-LN99812", "ach"),
    ("ATM WDL, MG ROAD", "atm"),
    ("CASH DEP, MG ROAD BRANCH", "cash"),
    ("POS 12 STATIONERY MART", "pos"),
    ("DEBIT-ATMCard AMC 5085XXXXXXXX1234", "charges"),
    ("SOMETHING ELSE", None),
])
def test_channel(narration, channel):
    assert channel_of(normalize_narration(narration)) == channel


@pytest.mark.parametrize("narration, key", [
    ("UPI/412345678901/ZOMATO/Zomato@HDFCbank", "vpa:zomato@hdfcbank"),
    ("UPI-RAMESH KIRANA-ramesh@okicici-412300000001-SALE", "vpa:ramesh@okicici"),
    ("NEFT DR-SBIN0004321-SHREE SUPPLIERS-INV 88", "name:SHREE SUPPLIERS"),
    ("NEFT CR-SBIN0001234-SHARMA TRADERS", "name:SHARMA TRADERS"),
    ("ATM WDL, MG ROAD", None),
    ("INT CR", None),
])
def test_counterparty_key(narration, key):
    assert counterparty_key(narration, channel_of(normalize_narration(narration))) == key


def test_counterparty_is_stable_across_spacing_and_case():
    a = counterparty_key("NEFT DR-SBIN0004321-Shree  Suppliers-INV 88", "neft")
    b = counterparty_key("neft dr-SBIN0004321-SHREE SUPPLIERS-inv 99", "neft")
    assert a == b == "name:SHREE SUPPLIERS"
