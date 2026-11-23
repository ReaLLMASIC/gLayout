"""Pin access: choose the side each pin leaves its cell from, then land it just outside the cell.

1. **Side choice** (paper step 2). For every net, the combination of access options (one per
   pin) with the smallest HPWL is chosen, exhaustively. Combinations within half a pitch of
   the smallest are a tie, broken toward the one whose route region holds the fewest landings
   already chosen (longest nets choose first). Without this, a rail reaching both block edges
   always took the first-listed side, and every such net piled into the same channel.
2. **Landing.** Each pin gets a stub on its own layer (met1/met2) out to a landing point
   just outside its cell, with a via stack up to the router layer. Nodes and edges close to
   those via pads are reserved for the pin (``RoutingGrid.node_ok``).
"""
from __future__ import annotations

import itertools
import math
from typing import Optional, Sequence

from glayout.floorplan.router.geometry import DIRS, H, V, Rect, gap, square, too_close
from glayout.floorplan.router.grid import RoutingGrid
from glayout.floorplan.router.metrics import hpwl
from glayout.floorplan.router.problem import AccessOption, Landing, RouterPin
from glayout.floorplan.router.tech import RouterTech

MAX_COMBOS = 4096       # side combinations per net that are still enumerated exhaustively


# ---------------------------------------------------------------------------
# landing one pin
# ---------------------------------------------------------------------------

def landing_shapes(tech: RouterTech, opt: AccessOption, x: float, y: float, z: int) -> list[tuple[str, Rect]]:
    """Shapes of a landing at (x, y): the stub from the port (index 0), then the via-stack pads.

    The stub runs on the port's layer, no wider than the port or the pad on that layer.
    """
    sw = min(opt.width, tech.pad(opt.layer, z, opt.layer) or opt.width)
    dx, dy = DIRS[opt.side]
    # start half a width inside the port's own metal so the two overlap
    if opt.side in "EW":
        x0 = opt.x - dx * sw / 2
        stub = (min(x0, x), y - sw / 2, max(x0, x), y + sw / 2)
    else:
        y0 = opt.y - dy * sw / 2
        stub = (x - sw / 2, min(y0, y), x + sw / 2, max(y0, y))
    shapes = [(opt.layer, stub)]
    for lay, s in tech.access_pads.get((opt.layer, z), {}).items():
        shapes.append((lay, square(x, y, s)))
    return shapes


def _step_spot(grid: RoutingGrid, opt: AccessOption, step: int) -> Optional[tuple[float, float, list[tuple]]]:
    """The ``step``-th landing spot out from port ``opt``: (x, y, grid nodes beside it), or None off the grid.

    An E/W port lands on a vertical-layer column, ``step`` columns beyond the first one past the
    port, at the port's y; the nodes beside it are the two on that column either side of y.
    An N/S port likewise lands on a horizontal-layer row at the port's x.
    """
    t = grid.t
    dx, dy = DIRS[opt.side]
    if opt.side in "EW":
        i = (math.floor((opt.x - grid.x0) / t.pitch) + (0 if dx < 0 else 1)) + dx * step
        if not 0 <= i < grid.nx:
            return None
        x, y = grid.x0 + i * t.pitch, opt.y
        j_lo = math.floor((y - grid.y0) / t.pitch + 1e-9)
        cand = [(V, i, j) for j in (j_lo, j_lo + 1) if 0 <= j < grid.ny]
    else:
        j = (math.floor((opt.y - grid.y0) / t.pitch) + (0 if dy < 0 else 1)) + dy * step
        if not 0 <= j < grid.ny:
            return None
        x, y = opt.x, grid.y0 + j * t.pitch
        i_lo = math.floor((x - grid.x0) / t.pitch + 1e-9)
        cand = [(H, i, j) for i in (i_lo, i_lo + 1) if 0 <= i < grid.nx]
    return x, y, cand


