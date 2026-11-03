"""CYCLE v1: money that leaves the business and comes back through counterparties.

For each 30-day window (windows start on the 1st and the 16th of every month, so they overlap):
  1. Build a directed graph. Nodes are the business's accounts ('ACCT:<id>') and counterparty
     keys. A debit is an edge ACCT -> counterparty, a credit counterparty -> ACCT, and a
     self-transfer between two of the business's accounts is ACCT -> ACCT. Edges carry the
     total paise, the transaction ids and dates. Rows without a counterparty key can't be
     placed and are left out; self-transfer legs never become counterparty edges, and legs of
     verified reversals are left out (a refunded payment is a round trip that is already
     explained, not circular money).
  2. Strongly connected components (iterative Tarjan).
  3. In each component with 2+ nodes: simple cycles through an account node, up to 4 hops.
     At most 50 are *reported* per component; the search itself has a larger work budget, so
     cycles that can never be reported (account <-> account loops) can't use up the 50.
  4. A cycle is reported when money out (account -> counterparty edges on it) and money back
     (counterparty -> account edges) are within 10% of each other and the money out is at
     least Rs 10,000.

A cycle is a reason for an officer to look, never a fraud verdict: a supplier who is also a
customer forms one too.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from khataiq.evidence.graph import bounded_simple_cycles, strongly_connected_components
from khataiq.evidence.types import LedgerTxn

RULE_ID, RULE_VERSION = "CYCLE", 1
WINDOW_DAYS = 30
MAX_HOPS = 4
MAX_CYCLES_PER_COMPONENT = 50  # reported
SEARCH_BUDGET_PER_COMPONENT = 5_000  # enumerated, to keep a pathological graph bounded
MIN_TOTAL_PAISE = 1_000_000
TOLERANCE_PERCENT = 10


@dataclass
class Edge:
    total_paise: int = 0
    txn_ids: list[int] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)


@dataclass(frozen=True)
class CycleFinding:
    window_start: date
    window_end: date  # exclusive
    path: tuple[str, ...]  # nodes in order; the last node links back to the first
    out_paise: int
    back_paise: int
    txn_ids: tuple[int, ...]  # every row on the cycle's edges
    external_txn_ids: tuple[int, ...]  # rows on account <-> counterparty edges: its identity
    first_date: date
    last_date: date


def account_node(account_id: int) -> str:
    return f"ACCT:{account_id}"


def window_starts(first: date, last: date) -> list[date]:
    """The 1st and 16th of every month whose 30-day window touches [first, last]."""
    starts = []
    earliest = first - timedelta(days=WINDOW_DAYS)
    year, month = earliest.year, earliest.month
    while date(year, month, 1) <= last:
        for day in (1, 16):
            start = date(year, month, day)
            if start <= last and start + timedelta(days=WINDOW_DAYS) > first:
                starts.append(start)
        month = month % 12 + 1
        year += month == 1
    return starts


def find_cycles(txns: list[LedgerTxn], self_transfers: list[tuple[int, int]],
                explained: frozenset[int] = frozenset()) -> list[CycleFinding]:
    """self_transfers: (debit_id, credit_id) pairs from SELF_TRANSFER links (any level).
    explained: ids already accounted for by another rule (legs of verified reversals)."""
    if not txns:
        return []
    by_id = {t.id: t for t in txns}
    internal = {i for pair in self_transfers for i in pair} | explained
    findings: dict[tuple[int, ...], CycleFinding] = {}
    first, last = min(t.txn_date for t in txns), max(t.txn_date for t in txns)
    for start in window_starts(first, last):
        end = start + timedelta(days=WINDOW_DAYS)
        graph = _window_graph(by_id, internal, self_transfers, start, end)
        for finding in _window_cycles(graph, start, end):
            # The same flow seen from two overlapping windows (perhaps with different internal
            # transfers attached) is reported once, by its counterparty legs.
            findings.setdefault(finding.external_txn_ids, finding)
    return sorted(findings.values(), key=lambda f: (f.window_start, f.txn_ids))


def build_graph(txns: list[LedgerTxn], self_transfers: list[tuple[int, int]], start: date,
                end: date, explained: frozenset[int] = frozenset()) -> dict[tuple[str, str], Edge]:
    """The money-flow graph for [start, end): what the cycle rule sees, and what the evidence
    view draws."""
    by_id = {t.id: t for t in txns}
    internal = {i for pair in self_transfers for i in pair} | explained
    return _window_graph(by_id, internal, self_transfers, start, end)


def _window_graph(by_id: dict[int, LedgerTxn], internal: set[int],
                  self_transfers: list[tuple[int, int]], start: date,
                  end: date) -> dict[tuple[str, str], Edge]:
    graph: dict[tuple[str, str], Edge] = defaultdict(Edge)

    def add(u: str, v: str, t: LedgerTxn) -> None:
        edge = graph[(u, v)]
        edge.total_paise += t.amount_paise
        edge.txn_ids.append(t.id)
        edge.dates.append(t.txn_date)

    for t in by_id.values():
        if not start <= t.txn_date < end or t.id in internal or t.counterparty_key is None:
            continue
        if t.is_credit:
            add(t.counterparty_key, account_node(t.account_id), t)
        else:
            add(account_node(t.account_id), t.counterparty_key, t)
    for debit_id, credit_id in self_transfers:
        debit, credit = by_id.get(debit_id), by_id.get(credit_id)
        if debit and credit and start <= debit.txn_date < end and start <= credit.txn_date < end:
            add(account_node(debit.account_id), account_node(credit.account_id), debit)
            graph[(account_node(debit.account_id),
                   account_node(credit.account_id))].txn_ids.append(credit.id)
    return graph


def _window_cycles(graph: dict[tuple[str, str], Edge], start: date,
                   end: date) -> list[CycleFinding]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for u, v in sorted(graph):
        adjacency[u].append(v)
    nodes = sorted({n for edge in graph for n in edge})
    # Account nodes sort first, so every cycle through an account is rooted at an account.
    order = {n: i for i, n in enumerate(sorted(nodes, key=lambda n: (not n.startswith("ACCT:"),
                                                                     n)))}
    found = []
    for component in strongly_connected_components(nodes, adjacency):
        accounts = [n for n in component if n.startswith("ACCT:")]
        if len(component) < 2 or not accounts:
            continue
        reported = 0
        # Accounts sort first, so rooting at accounts finds exactly the cycles through one.
        for cycle in bounded_simple_cycles(component, adjacency, MAX_HOPS,
                                           SEARCH_BUDGET_PER_COMPONENT, order, roots=accounts):
            finding = _assess(cycle, graph, start, end)
            if finding is not None:
                found.append(finding)
                reported += 1
                if reported >= MAX_CYCLES_PER_COMPONENT:
                    break
    return found


def _assess(cycle: list[str], graph: dict[tuple[str, str], Edge], start: date,
            end: date) -> CycleFinding | None:
    if not cycle[0].startswith("ACCT:"):
        return None
    hops = list(zip(cycle, cycle[1:] + cycle[:1], strict=True))
    out = sum(graph[h].total_paise for h in hops
              if h[0].startswith("ACCT:") and not h[1].startswith("ACCT:"))
    back = sum(graph[h].total_paise for h in hops
               if not h[0].startswith("ACCT:") and h[1].startswith("ACCT:"))
    if out < MIN_TOTAL_PAISE or back == 0:
        return None
    if abs(out - back) * 100 > TOLERANCE_PERCENT * max(out, back):
        return None
    ids = tuple(sorted({i for h in hops for i in graph[h].txn_ids}))
    external = tuple(sorted({i for h in hops for i in graph[h].txn_ids
                             if h[0].startswith("ACCT:") != h[1].startswith("ACCT:")}))
    dates = [d for h in hops for d in graph[h].dates]
    return CycleFinding(start, end, tuple(cycle), out, back, ids, external, min(dates),
                        max(dates))


def describe(finding: CycleFinding) -> str:
    path = " -> ".join((*finding.path, finding.path[0]))
    return (f"Money went round {path}: {finding.out_paise} paise out, {finding.back_paise} "
            f"paise back, {finding.first_date.isoformat()} to {finding.last_date.isoformat()}")

