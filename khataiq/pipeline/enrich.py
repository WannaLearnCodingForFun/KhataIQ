"""Derive channel, counterparty and the normalized narration from a statement row. Pure.

The counterparty key groups transactions with the same other party, which the cycle detector
and the reversal rule rely on. It is deliberately conservative: a UPI VPA (exact), else a
cleaned-up name from a known narration layout, else None. None means "unknown", never a guess.
"""

from __future__ import annotations

import re

from khataiq.core.ledger import normalize_narration

# A VPA's local part may contain '-', but banks also use '-' as a field separator
# ('UPI-RAMESH KIRANA-ramesh@okicici-...'), so '-' is left out: a rare hyphenated VPA loses its
# prefix, instead of every hyphen-separated narration gluing a name onto the VPA.
_VPA = re.compile(r"[a-z0-9._]+@[a-z][a-z0-9]*", re.IGNORECASE)

# (channel, regex on the normalized narration)
_CHANNELS: list[tuple[str, re.Pattern[str]]] = [
    ("upi", re.compile(r"\bUPI\b")),
    ("neft", re.compile(r"\bNEFT\b")),
    ("rtgs", re.compile(r"\bRTGS\b")),
    ("imps", re.compile(r"\bIMPS\b")),
    ("ach", re.compile(r"\b(ACH|NACH|ECS)\b")),
    ("atm", re.compile(r"\bATM\b")),
    ("cash", re.compile(r"\bCASH\b")),
    ("pos", re.compile(r"\bPOS\b")),
    ("charges", re.compile(r"\b(CHARGES?|CHRG|AMC|GST)\b")),
    ("interest", re.compile(r"\bINT(EREST)?\b.*\bCR\b|\bINT\.?\s?PD\b")),
]

# Words that are part of the narration layout rather than a name.
_NOISE = {"UPI", "NEFT", "RTGS", "IMPS", "P2A", "P2M", "CR", "DR", "BY", "TO", "TRANSFER",
          "PAYMENT", "SALE", "REV", "REVERSAL", "REFUND", "RETURN", "RTN", "FAILED"}


def channel_of(narration_norm: str) -> str | None:
    for name, pattern in _CHANNELS:
        if pattern.search(narration_norm):
            return name
    return None


def counterparty_key(narration: str, channel: str | None) -> str | None:
    """'vpa:ramesh@okicici', 'name:SHREE SUPPLIERS', or None."""
    vpa = _VPA.search(narration)
    if vpa:
        return f"vpa:{vpa.group(0).lower()}"
    if channel in {"upi", "neft", "rtgs", "imps"}:
        name = _name_from_segments(normalize_narration(narration))
        if name:
            return f"name:{name}"
    return None


def _name_from_segments(norm: str) -> str | None:
    """The first segment (split on / - *) that looks like a name: letters and spaces, two or
    more characters, not a layout word, not an IFSC-like code."""
    for segment in re.split(r"[/*-]", norm):
        cleaned = " ".join(w for w in re.sub(r"[^A-Z ]", " ", segment).split()
                           if w not in _NOISE)
        if len(cleaned) >= 3 and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", segment.strip()):
            return cleaned
    return None
