"""Turn the raw strings a bank statement contains into typed values — YOU implement the TODOs.

Make tests/test_normalize.py pass:  pytest -q tests/test_normalize.py

Rules for this file:
  * Pure functions only. No database, no I/O.
  * Money is always int paise. Do NOT go through float, not even for a moment.
  * Every bad input raises ValueError with a message saying what was wrong.
"""

from __future__ import annotations

from datetime import date


def parse_amount(text: str) -> int:
    """Rupee amount as printed on a statement -> int paise.

    '1,23,456.78' -> 12345678     '500' -> 50000     '0.5' -> 50     ' 1,000.00 ' -> 100000

    * Surrounding whitespace is ignored. Commas are digit-group separators: drop them
      wherever they are (Indian grouping puts them in different places from Western).
    * At most 2 digits after the decimal point: '1.234' is an error (no fractional paise).
    * Errors: '', 'abc', '-5', '1.2.3', '1e3', 'NaN', 'inf'.
    Think: what does float('0.29') * 100 give you, and why does that rule out float here?
    Then: which of the error cases above would Python's Decimal() happily accept?
    """
    # TODO
    raise NotImplementedError


def format_paise(paise: int) -> str:
    """int paise -> plain rupee string with exactly 2 decimals and no commas.

    12345678 -> '123456.78'    50 -> '0.50'    0 -> '0.00'    negative -> ValueError
    Property: parse_amount(format_paise(p)) == p for every p >= 0.
    Hint: divmod.
    """
    # TODO
    raise NotImplementedError


def parse_date(text: str) -> date:
    """Statement date -> date. Supported formats (surrounding whitespace ignored):

      '05/10/2026'  day/month/year   -> date(2026, 10, 5)
      '05-Oct-26'   day-Mon-yy       -> date(2026, 10, 5)

    Anything else (including ISO '2026-10-05' and impossible dates like '31/02/2026')
    raises ValueError.
    Think: '05/10/2026' is 5 October in India and May 10 in the US. Why must a parser
    never guess the format from the value?
    """
    # TODO
    raise NotImplementedError


def extract_utr(narration: str) -> str | None:
    """Pull the 12-digit UPI/IMPS reference number (RRN) out of a narration.

    'UPI/412345678901/ZOMATO/zomato@hdfcbank' -> '412345678901'
    'IMPS/P2A/612345678901/RENT'              -> '612345678901'
    'NEFT CR-SBIN0001234-SHARMA TRADERS'      -> None

    Return the FIRST run of exactly 12 digits that is not part of a longer run of digits
    (so a 16-digit card number is never mistaken for a reference). None if there is none.
    """
    # TODO
    raise NotImplementedError
