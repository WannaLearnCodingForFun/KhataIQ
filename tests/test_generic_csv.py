"""Golden-file and error tests for the config-driven CSV parser (hdfc_like, sbi_like)."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from khataiq.core.ledger import Txn, reconcile
from khataiq.pipeline.parsers import get_parser, supported_parsers
from khataiq.pipeline.parsers.base import ParsedStatement, ParseError

FIXTURES = Path(__file__).parent / "fixtures"
BANKS = ["hdfc_like", "sbi_like"]

SBI_HEADER = "Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance"


def as_json(statement: ParsedStatement) -> dict:
    data = asdict(statement)
    for row in data["rows"]:
        row["txn_date"] = row["txn_date"].isoformat()
    return data


def sbi(text: str) -> ParsedStatement:
    return get_parser("sbi_like", "csv").parse(text.encode())


@pytest.mark.parametrize("bank", BANKS)
def test_matches_golden_output(bank):
    raw = (FIXTURES / bank / "statement_nov.csv").read_bytes()
    expected = json.loads((FIXTURES / bank / "statement_nov.expected.json").read_text())
    assert as_json(get_parser(bank, "csv").parse(raw)) == expected


@pytest.mark.parametrize("bank", BANKS)
def test_golden_statement_reconciles(bank):
    s = get_parser(bank, "csv").parse((FIXTURES / bank / "statement_nov.csv").read_bytes())
    txns = [Txn(i, 1, r.txn_date, r.amount_paise, r.direction, r.balance_after_paise,
                r.narration, r.utr) for i, r in enumerate(s.rows)]
    assert reconcile(s.opening_paise, s.closing_paise, txns).ok


def test_registry_lists_all_parsers():
    banks = {(bank, fmt) for bank, fmt, _ in supported_parsers()}
    assert {("demo", "csv"), ("hdfc_like", "csv"), ("sbi_like", "csv")} <= banks


def test_hdfc_like_derives_opening_from_first_row():
    s = get_parser("hdfc_like", "csv").parse(
        (FIXTURES / "hdfc_like" / "statement_nov.csv").read_bytes())
    first = s.rows[0]
    assert s.opening_paise == first.balance_after_paise - first.amount_paise  # first is a credit


def test_columns_are_mapped_by_name_not_position():
    text = (
        "Opening Balance,,100.00\n"
        "txn date , Balance,Credit,Debit,Description,Value Date,Ref No./Cheque No.\n"
        "1 Nov 2026,150.00,50.00,,UPI/CR/412300000099/X,,\n"
        "Closing Balance,,150.00\n"
    )
    s = sbi(text)
    assert (s.rows[0].amount_paise, s.rows[0].direction, s.rows[0].utr) == (
        5000, "credit", "412300000099")


def test_cp1252_file_is_decoded():
    text = (f"Opening Balance,,,,,,100.00\n{SBI_HEADER}\n"
            "1 Nov 2026,,CAFÉ,,10.00,,90.00\nClosing Balance,,,,,,90.00\n")
    s = get_parser("sbi_like", "csv").parse(text.encode("cp1252"))
    assert s.rows[0].narration == "CAFÉ"


def test_numeric_reference_loses_zero_padding():
    raw = (FIXTURES / "hdfc_like" / "statement_nov.csv").read_bytes()
    assert get_parser("hdfc_like", "csv").parse(raw).rows[0].utr == "412300000001"


@pytest.mark.parametrize("bad_row", [
    "1 Nov 2026,,BOTH,,10.00,10.00,100.00",
    "1 Nov 2026,,NEITHER,,,,100.00",
    "31 Feb 2026,,BAD DATE,,10.00,,90.00",
    "1 Nov 2026,,BAD AMOUNT,,10.001,,90.00",
    "1 Nov 2026,,TOO SHORT",
])
def test_malformed_row_reports_its_line(bad_row):
    text = f"Opening Balance,,,,,,100.00\n{SBI_HEADER}\n{bad_row}\nClosing Balance,,,,,,90.00\n"
    with pytest.raises(ParseError) as err:
        sbi(text)
    assert err.value.line_no == 3


def test_hdfc_like_malformed_row_reports_its_line():
    raw = (FIXTURES / "hdfc_like" / "statement_nov.csv").read_text()
    broken = raw.replace('"18,000.00",,"33,250.00"', '"18,000.00","1.00","33,250.00"')
    with pytest.raises(ParseError) as err:
        get_parser("hdfc_like", "csv").parse(broken.encode())
    assert err.value.line_no == 7


def test_missing_header_is_a_file_level_error():
    with pytest.raises(ParseError) as err:
        sbi("Opening Balance,,100.00\nnot a header\n")
    assert err.value.line_no == 0


def test_missing_column_points_at_header():
    with pytest.raises(ParseError) as err:
        sbi("Opening Balance,,100.00\nTxn Date,Description,Debit,Credit\n")
    assert err.value.line_no == 2


def test_missing_closing_label_is_an_error():
    with pytest.raises(ParseError, match="Closing Balance"):
        sbi(f"Opening Balance,,,,,,100.00\n{SBI_HEADER}\n1 Nov 2026,,X,,10.00,,90.00\n")


def test_undecodable_bytes_are_a_file_level_error():
    with pytest.raises(ParseError) as err:
        get_parser("sbi_like", "csv").parse(b"x\x81\x8d\x8f\x90\x9d\xff\xfe")
    assert err.value.line_no == 0
