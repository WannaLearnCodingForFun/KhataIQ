"""Helpers shared by the CSV parsers: decoding, line-numbered rows, and value parsing that
turns a ValueError into a ParseError pointing at the line."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date

from khataiq.pipeline.normalize import DEFAULT_DATE_FORMATS, parse_amount, parse_date
from khataiq.pipeline.parsers.base import ParseError

# A non-blank CSV row with the 1-based line number it ends on.
NumberedRow = tuple[int, list[str]]


def decode_statement(data: bytes) -> str:
    """UTF-8 (a leading byte-order mark is dropped), then cp1252, else ParseError(0)."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseError(0, "file is neither UTF-8 nor cp1252 text")


def numbered_rows(text: str) -> list[NumberedRow]:
    """Every row that has at least one non-empty cell, with its physical line number.

    csv.reader.line_num counts lines consumed so far, so blank lines are counted even though
    they are skipped, and CRLF endings are handled by the csv module itself.
    """
    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[NumberedRow] = []
    for cells in reader:
        if any(cell.strip() for cell in cells):
            rows.append((reader.line_num, cells))
    return rows


def amount_at(line_no: int, text: str) -> int:
    try:
        return parse_amount(text)
    except ValueError as exc:
        raise ParseError(line_no, str(exc)) from exc


def date_at(line_no: int, text: str, formats: Sequence[str] = DEFAULT_DATE_FORMATS) -> date:
    try:
        return parse_date(text, formats)
    except ValueError as exc:
        raise ParseError(line_no, str(exc)) from exc
