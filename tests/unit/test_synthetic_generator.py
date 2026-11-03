"""M7.1: the synthetic generator is deterministic and its statements are valid."""

from collections import Counter

import pytest

from khataiq.core.ledger import Txn, reconcile
from khataiq.pipeline.parsers import get_parser
from synthetic.generator import GenConfig, generate

PARSER = get_parser("demo", "csv")


def test_same_seed_same_bytes():
    a, b = generate(11), generate(11)
    assert [s.csv for s in a.statements] == [s.csv for s in b.statements]
    assert a.ground_truth == b.ground_truth
    assert generate(12).statements[0].csv != a.statements[0].csv


@pytest.mark.parametrize("seed", range(8))
def test_every_statement_parses_and_reconciles(seed):
    for st in generate(seed).statements:
        parsed = PARSER.parse(st.csv)
        txns = [Txn(i, 1, r.txn_date, r.amount_paise, r.direction, r.balance_after_paise,
                    r.narration, r.utr) for i, r in enumerate(parsed.rows)]
        assert reconcile(parsed.opening_paise, parsed.closing_paise, txns).ok


@pytest.mark.parametrize("seed", range(8))
def test_ground_truth_refs_point_at_real_lines(seed):
    business = generate(seed)
    lines = {f"a{s.account_index}:s{s.statement_index}:{line}"
             for s in business.statements for line in s.lines.values()}
    truth = business.ground_truth
    refs = [r for pair in truth["self_transfers"] for r in pair[:2]]
    refs += [r for pair in truth["reversals"] + truth["duplicates"] for r in pair]
    refs += [r for cycle in truth["cycles"] for r in cycle] + truth["loans"]
    assert set(refs) <= lines
    assert set(truth["labels"]) <= lines


def test_account_zero_has_two_overlapping_statements():
    business = generate(3)
    first, second = [s for s in business.statements if s.account_index == 0]
    shared = set(first.uids) & set(second.uids)
    assert len(shared) > 10
    assert len(business.ground_truth["duplicates"]) >= 1


def test_planted_event_rates_over_many_businesses():
    config = GenConfig()
    businesses = [generate(seed, config) for seed in range(30)]
    multi = [b for b in businesses if len(b.accounts) > 1]
    for b in multi:
        verified = [t for t in b.ground_truth["self_transfers"] if t[2] == "verified"]
        assert len(verified) >= config.self_transfers_per_month * config.months
    assert all(len(b.ground_truth["reversals"]) == config.reversals_per_month * config.months
               for b in businesses)
    with_cycles = sum(1 for b in businesses if b.ground_truth["cycles"])
    assert 4 <= with_cycles <= 18  # about one in three
    labels = Counter(label for b in businesses for label in b.ground_truth["labels"].values())
    assert {"sales", "rent", "salary_paid", "emi", "loan_in", "refund"} <= set(labels)
