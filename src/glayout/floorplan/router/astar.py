"""Bidirectional A* from a new pin to the part of its net already routed (paper Eq. 3-5).

    D(n,k) = |dx| + |dy| + c_via·|dz|                              (Eq. 3)
    g(n)   = g(k) + D(n,k) + c_DRC·[n used by another net] + H(n)  (Eq. 4)
    h(n)   = D(t,n)·(1+q),  q = 1e-4
    f(n)   = g + h            if g < h
           = (g + (2κ-1)h)/κ  otherwise, κ = 3                     (Eq. 5)

H(n) is the history cost that rip-up and reroute raises on contested nodes.
"""
from __future__ import annotations

import heapq
import itertools
import math
from typing import Callable, Iterable, Optional

from glayout.floorplan.router.grid import RoutingGrid


def step_distance(grid: RoutingGrid, a: tuple, b: tuple) -> float:
    """D(a, b): Manhattan distance plus c_via per layer change (Eq. 3)."""
    (ax, ay), (bx, by) = grid.xy(a), grid.xy(b)
    return abs(ax - bx) + abs(ay - by) + grid.t.c_via * abs(grid.layer(a) - grid.layer(b))


def f_cost(g: float, h: float, kappa: float) -> float:
    """Search priority (Eq. 5): g + h until g reaches h, then (g + (2κ-1)h)/κ.

    The second form weights the remaining distance more than the cost so far, so a long
    search leans toward its goal.
    """
    return g + h if g < h else (g + (2 * kappa - 1) * h) / kappa


def _tree_order(target_tree: Iterable[tuple]) -> list[tuple]:
    """The target tree in a fixed order: grid nodes (by layer, column, row), then pin nodes by index.

    The order is the heap's tie-break. A set's order follows string hashing (pin nodes are
    ("P", k)), which changes with every interpreter, and so did the routes; sort it instead.
    """
    return sorted(target_tree, key=lambda n: (1, n[1], 0, 0) if n[0] == "P" else (0, *n))


class _Frontier:
    """One direction of the search: cost so far, parents, open heap, goal and closed set."""

    __slots__ = ("g", "parent", "heap", "goal", "closed")

    def __init__(self, starts: list[tuple], goal: tuple, h: Callable[[tuple, tuple], float], kappa: float):
        """Open every start at cost 0; heap entries are (f, tie-break counter, node)."""
        self.g = {s: 0.0 for s in starts}
        self.parent = {s: None for s in starts}
        self.heap = [(f_cost(0.0, h(s, goal), kappa), k, s) for k, s in enumerate(starts)]
        heapq.heapify(self.heap)
        self.goal = goal
        self.closed: set[tuple] = set()


def _stitch(fwd: _Frontier, bwd: _Frontier, u: tuple) -> list[tuple]:
    """The path source..u from the forward parents, continued u..tree by the backward parents."""
    path, n = [], u
    while n is not None:
        path.append(n)
        n = fwd.parent[n]
    path.reverse()
    n = bwd.parent[u]
    while n is not None:
        path.append(n)
        n = bwd.parent[n]
    return path


def bidirectional_astar(grid: RoutingGrid, net: str, source: tuple, target_tree: set[tuple], target_hint: tuple,
                        occ: dict[tuple, set[str]], hist: dict[tuple, float]) -> Optional[list[tuple]]:
    """Path from ``source`` to any node of ``target_tree`` (paper Eq. 3-5), or None if there is none.

    The forward search starts at ``source`` and heads for ``target_hint`` (the pin's parent in
    the net's spanning tree); the backward search starts from every tree node at once and
    heads for ``source``. They take turns, one node each, until one closes a node the other
    has reached. ``occ`` says which nets use each node; ``hist`` is the history cost H.
    """
    t = grid.t

    def step_cost(a: tuple, b: tuple) -> float:
        """Cost of entering ``b`` from ``a`` (Eq. 4)."""
        c = step_distance(grid, a, b) + hist.get(b, 0.0)
        others = occ.get(b)
        if others and (others - {net}):
            c += t.c_drc
        return c

    def h(n: tuple, goal: tuple) -> float:
        """Heuristic: D to the goal, raised by a factor (1+q) so ties go toward the goal."""
        return step_distance(grid, n, goal) * (1 + t.q)

    if source in target_tree:
        return [source]
    fwd = _Frontier([source], target_hint, h, t.kappa)
    bwd = _Frontier(_tree_order(target_tree), source, h, t.kappa)
    sides = (fwd, bwd)
    counter = itertools.count(len(target_tree) + 1)
    turn = 0
    while fwd.heap or bwd.heap:
        s = sides[turn] if sides[turn].heap else sides[1 - turn]    # take turns; go on alone if one ran dry
        o = bwd if s is fwd else fwd
        _, _, u = heapq.heappop(s.heap)
        turn = 1 - turn
        if u in s.closed:
            continue
        s.closed.add(u)
        if u in o.g:
            return _stitch(fwd, bwd, u)       # meet: forward(source..u) + backward(u..tree)
        gu = s.g[u]
        for v in grid.neighbours(u):
            if not grid.node_ok(v, net) or not grid.edge_ok(u, v, net):
                continue
            # the backward search walks edges in reverse; costs are symmetric except H(n),
            # which is charged on the node entered in the forward direction
            gv = gu + (step_cost(u, v) if s is fwd else step_cost(v, u))
            if gv < s.g.get(v, math.inf) - 1e-12:
                s.g[v] = gv
                s.parent[v] = u
                heapq.heappush(s.heap, (f_cost(gv, h(v, s.goal), t.kappa), next(counter), v))
    return None
