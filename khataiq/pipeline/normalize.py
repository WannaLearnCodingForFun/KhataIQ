"""Turn the raw strings a bank statement contains into typed values.

Rules for this file:
  * Pure functions only. No database, no I/O.
  * Money is always int paise. Never go through float, not even for a moment.
  * Every bad input raises ValueError with a message saying what was wrong.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime

# Digits, then optionally a point and 1-2 more digits. Anchored by fullmatch, so signs,
# exponents ('1e3'), 'NaN', 'inf' and a third decimal all fail to match.
_AMOUNT_RE = re.compile(r"(\d+)(?:\.(\d{1,2}))?")

# A run of exactly 12 digits, not glued to another digit on either side.
_UTR_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")

DEFAULT_DATE_FORMATS: tuple[str, ...] = ("%d/%m/%Y", "%d-%b-%y")


def parse_amount(text: str) -> int:
    """Rupee amount as printed on a statement -> int paise.

    '1,23,456.78' -> 12345678     '500' -> 50000     '0.5' -> 50     ' 1,000.00 ' -> 100000

    * Surrounding whitespace is ignored. Commas are digit-group separators and are dropped
      wherever they are (Indian grouping places them differently from Western grouping).
    * At most 2 digits after the decimal point: '1.234' is an error (no fractional paise).
    * Errors: '', 'abc', '-5', '1.2.3', '1e3', 'NaN', 'inf'.

    The string is split into rupees and paise as text and each part converted with int(),
    so the value is exact. float('0.29') * 100 is 28.999999999999996, and Decimal() would
    accept 'NaN' and '1e3', which is why neither is used.
    """
    match = _AMOUNT_RE.fullmatch(text.strip().replace(",", ""))
    if match is None:
        raise ValueError(f"not a valid amount: {text!r}")
    rupees, fraction = match.group(1), match.group(2) or ""
    return int(rupees) * 100 + int(fraction.ljust(2, "0"))


def format_paise(paise: int) -> str:
    """int paise -> plain rupee string with exactly 2 decimals and no commas.

    12345678 -> '123456.78'    50 -> '0.50'    0 -> '0.00'    negative -> ValueError
    Property: parse_amount(format_paise(p)) == p for every p >= 0.
    """
    if paise < 0:
        raise ValueError(f"amount must not be negative: {paise}")
    rupees, rest = divmod(paise, 100)
    return f"{rupees}.{rest:02d}"


def parse_date(text: str, formats: Sequence[str] = DEFAULT_DATE_FORMATS) -> date:
    """Statement date -> date, trying each strptime format in order.

    With the default formats (surrounding whitespace ignored):
      '05/10/2026'  day/month/year   -> date(2026, 10, 5)
      '05-Oct-26'   day-Mon-yy       -> date(2026, 10, 5)

    Anything else (including ISO '2026-10-05' and impossible dates like '31/02/2026')
    raises ValueError. The format list is fixed per bank on purpose: '05/10/2026' is
    5 October in India and May 10 in the US, so the format is never guessed from the value.
    """
    cleaned = text.strip()
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date in any of {list(formats)}: {text!r}")


def extract_utr(narration: str) -> str | None:
    """Pull the 12-digit UPI/IMPS reference number (RRN) out of a narration.

    'UPI/412345678901/ZOMATO/zomato@hdfcbank' -> '412345678901'
    'IMPS/P2A/612345678901/RENT'              -> '612345678901'
    'NEFT CR-SBIN0001234-SHARMA TRADERS'      -> None

    Returns the FIRST run of exactly 12 digits that is not part of a longer run of digits
    (so a 16-digit card number is never mistaken for a reference). None if there is none.
    """
    match = _UTR_RE.search(narration)
    return match.group(0) if match else None
