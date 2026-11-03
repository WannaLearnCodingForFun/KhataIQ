"""Spec for khataiq/pipeline/normalize.py. Do not edit these to make them pass."""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from khataiq.pipeline.normalize import extract_utr, format_paise, parse_amount, parse_date

# ---------------------------------------------------------------- amounts

@pytest.mark.parametrize("raw, paise", [
    ("1,23,456.78", 12_345_678),
    ("123,456.78", 12_345_678),
    ("500", 50_000),
    ("0.5", 50),
    ("0.29", 29),
    ("  1,000.00 ", 100_000),
    ("0.00", 0),
    ("1,00,00,000.01", 1_000_000_001),
])
def test_parse_amount(raw, paise):
    assert parse_amount(raw) == paise


@pytest.mark.parametrize("raw", [
    "", "   ", "abc", "-5", "1.234", "1.2.3", "1e3", "NaN", "inf", ".", "12.", "₹500",
])
def test_parse_amount_rejects(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


def test_parse_amount_returns_int_not_float():
    assert type(parse_amount("19.99")) is int


@pytest.mark.parametrize("paise, text", [(12_345_678, "123456.78"), (50, "0.50"), (0, "0.00")])
def test_format_paise(paise, text):
    assert format_paise(paise) == text


def test_format_paise_rejects_negative():
    with pytest.raises(ValueError):
        format_paise(-1)


@given(st.integers(min_value=0, max_value=10**15))
def test_amount_round_trip(paise):
    assert parse_amount(format_paise(paise)) == paise


# ---------------------------------------------------------------- dates

@pytest.mark.parametrize("raw, expected", [
    ("05/10/2026", date(2026, 10, 5)),
    ("05-Oct-26", date(2026, 10, 5)),
    (" 31/12/2025 ", date(2025, 12, 31)),
    ("29/02/2028", date(2028, 2, 29)),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["", "2026-10-05", "31/02/2026", "29/02/2026", "5 Oct 2026",
                                 "13/13/2026", "05/10/26"])
def test_parse_date_rejects(raw):
    with pytest.raises(ValueError):
        parse_date(raw)


# ---------------------------------------------------------------- UTR

@pytest.mark.parametrize("narration, utr", [
    ("UPI/412345678901/ZOMATO/zomato@hdfcbank", "412345678901"),
    ("IMPS/P2A/612345678901/RENT", "612345678901"),
    ("UPI-111111111111-222222222222", "111111111111"),
    ("NEFT CR-SBIN0001234-SHARMA TRADERS", None),
    ("POS 4111111111111111 AMAZON", None),       # 16-digit card number, not a reference
    ("UPI/12345678901/SHORT", None),             # 11 digits
    ("", None),
])
def test_extract_utr(narration, utr):
    assert extract_utr(narration) == utr