def _clashes(tech: RouterTech, pin: RouterPin, x: float, y: float, shapes: Sequence[tuple[str, Rect]],
             claimed: Sequence[Landing]) -> bool:
    """Whether a landing at (x, y) with ``shapes`` comes too close to a landing already claimed.

    A same-net shape may overlap, not nearly touch. Two via pads (index > 0; 0 is the stub)
    may only overlap when concentric: off-centre, their via cuts sit closer than the cut
    spacing (gf180 V2.2a/V3.2a: two VDD landings 0.49um apart).
    """
    for other in claimed:
        same = other.pin.net == pin.net
        for k, (lay, r) in enumerate(shapes):
            for ok, (ol, orr) in enumerate(other.shapes):
                if lay != ol or not too_close(r, orr, tech.layer_sep.get(lay, 0.0)):
                    continue
                gx, gy = gap(r, orr)
                concentric = abs(x - other.x) < 1e-6 and abs(y - other.y) < 1e-6
                if not (same and gx <= 0 and gy <= 0 and (k == 0 or ok == 0 or concentric)):
                    return True
    return False


def _keeps_escapes(grid: RoutingGrid, pin: RouterPin, neigh: list[tuple], pads: Sequence[tuple[str, Rect]],
                   claimed: Sequence[Landing]) -> bool:
    """The new pin can get out through ``neigh``, and its pads would not trap a pin already landed."""
    new_nodes, new_edges = grid.would_reserve(pads)
    if not grid.has_escape(pin.net, neigh, set(), set(), new_nodes, new_edges):
        return False
    return not any(not grid.has_escape(other.pin.net, [n for n in other.neighbours if grid.node_ok(n, other.pin.net)],
                                       new_nodes, new_edges)
                   for other in claimed)


def try_landing(grid: RoutingGrid, pin: RouterPin, opt: AccessOption, claimed: list[Landing],
                max_steps: int = 60) -> Optional[Landing]:
    """Walk out from port ``opt`` one grid step at a time and return the first legal landing.

    A spot is passed over (try one step further out) when its pads would come too close to a
    cell, the stub would cross another cell, it clashes with a landing already claimed, it has
    no free neighbour node, or it would leave this pin or an earlier one no way out. The option
    is given up (None) when the stub's corridor through its own cell is blocked, or the walk
    leaves the grid or the routing area.
    """
    t = grid.t
    z = V if opt.side in "EW" else H
    for step in range(max_steps):
        spot = _step_spot(grid, opt, step)
        if spot is None:
            return None
        x, y, cand = spot
        shapes = landing_shapes(t, opt, x, y, z)
        pads = shapes[1:]
        # the landing pads must clear every cell, including the pin's own
        if any(too_close(r, cell, t.layer_sep.get(lay, 0.0)) for lay, r in pads for cell in grid.p.cells):
            continue
        # the stub may only cross its own cell, and there it must clear the
        # cell's other shapes (the corridor is fixed, so this option is dead)
        stub_lay, stub = shapes[0]
        if any(too_close(stub, f[:4], f[4]) for f in opt.foreign):
            return None
        if any(too_close(stub, cell, t.layer_sep.get(stub_lay, 0.0))
               for k, cell in enumerate(grid.p.cells) if k != pin.cell):
            continue
        if not (0 <= x <= grid.p.width and 0 <= y <= grid.p.height):
            return None
        if _clashes(t, pin, x, y, shapes, claimed):
            continue
        neigh = [n for n in cand if n not in grid.blocked and not grid.reserved.get(n)]
        if not neigh:
            continue
        # the new pin must be able to get out, and must not trap a pin already landed
        if not _keeps_escapes(grid, pin, neigh, pads, claimed):
            continue
        node = ("P", len(grid.pos))
        return Landing(pin, opt, x, y, z, node, neigh, shapes)
    return None


# ---------------------------------------------------------------------------
# side choice
# ---------------------------------------------------------------------------

def combo_key(pins: Sequence[RouterPin], combo: Sequence[AccessOption]) -> tuple:
    """Identity of one access option per pin, for excluding a side combination."""
    return tuple((p.owner, o.side, round(o.x, 3), round(o.y, 3)) for p, o in zip(pins, combo))


