"""Rupee formatting for sentences the server writes (flag summaries). The API's numbers stay
integer paise; this is only for human-readable text."""

from __future__ import annotations


def inr(paise: int) -> str:
    """12345678 -> '₹1,23,456.78'; whole rupees drop the paise: 9000000 -> '₹90,000'.
    Indian digit grouping: the last three digits, then groups of two."""
    sign = "-" if paise < 0 else ""
    rupees, rest = divmod(abs(paise), 100)
    digits = str(rupees)
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    grouped = ",".join([*groups, tail]) if groups else tail
    return f"{sign}₹{grouped}" + (f".{rest:02d}" if rest else "")
