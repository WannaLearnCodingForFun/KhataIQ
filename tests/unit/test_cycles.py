"""M5.3: Tarjan SCC, bounded cycle enumeration, and the CYCLE rule."""

import random
import time
from itertools import permutations

import pytest

from khataiq.evidence.cycles import find_cycles
from khataiq.evidence.graph import bounded_simple_cycles, strongly_connected_components
from tests.unit.evidence_helpers import lt


def random_graph(n: int, m: int, seed: int) -> dict[int, list[int]]:
    rng = random.Random(seed)
    edges: dict[int, set[int]] = {i: set() for i in range(n)}
    while sum(len(v) for v in edges.values()) < m:
        a, b = rng.randrange(n), rng.randrange(n)
        if a != b:
            edges[a].add(b)
    return {k: sorted(v) for k, v in edges.items()}


def reachable(edges, start):
    seen, todo = {start}, [start]
    while todo:
        for nxt in edges.get(todo.pop(), []):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


@pytest.mark.parametrize("seed", range(20))
def test_tarjan_matches_brute_force(seed):
    edges = random_graph(12, 20, seed)
    reach = {n: reachable(edges, n) for n in edges}
    expected = {frozenset(m for m in edges if m in reach[n] and n in reach[m]) for n in edges}
    got = {frozenset(c) for c in strongly_connected_components(list(edges), edges)}
    assert got == expected


def test_tarjan_survives_a_long_chain():
    n = 50_000  # far beyond Python's recursion limit
    edges = {i: [i + 1] for i in range(n - 1)}
    edges[n - 1] = [0]
    components = strongly_connected_components(list(range(n)), edges)
    assert len(components) == 1 and len(components[0]) == n


@pytest.mark.parametrize("seed", range(10))
def test_cycle_enumeration_matches_brute_force(seed):
    edges = random_graph(7, 14, seed)
    order = {n: n for n in edges}
    got = {tuple(c) for c in bounded_simple_cycles(list(edges), edges, 4, 10_000, order)}
    expected = set()
    for length in range(2, 5):
        for path in permutations(edges, length):
            if path[0] == min(path) and all(path[(i + 1) % length] in edges[path[i]]
                                            for i in range(length)):
                expected.add(path)
    assert got == expected


def test_dag_has_no_cycles():
    edges = {i: [j for j in range(i + 1, 30)] for i in range(30)}
    assert all(len(c) == 1 for c in strongly_connected_components(list(edges), edges))
    assert bounded_simple_cycles(list(edges), edges, 4, 50, {n: n for n in edges}) == []


def test_ten_thousand_edge_graph_is_fast():
    edges = random_graph(2_000, 10_000, seed=99)
    order = {n: n for n in edges}
    started = time.perf_counter()
    for component in strongly_connected_components(list(edges), edges):
        if len(component) > 1:
            bounded_simple_cycles(component, edges, 4, 50, order)
    assert time.perf_counter() - started < 2.0


# ------------------------------------------------------------------ the CYCLE rule

def round_trip(out_amount, back_amount, back_day=10, cp="vpa:x@ybl"):
    out = lt(account=1, day=2, direction="debit", amount=out_amount, cp=cp)
    back = lt(account=1, day=back_day, amount=back_amount, cp=cp)
    return out, back


def test_round_trip_within_tolerance_is_found():
    out, back = round_trip(2_000_000, 1_900_000)
    [finding] = find_cycles([out, back], [])
    assert finding.path == ("ACCT:1", "vpa:x@ybl")
    assert (finding.out_paise, finding.back_paise) == (2_000_000, 1_900_000)
    assert finding.txn_ids == tuple(sorted((out.id, back.id)))


@pytest.mark.parametrize("out_amount, back_amount", [
    (2_000_000, 1_700_000),   # 15% apart
    (900_000, 900_000),       # below Rs 10,000
])
def test_round_trip_outside_rules_is_ignored(out_amount, back_amount):
    assert find_cycles(list(round_trip(out_amount, back_amount)), []) == []


def test_money_back_after_the_window_is_ignored():
    out, back = round_trip(2_000_000, 2_000_000, back_day=45)
    assert find_cycles([out, back], []) == []


def test_four_hop_cycle_through_two_accounts_and_two_counterparties():
    a_out = lt(account=1, day=1, direction="debit", amount=3_000_000, cp="name:ALPHA")
    a_back = lt(account=2, day=5, amount=3_000_000, cp="name:ALPHA")
    b_out = lt(account=2, day=6, direction="debit", amount=2_900_000, cp="name:BETA")
    b_back = lt(account=1, day=9, amount=2_950_000, cp="name:BETA")
    findings = find_cycles([a_out, a_back, b_out, b_back], [])
    assert [f.path for f in findings] == [("ACCT:1", "name:ALPHA", "ACCT:2", "name:BETA")]
    assert findings[0].out_paise == 5_900_000 and findings[0].back_paise == 5_950_000


def test_self_transfer_legs_become_account_edges_not_counterparty_edges():
    out = lt(account=1, day=1, direction="debit", amount=2_000_000, cp="name:ALPHA")
    back = lt(account=2, day=3, amount=2_000_000, cp="name:ALPHA")
    move_d = lt(account=2, day=4, direction="debit", amount=2_000_000, cp="name:OWNER")
    move_c = lt(account=1, day=4, amount=2_000_000, cp="name:OWNER")
    [finding] = find_cycles([out, back, move_d, move_c], [(move_d.id, move_c.id)])
    assert finding.path == ("ACCT:1", "name:ALPHA", "ACCT:2")
    assert set(finding.txn_ids) == {out.id, back.id, move_d.id, move_c.id}


def test_unknown_counterparties_are_left_out():
    out = lt(day=1, direction="debit", amount=2_000_000, cp=None)
    back = lt(day=2, amount=2_000_000, cp=None)
    assert find_cycles([out, back], []) == []


def test_overlapping_windows_report_a_cycle_once():
    out, back = round_trip(2_000_000, 2_000_000, back_day=8)  # inside two windows
    assert len(find_cycles([out, back], [])) == 1


def test_a_verified_refund_is_not_a_cycle():
    out, back = round_trip(2_000_000, 2_000_000, back_day=4)
    assert len(find_cycles([out, back], [])) == 1
    assert find_cycles([out, back], [], frozenset({out.id, back.id})) == []


def test_cycles_that_fail_the_amount_test_do_not_use_up_the_cap():
    """60 round trips that can never be reported (money back is far off money out) are found
    before the real one in search order; they must not use up the 50 reported cycles."""
    from khataiq.evidence import cycles as cycle_rule

    rows = []
    for i in range(60):
        cp = f"name:AA{i:02d}"  # sorts before ALPHA, so the search meets these first
        rows.append(lt(account=1, day=1, direction="debit", amount=5_000_000, cp=cp))
        rows.append(lt(account=1, day=2, amount=100_000, cp=cp))
    out = lt(account=1, day=2, direction="debit", amount=2_000_000, cp="name:ALPHA")
    back = lt(account=1, day=6, amount=2_000_000, cp="name:ALPHA")
    findings = cycle_rule.find_cycles(rows + [out, back], [])
    assert [f.path for f in findings] == [("ACCT:1", "name:ALPHA")]
