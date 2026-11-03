"""Parser for the 'demo' bank's CSV export — YOU implement parse().

Make tests/test_parsers.py pass:  pytest -q tests/test_parsers.py

File layout (see tests/fixtures/demo_bank/statement_oct.csv):

    Opening Balance,10000.00
    Date,Narration,Withdrawal,Deposit,Balance
    01/10/2026,UPI/412345678901/ZOMATO/zomato@hdfcbank,450.00,,9550.00
    ...
    Closing Balance,15587.50

* Decode as UTF-8, and tolerate a byte-order mark at the start (Excel adds one).
* Use the csv module, not str.split(','): narrations can contain quoted commas.
* Blank lines are skipped. line_no counts every physical line, blank ones included.
* First non-blank line must be 'Opening Balance,<amount>'; the next must be the header
  exactly as above; the last non-blank line must be 'Closing Balance,<amount>'.
* Each data row has exactly one of Withdrawal (debit) or Deposit (credit) filled in.
  Both or neither is a ParseError for that line.
* utr = extract_utr(narration).
* The demo bank has no overdraft accounts, so every balance is a plain non-negative
  amount. (Real banks print overdrawn balances as e.g. '1,200.00 Dr'; that's a later parser.)
* Any ValueError from normalize.py must surface as ParseError(line_no, ...) so the
  user sees WHERE the file is bad. Hint: `raise ParseError(...) from exc`.
"""

from __future__ import annotations

from khataiq.pipeline.parsers.base import ParsedStatement


class DemoBankCsvParser:
    bank = "demo"
    format = "csv"
    version = "demo-csv/1"

    def parse(self, data: bytes) -> ParsedStatement:
        # TODO
        raise NotImplementedError
