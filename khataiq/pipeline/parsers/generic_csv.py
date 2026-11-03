"""A CSV parser driven by a CsvBankConfig, so supporting a new bank is configuration.

Layout it understands:

    <preamble rows, may contain '<opening_label>,...,<amount>'>
    <header row whose first cell is header_marker>
    <data rows>
    <a blank line, a footer-prefix row or the closing-label row ends the data>
    <footer rows, may contain '<closing_label>,...,<amount>'>

Columns are found by header name (case-insensitive, trimmed), never by position.

Balances: when the config has no opening_label, the opening balance is derived from the first
row as balance_after - credit + debit. When it has no closing_label, the closing balance is the
last row's balance. A derived opening means the first row can never fail reconciliation, which
is acceptable because every later row and the closing balance still have to add up.
"""

from __future__ import annotations

from khataiq.pipeline.normalize import extract_utr
from khataiq.pipeline.parsers.base import ParsedRow, ParsedStatement, ParseError
from khataiq.pipeline.parsers.configs import CsvBankConfig
from khataiq.pipeline.parsers.csv_common import (
    NumberedRow,
    amount_at,
    date_at,
    decode_statement,
    is_blank,
    numbered_rows,
)


def _first_cell(cells: list[str]) -> str:
    return cells[0].strip().upper() if cells else ""


def _labelled_amount(row: NumberedRow) -> int:
    """The amount on a label row is its last non-empty cell."""
    line_no, cells = row
    values = [cell for cell in cells[1:] if cell.strip()]
    if not values:
        raise ParseError(line_no, "balance line has no amount")
    return amount_at(line_no, values[-1])


def _normalize_reference(text: str) -> str | None:
    """Trim a reference cell; a purely numeric reference loses its zero padding, so
    '0000412300000001' and the 12-digit RRN in another bank's narration compare equal."""
    ref = text.strip()
    if ref.isdigit():
        ref = ref.lstrip("0")
    return ref or None


class GenericCsvParser:
    format = "csv"

    def __init__(self, config: CsvBankConfig) -> None:
        self.config = config
        self.bank = config.bank
        self.version = config.version

    def parse(self, data: bytes) -> ParsedStatement:
        cfg = self.config
        rows = numbered_rows(decode_statement(data), keep_blank=True)

        header_at = next(
            (i for i, (_, cells) in enumerate(rows)
             if _first_cell(cells) == cfg.header_marker.upper()),
            None,
        )
        if header_at is None:
            raise ParseError(0, f"header row starting with {cfg.header_marker!r} not found")
        header_line, header = rows[header_at]
        columns = self._column_index(header_line, header)

        opening: int | None = None
        if cfg.opening_label:
            label = cfg.opening_label.upper()
            for row in rows[:header_at]:
                if _first_cell(row[1]).startswith(label):
                    opening = _labelled_amount(row)
            if opening is None:
                raise ParseError(header_line, f"{cfg.opening_label!r} line not found")

        data_rows, footer = self._split_data_and_footer(rows[header_at + 1:])
        parsed = [self._parse_row(row, columns) for row in data_rows]

        closing: int | None = None
        if cfg.closing_label:
            label = cfg.closing_label.upper()
            for row in footer:
                if _first_cell(row[1]).startswith(label):
                    closing = _labelled_amount(row)
            if closing is None:
                last_line = rows[-1][0]
                raise ParseError(last_line, f"{cfg.closing_label!r} line not found")

        if opening is None:
            if parsed:
                first = parsed[0]
                signed = first.amount_paise if first.direction == "credit" else -first.amount_paise
                opening = first.balance_after_paise - signed
            else:
                opening = closing if closing is not None else 0
        if closing is None:
            closing = parsed[-1].balance_after_paise if parsed else opening

        return ParsedStatement(self.version, opening, closing, parsed)

    def _column_index(self, line_no: int, header: list[str]) -> dict[str, int]:
        cfg = self.config
        positions = {cell.strip().lower(): i for i, cell in enumerate(header)}
        wanted = {
            "date": cfg.date_column,
            "narration": cfg.narration_column,
            "debit": cfg.debit_column,
            "credit": cfg.credit_column,
            "balance": cfg.balance_column,
        }
        if cfg.utr_column:
            wanted["utr"] = cfg.utr_column
        index: dict[str, int] = {}
        for role, name in wanted.items():
            if name.strip().lower() not in positions:
                raise ParseError(line_no, f"header has no {name!r} column")
            index[role] = positions[name.strip().lower()]
        return index

    def _split_data_and_footer(
        self, rows: list[NumberedRow]
    ) -> tuple[list[NumberedRow], list[NumberedRow]]:
        enders = [p.upper() for p in self.config.skip_footer_prefixes]
        if self.config.closing_label:
            enders.append(self.config.closing_label.upper())
        for i, (_, cells) in enumerate(rows):
            first = _first_cell(cells)
            if is_blank(cells) or any(first.startswith(p) for p in enders):
                return rows[:i], [r for r in rows[i:] if not is_blank(r[1])]
        return rows, []

    def _parse_row(self, row: NumberedRow, columns: dict[str, int]) -> ParsedRow:
        line_no, cells = row
        if len(cells) <= max(columns.values()):
            raise ParseError(line_no, f"row has {len(cells)} columns, header needs more")

        def cell(role: str) -> str:
            return cells[columns[role]].strip()

        debit, credit = cell("debit"), cell("credit")
        if bool(debit) == bool(credit):
            raise ParseError(line_no, "exactly one of debit or credit must be filled")
        narration = cell("narration")
        utr = _normalize_reference(cell("utr")) if "utr" in columns else None
        return ParsedRow(
            line_no=line_no,
            txn_date=date_at(line_no, cell("date"), self.config.date_formats),
            amount_paise=amount_at(line_no, debit or credit),
            direction="debit" if debit else "credit",
            balance_after_paise=amount_at(line_no, cell("balance")),
            narration=narration,
            utr=utr or extract_utr(narration),
        )
