"""Types every statement parser shares. These are given; the parsers are yours."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from khataiq.core.ledger import Direction


class ParseError(ValueError):
    """A statement file could not be parsed. line_no is 1-based, as a text editor shows it."""

    def __init__(self, line_no: int, message: str) -> None:
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no
        self.message = message


@dataclass(frozen=True)
class ParsedRow:
    line_no: int               # where the row is in the file, for error reports and audit
    txn_date: date
    amount_paise: int          # always > 0; direction carries the sign
    direction: Direction
    balance_after_paise: int
    narration: str             # as printed; normalization happens in fingerprint()
    utr: str | None


@dataclass(frozen=True)
class ParsedStatement:
    parser_version: str        # stored on the upload, so a parser fix can be traced
    opening_paise: int
    closing_paise: int
    rows: list[ParsedRow]


class Parser(Protocol):
    bank: str
    format: str
    version: str

    def parse(self, data: bytes) -> ParsedStatement: ...
