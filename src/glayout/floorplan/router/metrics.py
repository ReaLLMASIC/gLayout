"""Lengths and costs: HPWL, minimum spanning trees, routed wire, detours."""
from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from glayout.floorplan.router.problem import Landing, RoutingResult

if TYPE_CHECKING:
    from glayout.floorplan.router.grid import RoutingGrid


def hpwl(pts: Sequence[tuple[float, float]]) -> float:
    """Half-perimeter of the bounding box of ``pts``."""
    return (max(x for x, _ in pts) - min(x for x, _ in pts)) + (max(y for _, y in pts) - min(y for _, y in pts))


def mst_order(lands: list[Landing]) -> list[tuple[Landing, Landing]]:
    """Prim's MST over pin landings; returns (new pin, parent pin) in tree order.

    The first entry is (root, root); the root is the landing with the smallest x + y.
    Distances are Manhattan; ties go to the smaller pin owner name.
    """
    if not lands:
        return []
    start = min(lands, key=lambda l: (l.x + l.y, l.pin.owner))
    in_tree = [start]
    rest = [l for l in lands if l is not start]
    edges = []
    while rest:
        best = min(((r, p) for r in rest for p in in_tree),
                   key=lambda rp: (abs(rp[0].x - rp[1].x) + abs(rp[0].y - rp[1].y), rp[0].pin.owner))
        edges.append(best)
        in_tree.append(best[0])
        rest.remove(best[0])
    return [(start, start)] + edges


def path_wire(grid: "RoutingGrid", plist: Sequence[Sequence[tuple]]) -> float:
    """Router-layer wire length of a net's paths (vias and stubs not included)."""
    wl = 0.0
    for path in plist:
        for a, b in zip(path, path[1:]):
            if grid.layer(a) == grid.layer(b):
                (ax, ay), (bx, by) = grid.xy(a), grid.xy(b)
                wl += abs(ax - bx) + abs(ay - by)
    return wl


def mst_length(pts: Sequence[tuple[float, float]]) -> float:
    """Manhattan length of the minimum spanning tree over ``pts`` (Prim)."""
    if len(pts) < 2:
        return 0.0
    dist = {i: abs(pts[i][0] - pts[0][0]) + abs(pts[i][1] - pts[0][1]) for i in range(1, len(pts))}
    total = 0.0
    while dist:
        i = min(dist, key=dist.get)
        total += dist.pop(i)
        for k in dist:
            dist[k] = min(dist[k], abs(pts[k][0] - pts[i][0]) + abs(pts[k][1] - pts[i][1]))
    return total


def detours(result: RoutingResult) -> dict[str, float]:
    """Routed nets whose wire exceeds ``detour_ratio`` times the MST of their landings,
    and by at least ``detour_min``: net -> excess wire (µm)."""
    t, g = result.tech, result.grid
    out = {}
    for net, plist in result.paths.items():
        wire = path_wire(g, plist)
        ref = mst_length([(l.x, l.y) for l in result.landings.get(net, [])])
        # the MST is floored at one pitch, so nets whose landings almost touch are not flagged
        if wire > t.detour_ratio * max(ref, t.pitch) and wire - ref >= t.detour_min:
            out[net] = wire - ref
    return out


def route_cost(r: RoutingResult) -> float:
    """Wirelength plus via cost: what detour re-landing must lower to keep a change."""
    return r.wirelength + r.tech.c_via * r.vias
