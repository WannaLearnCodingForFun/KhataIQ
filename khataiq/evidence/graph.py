"""Graph algorithms for cycle detection: Tarjan's strongly connected components (iterative)
and bounded simple-cycle enumeration.

Why SCCs first: every directed cycle lies entirely inside one strongly connected component.
Tarjan finds all components in O(V + E); cycle search then only runs inside components with
two or more nodes, which for real ledgers are tiny compared with the whole graph.

Why iterative: Python's recursion limit (1000 by default) would crash a recursive Tarjan on a
long chain of counterparties.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from typing import TypeVar

N = TypeVar("N", bound=Hashable)


def strongly_connected_components(nodes: Iterable[N],
                                  edges: Mapping[N, Sequence[N]]) -> list[list[N]]:
    """Tarjan's algorithm with an explicit stack. Returns components in reverse topological
    order (a component is emitted after every component it can reach)."""
    index: dict[N, int] = {}
    lowlink: dict[N, int] = {}
    on_stack: set[N] = set()
    stack: list[N] = []
    components: list[list[N]] = []
    counter = 0

    for root in nodes:
        if root in index:
            continue
        # Each frame: (node, position of the next neighbour to look at).
        work: list[tuple[N, int]] = [(root, 0)]
        while work:
            node, position = work.pop()
            if position == 0:
                index[node] = lowlink[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            neighbours = edges.get(node, ())
            descended = False
            while position < len(neighbours):
                nxt = neighbours[position]
                position += 1
                if nxt not in index:
                    work.append((node, position))  # come back to the rest later
                    work.append((nxt, 0))
                    descended = True
                    break
                if nxt in on_stack:
                    lowlink[node] = min(lowlink[node], index[nxt])
            if descended:
                continue
            if lowlink[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
            if work:  # propagate our lowlink to the parent frame
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
    return components


def bounded_simple_cycles(component: Iterable[N], edges: Mapping[N, Sequence[N]],
                          max_length: int, limit: int, order: Mapping[N, int],
                          roots: Iterable[N] | None = None) -> list[list[N]]:
    """Simple cycles of at most max_length nodes inside one component, at most limit of them.

    Each cycle is found exactly once, rooted at its lowest node by `order`: a search from
    start s only visits nodes ordered after s (the idea behind Johnson's algorithm, without
    its blocking sets, which a depth bound of 4 doesn't need). With roots, only cycles whose
    lowest node is one of them are searched for.
    """
    members = set(component)
    starts = members if roots is None else members & set(roots)
    cycles: list[list[N]] = []
    for start in sorted(starts, key=order.__getitem__):
        floor = order[start]
        path = [start]
        on_path = {start}
        frames: list[int] = [0]  # next neighbour index for each node on the path
        while frames:
            node = path[-1]
            neighbours = edges.get(node, ())
            i = frames[-1]
            if i >= len(neighbours):
                frames.pop()
                on_path.discard(path.pop())
                continue
            frames[-1] = i + 1
            nxt = neighbours[i]
            if nxt == start and len(path) >= 2:
                cycles.append(list(path))
                if len(cycles) >= limit:
                    return cycles
            elif (nxt in members and nxt not in on_path and order[nxt] > floor
                  and len(path) < max_length):
                path.append(nxt)
                on_path.add(nxt)
                frames.append(0)
    return cycles
