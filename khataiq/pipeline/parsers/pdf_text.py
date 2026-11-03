"""Parser for digital (text-layer) PDF statements from the 'demo' bank.

* Tables come from pdfplumber's page.extract_tables(); rows from every page are concatenated
  and the header row, which is printed again on each page, is dropped wherever it appears.
* line_no = page number * 1000 + row index in that page's table (the header is row 0), so
  1003 means "page 1, third transaction row" — enough for a person to find it.
* Opening and closing balances are read from the page text ('Opening Balance: 25,000.00').
* A PDF with no extractable text (a scan) raises ParseError(0, "no text layer"). OCR is out
  of scope.
"""

from __future__ import annotations

import io
import re

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

from khataiq.pipeline.normalize import extract_utr
from khataiq.pipeline.parsers.base import ParsedRow, ParsedStatement, ParseError
from khataiq.pipeline.parsers.csv_common import amount_at, date_at

HEADER = ["date", "narration", "withdrawal", "deposit", "balance"]
_AMOUNT = r"([\d,]+(?:\.\d{1,2})?)"
_OPENING_RE = re.compile(rf"Opening Balance\s*:?\s*{_AMOUNT}", re.IGNORECASE)
_CLOSING_RE = re.compile(rf"Closing Balance\s*:?\s*{_AMOUNT}", re.IGNORECASE)


def _clean(cell: str | None) -> str:
    """pdfplumber gives None for empty cells and '\\n' where text wrapped inside a cell."""
    return " ".join((cell or "").split())


class DemoBankPdfParser:
    bank = "demo"
    format = "pdf_text"  # text-layer PDFs only; a scanned PDF would need a different parser
    version = "demo-pdf/1"

    def parse(self, data: bytes) -> ParsedStatement:
        try:
            pdf = pdfplumber.open(io.BytesIO(data))
        except PdfminerException as exc:
            raise ParseError(0, "not a readable PDF") from exc

        with pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            if not text.strip():
                raise ParseError(0, "no text layer")
            rows: list[ParsedRow] = []
            for page_no, page in enumerate(pdf.pages, start=1):
                for table in page.extract_tables():
                    for index, raw in enumerate(table):
                        cells = [_clean(cell) for cell in raw]
                        if [c.lower() for c in cells] == HEADER:
                            continue
                        rows.append(self._parse_row(page_no * 1000 + index, cells))

        return ParsedStatement(
            parser_version=self.version,
            opening_paise=self._balance(_OPENING_RE, text, "Opening Balance"),
            closing_paise=self._balance(_CLOSING_RE, text, "Closing Balance"),
            rows=rows,
        )

    @staticmethod
    def _balance(pattern: re.Pattern[str], text: str, label: str) -> int:
        match = pattern.search(text)
        if match is None:
            raise ParseError(0, f"{label!r} not found in the PDF text")
        return amount_at(0, match.group(1))

    @staticmethod
    def _parse_row(line_no: int, cells: list[str]) -> ParsedRow:
        if len(cells) != len(HEADER):
            raise ParseError(line_no, f"expected {len(HEADER)} columns, got {len(cells)}")
        date_text, narration, withdrawal, deposit, balance = cells
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
