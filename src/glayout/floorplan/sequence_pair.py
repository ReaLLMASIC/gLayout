"""Sequence-pair floorplan representation (Murata et al., 1995).

Two permutations (Γ+, Γ-) of the blocks encode every relative position:
a is left of b  iff a precedes b in both;
a is below b    iff a follows b in Γ+ and precedes it in Γ-.
``pack`` turns a pair into lower-left coordinates by longest-path, O(n²).
"""
from __future__ import annotations

from typing import Sequence


def pack(gp: Sequence[int], gn: Sequence[int], w: Sequence[float], h: Sequence[float]) -> tuple[list[float], list[float]]:
    n = len(gp)
    pos_p = [0] * n
    pos_n = [0] * n
    for i, b in enumerate(gp):
        pos_p[b] = i
    for i, b in enumerate(gn):
        pos_n[b] = i
    x = [0.0] * n
    y = [0.0] * n
    for i, b in enumerate(gp):            # left-of is consistent with Γ+ order
        best = 0.0
        for a in gp[:i]:
            if pos_n[a] < pos_n[b]:
                best = max(best, x[a] + w[a])
        x[b] = best
    for i, b in enumerate(gn):            # below is consistent with Γ- order
        best = 0.0
        for a in gn[:i]:
            if pos_p[a] > pos_p[b]:
                best = max(best, y[a] + h[a])
        y[b] = best
    return x, y


def overlaps(x: Sequence[float], y: Sequence[float], w: Sequence[float], h: Sequence[float],
             i: int, xi: float, eps: float = 1e-9) -> bool:
    """Would block i at x=xi overlap any other block?"""
    for j in range(len(x)):
        if j == i:
            continue
        if xi < x[j] + w[j] - eps and x[j] < xi + w[i] - eps and y[i] < y[j] + h[j] - eps and y[j] < y[i] + h[i] - eps:
            return True
    return False
