from datetime import date

import pytest

from khataiq.pipeline.parsers import get_parser
from khataiq.pipeline.parsers.demo_csv import render_demo_csv


def test_render_then_parse_round_trips():
    rows = [(date(2026, 10, 1), "UPI/412345678901/A/a@okaxis", 0, 150_000),
            (date(2026, 10, 2), 'NEFT DR-X, "Y"', 50_025, 0)]
    s = get_parser("demo", "csv").parse(render_demo_csv(1_000_00, rows))
    assert (s.opening_paise, s.closing_paise) == (100_000, 199_975)
    assert [(r.narration, r.amount_paise, r.direction) for r in s.rows] == [
        ("UPI/412345678901/A/a@okaxis", 150_000, "credit"), ('NEFT DR-X, "Y"', 50_025, "debit")]


def test_render_rejects_overdraft_and_ambiguous_rows():
    with pytest.raises(ValueError):
        render_demo_csv(100, [(date(2026, 10, 1), "X", 200, 0)])
    with pytest.raises(ValueError):
        render_demo_csv(100, [(date(2026, 10, 1), "X", 10, 10)])
