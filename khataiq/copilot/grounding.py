"""Grounding checker: is every citation and every rupee figure in an answer backed by data
the tools returned in this turn? Pure: no I/O.

Rules (docs/specs/copilot.md):
  1. Every cited id must appear in a tool result from this turn (with the same type).
  2. Every rupee amount in the answer must equal a value in the *cited* rows, or a sum or
     difference of at most 3 of those values.
An amount written without paise ("₹12,346") may be rounded: it matches a value within
half a rupee. An amount with paise must match exactly.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import combinations, product

# ₹12,345  ₹12,345.50  ₹ 1,23,456  Rs. 500 is not accepted: the format is fixed by the prompt.
_RUPEES = re.compile(r"₹\s?(\d[\d,]*)(?:\.(\d{1,2}))?")


@dataclass(frozen=True)
class Citation:
    type: str  # "txn" | "metric"
    id: int


@dataclass
class Evidence:
    """Rows the tools returned this turn, by (type, id), each with its paise values."""

    rows: dict[tuple[str, int], tuple[int, ...]] = field(default_factory=dict)

    def add(self, row_type: str, row_id: int, values: Iterable[int]) -> None:
        current = self.rows.get((row_type, row_id), ())
        self.rows[(row_type, row_id)] = tuple(sorted(set(current) | set(values)))


@dataclass(frozen=True)
class GroundingResult:
    ok: bool
    problems: tuple[str, ...]


def rupee_amounts(answer: str) -> list[tuple[str, int, bool]]:
    """(as written, paise, exact?) for every ₹ figure in the text."""
    found = []
    for match in _RUPEES.finditer(answer):
        rupees = int(match.group(1).replace(",", ""))
        fraction = match.group(2)
        paise = rupees * 100 + (int(fraction.ljust(2, "0")) if fraction else 0)
        found.append((match.group(0), paise, fraction is not None))
    return found


def _reachable(target: int, values: list[int], exact: bool) -> bool:
    """Is target one cited value, or a signed sum of 2 or 3 *different* cited values?
    (Each value may be used once: one ₹25,000 row doesn't prove ₹50,000.)"""
    tolerance = 0 if exact else 50
    for size in range(1, 4):
        for chosen in combinations(values, size):
            for signs in product((1, -1), repeat=size):
                total = sum(sign * value for sign, value in zip(signs, chosen, strict=True))
                if abs(total - target) <= tolerance:
                    return True
    return False


def check(answer: str, citations: list[Citation],
          evidence: Evidence | Mapping[tuple[str, int], tuple[int, ...]]) -> GroundingResult:
    rows = evidence.rows if isinstance(evidence, Evidence) else evidence
    problems = []
    for c in citations:
        if (c.type, c.id) not in rows:
            problems.append(f"citation {c.type}:{c.id} was not returned by any tool in this turn")
    cited = {(c.type, c.id) for c in citations}
    cited_values = [v for key in sorted(cited) for v in rows.get(key, ())]
    for written, paise, exact in rupee_amounts(answer):
        if not cited_values:
            problems.append(f"{written} is stated but nothing is cited")
        elif not _reachable(paise, cited_values, exact):
            problems.append(f"{written} doesn't match the cited rows (or a sum/difference of up "
                            "to 3 of their values)")
    return GroundingResult(not problems, tuple(problems))
