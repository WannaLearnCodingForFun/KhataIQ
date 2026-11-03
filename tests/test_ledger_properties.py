"""Hypothesis property tests for khataiq/core/ledger.py.

These complement the example-based spec in test_ledger.py: instead of a fixed
seed, Hypothesis generates inputs and shrinks any failure to a minimal case.
"""

from dataclasses import replace
from datetime import date, timedelta

from hypothesis import given
from hypothesis import strategies as st

from khataiq.core.ledger import (
    Txn,
    fingerprint,
    match_self_transfers,
    normalize_narration,
    reconcile,
)

D = date(2026, 10, 1)

directions = st.sampled_from(["debit", "credit"])


@st.composite
def balanced_statements(draw):
    """(opening, closing, rows) where every running balance is correct."""
    opening = draw(st.integers(-10_00_000_00, 10_00_000_00))
    steps = draw(st.lists(st.tuples(st.integers(1, 5_00_000_00), directions), max_size=40))
    bal, rows = opening, []
    for i, (amt, direction) in enumerate(steps):
        bal += amt if direction == "credit" else -amt
        rows.append(Txn(i, 1, D + timedelta(days=i // 3), amt, direction, bal, "UPI/X"))
    return opening, bal, rows


@st.composite
def transfer_batches(draw):
    """Small, collision-heavy batches so the matcher sees plenty of ambiguity."""
    n = draw(st.integers(0, 25))
    return [
        Txn(
            id=i,
            account_id=draw(st.integers(1, 3)),
            txn_date=D + timedelta(days=draw(st.integers(0, 10))),
            amount_paise=draw(st.sampled_from([1_000_00, 2_500_00, 5_000_00])),
            direction=draw(directions),
            balance_after_paise=0,
            narration="X",
            utr=draw(st.sampled_from([None, None, "A", "B"])),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------- narration

@given(st.text())
def test_normalize_is_idempotent(raw):
    once = normalize_narration(raw)
    assert normalize_narration(once) == once


@given(st.text())
def test_normalized_text_has_no_stray_spaces(raw):
    out = normalize_narration(raw)
    assert out == out.strip()
    assert "  " not in out
    assert " /" not in out and "/ " not in out


# ---------------------------------------------------------------- fingerprint

@given(st.integers(), st.integers())
def test_fingerprint_ignores_db_id(id_a, id_b):
    row = Txn(id_a, 1, D, 500_00, "debit", 9_500_00, "UPI/ZOMATO")
    assert fingerprint(row) == fingerprint(replace(row, id=id_b))


# ---------------------------------------------------------------- reconcile

@given(balanced_statements())
def test_balanced_statements_always_reconcile(stmt):
    opening, closing, rows = stmt
    assert reconcile(opening, closing, rows).ok


@given(balanced_statements(), st.data())
def test_any_single_amount_tamper_is_caught_at_that_row(stmt, data):
    opening, closing, rows = stmt
    if not rows:
        return
    i = data.draw(st.integers(0, len(rows) - 1))
    bump = data.draw(st.integers(1, 999))
    rows[i] = replace(rows[i], amount_paise=rows[i].amount_paise + bump)
    r = reconcile(opening, closing, rows)
    assert not r.ok and r.reason == "running_balance" and r.break_index == i


@given(balanced_statements(), st.integers(1, 999))
def test_wrong_closing_balance_is_caught(stmt, delta):
    opening, closing, rows = stmt
    r = reconcile(opening, closing + delta, rows)
    assert (r.ok, r.reason, r.expected_paise) == (False, "closing_balance", closing)


# ---------------------------------------------------------------- matching

@given(transfer_batches())
def test_matches_are_valid_sorted_and_verified_disjoint(txns):
    by_id = {x.id: x for x in txns}
    out = match_self_transfers(txns)
    assert out == sorted(out, key=lambda m: (m.debit_id, m.credit_id))
    verified_ids = []
    for m in out:
        d, c = by_id[m.debit_id], by_id[m.credit_id]
        assert d.direction == "debit" and c.direction == "credit"
        assert d.account_id != c.account_id
        assert d.amount_paise == c.amount_paise
        assert abs((c.txn_date - d.txn_date).days) <= 2
        if m.level == "verified":
            verified_ids += [m.debit_id, m.credit_id]
    assert len(verified_ids) == len(set(verified_ids))


@given(transfer_batches(), st.randoms(use_true_random=False))
def test_matching_does_not_depend_on_input_order(txns, rng):
    shuffled = list(txns)
    rng.shuffle(shuffled)
    assert match_self_transfers(shuffled) == match_self_transfers(txns)


@given(transfer_batches())
def test_verified_txns_never_also_appear_as_unresolved(txns):
    out = match_self_transfers(txns)
    verified = {i for m in out if m.level == "verified" for i in (m.debit_id, m.credit_id)}
    for m in out:
        if m.level == "unresolved":
            assert m.debit_id not in verified and m.credit_id not in verified
