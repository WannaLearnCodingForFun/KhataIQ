"""Spec for khataiq/core/ledger.py. Do not edit these to make them pass.

Run:  pytest -q
Stretch goal (week 3): rewrite the random-based property tests with Hypothesis.
"""

import random
from datetime import date, timedelta

import pytest

from khataiq.core.ledger import (
    Match,
    Txn,
    fingerprint,
    match_self_transfers,
    normalize_narration,
    reconcile,
)

D = date(2026, 10, 1)


def t(id, acct, day, amt, direction, bal=0, narr="X", utr=None):
    return Txn(id, acct, D + timedelta(days=day), amt, direction, bal, narr, utr)


def balanced_statement(rng, n, opening=100_000):
    """Random statement whose running balances are all correct."""
    bal, rows = opening, []
    for i in range(n):
        amt = rng.randint(1, 5_000_00)
        direction = rng.choice(["debit", "credit"])
        bal += amt if direction == "credit" else -amt
        rows.append(t(i, 1, i // 3, amt, direction, bal, f"UPI/{rng.randint(1, 9)}"))
    return opening, bal, rows


# ---------------------------------------------------------------- narration

@pytest.mark.parametrize("raw, expected", [
    ("  upi / Zomato   123 ", "UPI/ZOMATO 123"),
    ("NEFT\tSALARY\nOCT", "NEFT SALARY OCT"),
    ("UPI/ZOMATO", "UPI/ZOMATO"),
    ("", ""),
])
def test_normalize_narration(raw, expected):
    assert normalize_narration(raw) == expected


# ---------------------------------------------------------------- fingerprint

def test_fingerprint_is_sha256_hex_and_deterministic():
    a = t(1, 1, 0, 500_00, "debit", 9_500_00, "UPI/ZOMATO")
    fp = fingerprint(a)
    assert len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)
    assert fp == fingerprint(a)


def test_fingerprint_ignores_db_id_and_narration_spacing():
    a = t(1, 1, 0, 500_00, "debit", 9_500_00, "UPI/ZOMATO")
    b = t(99, 1, 0, 500_00, "debit", 9_500_00, "  upi / zomato ")
    assert fingerprint(a) == fingerprint(b)


def test_identical_payments_same_day_differ_by_running_balance():
    first = t(1, 1, 0, 500_00, "debit", 9_500_00, "UPI/CHAI")
    second = t(2, 1, 0, 500_00, "debit", 9_000_00, "UPI/CHAI")
    assert fingerprint(first) != fingerprint(second)


@pytest.mark.parametrize("field_change", [
    dict(account_id=2), dict(amount_paise=501_00), dict(direction="credit"),
    dict(txn_date=D + timedelta(days=1)),
])
def test_fingerprint_changes_with_each_identity_field(field_change):
    from dataclasses import replace
    a = t(1, 1, 0, 500_00, "debit", 9_500_00, "UPI/ZOMATO")
    assert fingerprint(a) != fingerprint(replace(a, **field_change))


# ---------------------------------------------------------------- reconcile

def test_reconcile_ok():
    rows = [t(0, 1, 0, 1_000, "credit", 11_000), t(1, 1, 0, 3_000, "debit", 8_000)]
    assert reconcile(10_000, 8_000, rows) == reconcile(10_000, 8_000, rows)
    r = reconcile(10_000, 8_000, rows)
    assert r.ok and r.reason is None and r.break_index is None


def test_reconcile_reports_first_running_break():
    rows = [
        t(0, 1, 0, 1_000, "credit", 11_000),
        t(1, 1, 0, 3_000, "debit", 9_000),   # should be 8_000
        t(2, 1, 0, 1_000, "debit", 7_000),   # also wrong, but not first
    ]
    r = reconcile(10_000, 7_000, rows)
    assert (r.ok, r.reason, r.break_index) == (False, "running_balance", 1)
    assert (r.expected_paise, r.actual_paise) == (8_000, 9_000)


def test_reconcile_reports_closing_mismatch():
    rows = [t(0, 1, 0, 1_000, "credit", 11_000)]
    r = reconcile(10_000, 12_000, rows)
    assert (r.ok, r.reason, r.break_index) == (False, "closing_balance", None)
    assert (r.expected_paise, r.actual_paise) == (11_000, 12_000)


def test_reconcile_empty_statement():
    assert reconcile(5_000, 5_000, []).ok
    assert not reconcile(5_000, 4_000, []).ok


def test_property_balanced_statements_always_reconcile():
    rng = random.Random(7)
    for _ in range(300):
        o, c, rows = balanced_statement(rng, rng.randint(0, 40))
        assert reconcile(o, c, rows).ok


def test_property_any_single_tamper_is_caught():
    from dataclasses import replace
    rng = random.Random(11)
    for _ in range(300):
        o, c, rows = balanced_statement(rng, rng.randint(1, 40))
        i = rng.randrange(len(rows))
        rows[i] = replace(rows[i], amount_paise=rows[i].amount_paise + rng.randint(1, 999))
        r = reconcile(o, c, rows)
        assert not r.ok and r.break_index == i


# ---------------------------------------------------------------- matching

def test_simple_self_transfer_is_verified():
    txns = [t(1, 1, 0, 20_000_00, "debit"), t(2, 2, 1, 20_000_00, "credit")]
    assert match_self_transfers(txns) == [Match(1, 2, "verified")]


@pytest.mark.parametrize("credit", [
    t(2, 2, 3, 20_000_00, "credit"),   # outside 2-day window
    t(2, 1, 0, 20_000_00, "credit"),   # same account: not a transfer
    t(2, 2, 0, 19_999_99, "credit"),   # amount differs by 1 paisa
])
def test_non_candidates_are_ignored(credit):
    assert match_self_transfers([t(1, 1, 0, 20_000_00, "debit"), credit]) == []


def test_window_is_symmetric_credit_can_post_first():
    txns = [t(1, 1, 2, 5_000_00, "debit"), t(2, 2, 0, 5_000_00, "credit")]
    assert match_self_transfers(txns) == [Match(1, 2, "verified")]


def test_ambiguous_is_unresolved_never_guessed():
    txns = [
        t(1, 1, 0, 5_000_00, "debit"),
        t(2, 2, 0, 5_000_00, "credit"),
        t(3, 3, 1, 5_000_00, "credit"),
    ]
    assert match_self_transfers(txns) == [
        Match(1, 2, "unresolved"), Match(1, 3, "unresolved"),
    ]


def test_utr_resolves_ambiguity_and_frees_the_rest():
    txns = [
        t(1, 1, 0, 5_000_00, "debit", utr="U9"),
        t(2, 2, 0, 5_000_00, "credit"),
        t(3, 3, 1, 5_000_00, "credit", utr="U9"),
    ]
    assert match_self_transfers(txns) == [Match(1, 3, "verified")]


def test_property_verified_matches_are_valid_and_disjoint():
    rng = random.Random(3)
    for _ in range(200):
        txns = [
            t(i, rng.randint(1, 3), rng.randint(0, 10),
              rng.choice([1_000_00, 2_500_00, 5_000_00]),
              rng.choice(["debit", "credit"]),
              utr=rng.choice([None, None, "A", "B"]))
            for i in range(rng.randint(0, 25))
        ]
        by_id = {x.id: x for x in txns}
        out = match_self_transfers(txns)
        assert out == sorted(out, key=lambda m: (m.debit_id, m.credit_id))
        used = []
        for m in out:
            d, c = by_id[m.debit_id], by_id[m.credit_id]
            assert d.direction == "debit" and c.direction == "credit"
            assert d.account_id != c.account_id
            assert d.amount_paise == c.amount_paise
            assert abs((c.txn_date - d.txn_date).days) <= 2
            if m.level == "verified":
                used += [m.debit_id, m.credit_id]
        assert len(used) == len(set(used)), "a txn was verified twice"
