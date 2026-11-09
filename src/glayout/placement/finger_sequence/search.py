"""Search for a finger sequence that is common-centroid and shares diffusion.

Steps (notes §2.7, steps 3-5):

1. Build the diffusion graph and its Euler lower bound on breaks.
2. Enumerate device orders: every distinct permutation when there are few,
   otherwise palindromes (which are common-centroid by construction), and a
   seeded random sample of those when even that is too many.
3. For each order, pick finger orientations with a dynamic program that
   minimises (breaks, drain contacts).
4. Score each candidate and rank.

The score is a weighted sum; the defaults make centroid error dominate, then
breaks, then drain balance, then the second moment (quadratic-gradient
mismatch), then total drain area.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterator, Mapping, Optional, Sequence

from glayout.placement.finger_sequence.model import (
    DeviceSpec, DiffusionGraph, Finger, FingerSequence, RowMetrics, check_shareable,
)
from glayout.util.process_table import ProcessTable, print_table

CENTROID_TOL = 1e-9


@dataclass
class SequenceWeights:
    centroid: float = 1000.0
    breaks: float = 100.0
    drain_imbalance: float = 50.0
    moment2: float = 1.0
    drain_contacts: float = 0.5

    def score(self, m: RowMetrics) -> float:
        return (self.centroid * m.centroid_error + self.breaks * m.breaks
                + self.drain_imbalance * m.drain_imbalance + self.moment2 * m.moment2_error
                + self.drain_contacts * m.drain_contacts)


@dataclass
class Candidate:
    sequence: FingerSequence
    metrics: RowMetrics
    score: float


@dataclass
class SearchResult:
    best: Candidate
    candidates: list[Candidate]
    lower_bound_breaks: int
    mode: str
    orders_evaluated: int
    stats: dict = field(default_factory=dict)


# ---- enumeration --------------------------------------------------------------

def _multiset_perms(counts: dict[str, int]) -> Iterator[list[str]]:
    names = sorted(counts)
    total = sum(counts.values())
    cur: list[str] = []

    def rec() -> Iterator[list[str]]:
        if len(cur) == total:
            yield list(cur)
            return
        for n in names:
            if counts[n]:
                counts[n] -= 1
                cur.append(n)
                yield from rec()
                cur.pop()
                counts[n] += 1

    yield from rec()


def _count_perms(counts: Mapping[str, int]) -> int:
    out = math.factorial(sum(counts.values()))
    for c in counts.values():
        out //= math.factorial(c)
    return out


def _palindrome_parts(counts: Mapping[str, int]) -> Optional[tuple[dict[str, int], Optional[str]]]:
    odd = [n for n, c in counts.items() if c % 2]
    if len(odd) > 1:
        return None
    half = {n: c // 2 for n, c in counts.items()}
    return half, (odd[0] if odd else None)


def _orders(counts: dict[str, int], limit: int, seed: int) -> tuple[str, Iterator[list[str]], int]:
    n_all = _count_perms(counts)
    if n_all <= limit:
        return "exhaustive", _multiset_perms(dict(counts)), n_all
    parts = _palindrome_parts(counts)
    rng = random.Random(seed)
    if parts is not None:
        half, centre = parts
        mid = [centre] if centre else []
        n_pal = _count_perms(half)
        if n_pal <= limit:
            gen = (h + mid + h[::-1] for h in _multiset_perms(dict(half)))
            return "palindromes", gen, n_pal

        def sample_pal() -> Iterator[list[str]]:
            base = [n for n, c in half.items() for _ in range(c)]
            seen = set()
            for _ in range(limit * 4):
                rng.shuffle(base)
                key = tuple(base)
                if key in seen:
                    continue
                seen.add(key)
                yield list(base) + mid + list(base)[::-1]
                if len(seen) >= limit:
                    return
        return "sampled palindromes", sample_pal(), limit

    def sample_all() -> Iterator[list[str]]:
        base = [n for n, c in counts.items() for _ in range(c)]
        seen = set()
        for _ in range(limit * 4):
            rng.shuffle(base)
            key = tuple(base)
            if key not in seen:
                seen.add(key)
                yield list(base)
            if len(seen) >= limit:
                return
    return "sampled", sample_all(), limit


# ---- orientation DP -----------------------------------------------------------

def orient(order: Sequence[str], devices: Mapping[str, DeviceSpec]) -> tuple[Finger, ...]:
    """Choose orientations minimising (breaks, drain contacts) for a fixed order."""
    n = len(order)
    if n == 0:
        return ()

    def nets(i: int, o: int) -> tuple[str, str]:
        d = devices[order[i]]
        return (d.drain, d.source) if o else (d.source, d.drain)

    def is_drain(net: str, *idx: int) -> int:
        return int(any(devices[order[i]].drain == net for i in idx))

    INF = (math.inf, math.inf)
    cost = [[INF, INF] for _ in range(n)]
    back = [[0, 0] for _ in range(n)]
    for o in (0, 1):
        cost[0][o] = (0, is_drain(nets(0, o)[0], 0))
    for i in range(1, n):
        for o in (0, 1):
            left = nets(i, o)[0]
            for po in (0, 1):
                prev_right = nets(i - 1, po)[1]
                pb, pd = cost[i - 1][po]
                if prev_right == left:
                    c = (pb, pd + is_drain(left, i - 1, i))
                else:
                    c = (pb + 1, pd + is_drain(prev_right, i - 1) + is_drain(left, i))
                if c < cost[i][o]:
                    cost[i][o] = c
                    back[i][o] = po
    # close the last contact
    final = []
    for o in (0, 1):
        b, d = cost[n - 1][o]
        final.append((b, d + is_drain(nets(n - 1, o)[1], n - 1)))
    o = 0 if final[0] <= final[1] else 1
    orients = [0] * n
    for i in range(n - 1, -1, -1):
        orients[i] = o
        o = back[i][o]
    return tuple(Finger(order[i], bool(orients[i])) for i in range(n))


# ---- driver ---------------------------------------------------------------------

def search_sequences(
    devices: Sequence[DeviceSpec],
    weights: Optional[SequenceWeights] = None,
    limit: int = 20000,
    top_k: int = 5,
    require_common_centroid: bool = True,
    break_gap: float = 1.0,
    seed: int = 0,
    title: str = "Finger-sequence search",
) -> SearchResult:
    """Rank finger sequences for ``devices`` (one row, shared S/D allowed)."""
    weights = weights or SequenceWeights()
    devmap = {d.name: d for d in devices}
    if len(devmap) != len(devices):
        raise ValueError("device names must be unique")
    with ProcessTable(title, ", ".join(f"{d.name}×{d.fingers}" for d in devices)) as pt:
        with pt.stage("Eligibility") as st:
            never = check_shareable(devices)
            st.detail(f"{len(devices)} devices, {sum(d.fingers for d in devices)} fingers")
            if never:
                st.warn(f"no common S/D net: {', '.join(never)} (every boundary between them breaks)")
        with pt.stage("Diffusion graph") as st:
            g = DiffusionGraph.build(devices)
            lb = g.min_breaks()
            st.detail(f"{len(g.degree)} nets, {len(g.components)} component(s), "
                      f"odd nodes {g.odd_nodes or '—'}, Euler lower bound {lb} break(s)")
        with pt.stage("Enumerate orders") as st:
            counts = {d.name: d.fingers for d in devices}
            mode, gen, n_orders = _orders(counts, limit, seed)
            st.detail(f"{mode}: {n_orders} order(s) (all perms {_count_perms(counts)})")
        with pt.stage("Orient + score") as st:
            cands: list[Candidate] = []
            seen = set()
            evaluated = 0
            for order in gen:
                key = tuple(order)
                if key in seen or key[::-1] in seen:   # a mirrored row is the same row
                    continue
                seen.add(key)
                evaluated += 1
                seq = FingerSequence(devmap, orient(order, devmap), break_gap)
                m = seq.metrics()
                cands.append(Candidate(seq, m, weights.score(m)))
            cc = [c for c in cands if c.metrics.centroid_error <= CENTROID_TOL]
            st.detail(f"{evaluated} distinct orders, {len(cc)} exactly common-centroid")
            pool = cc
            if require_common_centroid and not cc:
                st.warn("no exactly common-centroid order; ranking all by score")
                pool = cands
            elif not require_common_centroid:
                pool = cands
        with pt.stage("Rank") as st:
            pool.sort(key=lambda c: (c.score, c.sequence.labels()))
            best = pool[0]
            st.detail(f"best score {best.score:.3g}; breaks {best.metrics.breaks} vs bound {lb}")
            if best.metrics.breaks > lb:
                st.detail("common centroid costs breaks over the Euler bound")
        pt.result("best", best.sequence.labels())
        pt.result("breaks", best.metrics.breaks)
        pt.result("centroid_err", f"{best.metrics.centroid_error:.3g}")
        pt.result("drain_imbalance", f"{best.metrics.drain_imbalance:.3g}")
    top = pool[:top_k]
    print_table(
        f"{title}: top {len(top)}",
        ["rank", "order", "orientation", "breaks", "centroid err", "drain imbal.", "m2 err", "drain contacts", "score"],
        [(i + 1, c.sequence.labels(), c.sequence.compact(), c.metrics.breaks, c.metrics.centroid_error,
          c.metrics.drain_imbalance, c.metrics.moment2_error, c.metrics.drain_contacts, c.score)
         for i, c in enumerate(top)],
        caption=f"best row: {best.sequence.diagram()}",
    )
    return SearchResult(best, top, lb, mode, evaluated,
                        {"common_centroid": len(cc), "lower_bound": lb})
