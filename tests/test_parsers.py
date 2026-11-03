"""Spec for the parser registry and khataiq/pipeline/parsers/demo_csv.py.
Do not edit these to make them pass. The expected JSON is the golden output: if a parser
change alters it, that change must be deliberate (and bump the parser version)."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from khataiq.core.ledger import Txn, reconcile
from khataiq.pipeline.parsers import get_parser
from khataiq.pipeline.parsers.base import ParseError

FIXTURES = Path(__file__).parent / "fixtures"
OCT_CSV = FIXTURES / "demo_bank" / "statement_oct.csv"
OCT_EXPECTED = FIXTURES / "demo_bank" / "statement_oct.expected.json"

HEADER = "Date,Narration,Withdrawal,Deposit,Balance"


def demo(text: str):
    return get_parser("demo", "csv").parse(text.encode("utf-8"))


def as_json(statement) -> dict:
    data = asdict(statement)
    for row in data["rows"]:
        row["txn_date"] = row["txn_date"].isoformat()
    return data


# ---------------------------------------------------------------- registry

def test_registry_finds_demo_parser_ignoring_case():
    assert get_parser("DEMO", "Csv").version == "demo-csv/1"


def test_registry_unknown_pair_is_key_error():
    with pytest.raises(KeyError):
        get_parser("demo", "pdf")


# ---------------------------------------------------------------- golden file

def test_demo_csv_matches_golden_output():
    statement = get_parser("demo", "csv").parse(OCT_CSV.read_bytes())
    assert as_json(statement) == json.loads(OCT_EXPECTED.read_text())


def test_bom_and_crlf_line_endings_parse_the_same():
    raw = OCT_CSV.read_bytes()
    windows = b"\xef\xbb\xbf" + raw.replace(b"\n", b"\r\n")
    parser = get_parser("demo", "csv")
    assert parser.parse(windows) == parser.parse(raw)


def test_parsed_statement_reconciles():
    s = get_parser("demo", "csv").parse(OCT_CSV.read_bytes())
    txns = [
        Txn(i, 1, r.txn_date, r.amount_paise, r.direction, r.balance_after_paise,
            r.narration, r.utr)
        for i, r in enumerate(s.rows)
    ]
    assert reconcile(s.opening_paise, s.closing_paise, txns).ok


# ---------------------------------------------------------------- errors point at the line

@pytest.mark.parametrize("bad_row", [
    "01/10/2026,BOTH,100.00,100.00,10000.00",      # withdrawal AND deposit
    "01/10/2026,NEITHER,,,10000.00",               # neither
    "01/10/2026,BAD AMOUNT,1.234,,9998.77",        # fractional paise
    "31/02/2026,BAD DATE,100.00,,9900.00",         # impossible date
    "01/10/2026,TOO FEW COLUMNS,100.00",
])
def test_bad_row_reports_its_line_number(bad_row):
    text = f"Opening Balance,10000.00\n{HEADER}\n{bad_row}\nClosing Balance,9900.00\n"
    with pytest.raises(ParseError) as err:
        demo(text)
    assert err.value.line_no == 3


def test_line_numbers_count_blank_lines():
    text = f"Opening Balance,10000.00\n\n{HEADER}\n\n01/10/2026,X,,,1.00\nClosing Balance,1.00\n"
    with pytest.raises(ParseError) as err:
        demo(text)
    assert err.value.line_no == 5


@pytest.mark.parametrize("text, line_no", [
    (f"{HEADER}\nClosing Balance,0.00\n", 1),                                # no opening
    ("Opening Balance,0.00\nDate,Narration,Amount\nClosing Balance,0.00\n", 2),  # wrong header
    (f"Opening Balance,10.00\n{HEADER}\n01/10/2026,X,1.00,,9.00\n", 3),       # no closing
])
def test_structure_errors(text, line_no):
    with pytest.raises(ParseError) as err:
        demo(text)
    assert err.value.line_no == line_no


def test_empty_statement_parses():
    s = demo(f"Opening Balance,500.00\n{HEADER}\nClosing Balance,500.00\n")
    assert (s.opening_paise, s.closing_paise, s.rows) == (50_000, 50_000, [])


def test_error_message_names_the_line():
    with pytest.raises(ParseError, match="line 3"):
        demo(f"Opening Balance,0.00\n{HEADER}\n01/10/2026,X,,,0.00\nClosing Balance,0.00\n")
