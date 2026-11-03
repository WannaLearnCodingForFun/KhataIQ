"""Parser for the 'demo' bank's CSV export.

File layout (see tests/fixtures/demo_bank/statement_oct.csv):

    Opening Balance,10000.00
    Date,Narration,Withdrawal,Deposit,Balance
    01/10/2026,UPI/412345678901/ZOMATO/zomato@hdfcbank,450.00,,9550.00
    ...
    Closing Balance,15587.50

* UTF-8 (a byte-order mark is tolerated), read with the csv module because narrations can
  contain quoted commas.
* Blank lines are skipped. line_no counts every physical line, blank ones included.
* First non-blank line is 'Opening Balance,<amount>', the next is the header exactly as above,
  the last non-blank line is 'Closing Balance,<amount>'.
* Each data row has exactly one of Withdrawal (debit) or Deposit (credit) filled in.
* utr = extract_utr(narration).
* The demo bank has no overdraft accounts, so every balance is a plain non-negative amount.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from khataiq.pipeline.normalize import extract_utr
from khataiq.pipeline.parsers.base import ParsedRow, ParsedStatement, ParseError
from khataiq.pipeline.parsers.csv_common import (
    NumberedRow,
    amount_at,
    date_at,
    decode_statement,
    numbered_rows,
)

HEADER = ["Date", "Narration", "Withdrawal", "Deposit", "Balance"]


def _labelled_amount(row: NumberedRow, label: str) -> int:
    line_no, cells = row
    if len(cells) != 2 or cells[0].strip() != label:
        raise ParseError(line_no, f"expected '{label},<amount>'")
    return amount_at(line_no, cells[1])


class DemoBankCsvParser:
    bank = "demo"
    format = "csv"
    version = "demo-csv/1"

    def parse(self, data: bytes) -> ParsedStatement:
        rows = numbered_rows(decode_statement(data))
        if not rows:
            raise ParseError(1, "file is empty")

        opening = _labelled_amount(rows[0], "Opening Balance")
        if len(rows) < 2:
            raise ParseError(rows[0][0], "missing header row")
        header_line, header = rows[1]
        if [cell.strip() for cell in header] != HEADER:
            raise ParseError(header_line, f"expected header {','.join(HEADER)}")
        if len(rows) < 3:
            raise ParseError(header_line, "missing 'Closing Balance' line")
        closing = _labelled_amount(rows[-1], "Closing Balance")

        return ParsedStatement(
            parser_version=self.version,
            opening_paise=opening,
            closing_paise=closing,
            rows=[self._parse_row(row) for row in rows[2:-1]],
        )

    def _parse_row(self, row: NumberedRow) -> ParsedRow:
        line_no, cells = row
        if len(cells) != len(HEADER):
            raise ParseError(line_no, f"expected {len(HEADER)} columns, got {len(cells)}")
        date_text, narration, withdrawal, deposit, balance = (c.strip() for c in cells)
        if bool(withdrawal) == bool(deposit):
            raise ParseError(line_no, "exactly one of Withdrawal or Deposit must be filled")
        return ParsedRow(
            line_no=line_no,
            txn_date=date_at(line_no, date_text),
            amount_paise=amount_at(line_no, withdrawal or deposit),
            direction="debit" if withdrawal else "credit",
            balance_after_paise=amount_at(line_no, balance),
            narration=narration,
            utr=extract_utr(narration),
        )


def _rupees(paise: int) -> str:
    rupees, rest = divmod(paise, 100)
    return f"{rupees}.{rest:02d}"


def render_demo_csv(opening_paise: int,
                    rows: list[tuple[date, str, int, int]]) -> bytes:
    """Write a statement in this parser's format. rows are (date, narration, debit_paise,
    credit_paise) with exactly one of the two amounts non-zero; balances are computed.

    The inverse of parse(), used by tests and the synthetic data generator.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Opening Balance", _rupees(opening_paise)])
    writer.writerow(HEADER)
    balance = opening_paise
    for txn_date, narration, debit, credit in rows:
        if (debit > 0) == (credit > 0):
            raise ValueError("exactly one of debit or credit must be positive")
        balance += credit - debit
        if balance < 0:
            raise ValueError("the demo bank has no overdraft: balance went negative")
        writer.writerow([txn_date.strftime("%d/%m/%Y"), narration,
                         _rupees(debit) if debit else "", _rupees(credit) if credit else "",
                         _rupees(balance)])
    writer.writerow(["Closing Balance", _rupees(balance)])
    return buffer.getvalue().encode()