def _estimate(o: AccessOption, margin: float) -> tuple[float, float]:
    """Where a pin leaving through ``o`` will roughly land: ``margin`` out from the port."""
    dx, dy = DIRS[o.side]
    return (o.x + dx * margin, o.y + dy * margin)


def _channel_point(grid: RoutingGrid, p: RouterPin, o: AccessOption, margin: float) -> tuple[float, float]:
    """Where the pin will land: just outside its cell, on the option's side."""
    x0, y0, x1, y1 = grid.p.cells[p.cell]
    return {"W": (x0 - margin, o.y), "E": (x1 + margin, o.y),
            "S": (o.x, y0 - margin), "N": (o.x, y1 + margin)}[o.side]


def _load(pts: Sequence[tuple[float, float]], taken: Sequence[tuple[float, float]], margin: float) -> int:
    """Landings already chosen inside the region a net with these landings would route through."""
    x0, x1 = min(x for x, _ in pts) - margin, max(x for x, _ in pts) + margin
    y0, y1 = min(y for _, y in pts) - margin, max(y for _, y in pts) + margin
    return sum(x0 <= x <= x1 and y0 <= y <= y1 for x, y in taken)


def _option_distance(o: AccessOption, chosen: Sequence[AccessOption], margin: float) -> float:
    """Total distance from option ``o``'s estimated landing to those of the chosen options."""
    return sum(abs(_estimate(o, margin)[0] - _estimate(f, margin)[0])
               + abs(_estimate(o, margin)[1] - _estimate(f, margin)[1]) for f in chosen)


def _side_candidates(grid: RoutingGrid, exclude: dict[str, set[tuple]],
                     margin: float) -> dict[str, list[tuple[float, tuple[AccessOption, ...]]]]:
    """Every side combination of each net with its estimated HPWL.

    Exhaustive over the pins' options up to ``MAX_COMBOS`` combinations, minus the excluded
    ones (unless that would exclude all). Beyond that, a single combination: each pin's option
    nearest the centroid of all the net's options (exclusions not applied).
    """
    cands: dict[str, list[tuple[float, tuple[AccessOption, ...]]]] = {}
    for net, pins in grid.p.nets.items():
        opts = [p.options for p in pins]
        if math.prod(max(1, len(o)) for o in opts) <= MAX_COMBOS:
            scored = [(hpwl([_estimate(o, margin) for o in combo]), combo) for combo in itertools.product(*opts)]
            kept = [s for s in scored if combo_key(pins, s[1]) not in exclude.get(net, ())]
            cands[net] = kept or scored
        else:      # too many to enumerate: nearest option to the centroid (exclusions not applied)
            cx = sum(o.x for p in pins for o in p.options) / sum(len(p.options) for p in pins)
            cy = sum(o.y for p in pins for o in p.options) / sum(len(p.options) for p in pins)
            cands[net] = [(0.0, tuple(min(p.options, key=lambda o: abs(_estimate(o, margin)[0] - cx)
                                          + abs(_estimate(o, margin)[1] - cy))
                                      for p in pins))]
    return cands


def _choose_sides(grid: RoutingGrid, cands: dict[str, list[tuple[float, tuple[AccessOption, ...]]]],
                  margin: float, spread: bool) -> dict[str, list[tuple[RouterPin, list[AccessOption]]]]:
    """Pick one combination per net and rank each pin's options; longest nets choose first.

    Combinations within half a pitch of the net's smallest HPWL are ties (landings snap to the
    grid anyway). With ``spread`` a tie goes to the combination whose route region holds the
    fewest landings chosen so far, then to the smaller HPWL, then to option order; without it,
    to HPWL and option order alone. Each pin's chosen option comes first, then its other
    options by distance from the chosen ones (fallbacks for when it cannot land).
    """
    taken: list[tuple[float, float]] = []      # landing estimates of the pins already given a side
    chosen: dict[str, list[tuple[RouterPin, list[AccessOption]]]] = {}
    for net in sorted(cands, key=lambda n: (-min(hp for hp, _ in cands[n]), n)):     # longest nets first
        pins = grid.p.nets[net]
        best_hp = min(hp for hp, _ in cands[net])
        ties = [(hp, c) for hp, c in cands[net] if hp <= best_hp + grid.t.pitch / 2]
        _, best = min(ties, key=lambda hc: (_load([_channel_point(grid, p, o, margin) for p, o in zip(pins, hc[1])],
                                                  taken, margin) if spread else 0,
                                            round(hc[0], 9)))
        pref = list(best)
        taken.extend(_channel_point(grid, p, o, margin) for p, o in zip(pins, pref))
        ranked = []
        for p, first in zip(pins, pref):
            rest = sorted((o for o in p.options if o is not first), key=lambda o: _option_distance(o, pref, margin))
            ranked.append((p, [first] + rest))
        chosen[net] = ranked
    return chosen


# ---------------------------------------------------------------------------
# landing all pins
# ---------------------------------------------------------------------------

def _land_pins(grid: RoutingGrid, chosen: dict[str, list[tuple[RouterPin, list[AccessOption]]]]):
    """Land every pin, in a fixed order (cell, side, y, x, owner), trying its ranked options in turn.

    Each landing joins the grid and reserves the nodes around its pads at once, so later pins
    see it. Returns (landings per net, owners of pins with no legal landing, back-links from
    grid nodes to the pin nodes next to them).
    """
    order = sorted(((p, opts) for ranked in chosen.values() for p, opts in ranked),
                   key=lambda po: (po[0].cell, po[1][0].side, round(po[1][0].y, 3), round(po[1][0].x, 3), po[0].owner))
    landings: dict[str, list[Landing]] = {}
    claimed: list[Landing] = []
    unreachable = []
    back: dict[tuple, list[tuple]] = {}
    for pin, opts in order:
        land = None
        for opt in opts:
            land = try_landing(grid, pin, opt, claimed)
            if land is not None:
                break
        if land is None:
            unreachable.append(pin.owner)
            continue
        claimed.append(land)
        landings.setdefault(pin.net, []).append(land)
        lid = grid.register_landing(land)
        for n in land.neighbours:
            back.setdefault(n, []).append(land.node)
        for lay, r in land.shapes[1:]:
            grid.reserve(lid, lay, r)
    return landings, unreachable, back


def _drop_trapped(grid: RoutingGrid, landings: dict[str, list[Landing]], unreachable: list[str]) -> None:
    """Re-check every landing's neighbours after all pins have landed, in place.

    A later reservation can take away an earlier pin's only neighbour. Each landing keeps the
    neighbours its net may still use; one left with none is dropped from ``landings`` and its
    pin is added to ``unreachable`` (it stays in the grid, so landing ids do not change).
    """
    for lid, land in enumerate(grid.landings):
        ok = [n for n in land.neighbours if grid.node_ok(n, land.pin.net)]
        if not ok:
            unreachable.append(land.pin.owner)
            landings[land.pin.net].remove(land)
        land.neighbours[:] = ok
        grid.adj[lid] = set(ok)


def plan_access(grid: RoutingGrid, exclude: Optional[dict[str, set[tuple]]] = None,
                spread: bool = True) -> tuple[dict[str, list[Landing]], list[str]]:
    """Choose each pin's side and land it. Returns landings per net and the unreachable pins' owners.

    ``exclude``: net -> side combinations (``combo_key``) not to choose.
    ``spread=False`` breaks HPWL ties by option order alone (the original rule).
    """
    margin = grid.t.pitch * 1.5
    cands = _side_candidates(grid, exclude or {}, margin)
    chosen = _choose_sides(grid, cands, margin, spread)
    landings, unreachable, back = _land_pins(grid, chosen)
    _drop_trapped(grid, landings, unreachable)
    # the search may step from a grid node onto a pin landed next to it only from now on;
    # access planning never routes through pin nodes, so it does not need these links
    grid.pin_back = back
    return landings, unreachable
