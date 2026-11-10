"""Two-layer grid router for the nets between floorplan blocks (paper §1.10).

1. **Grid.** A 3-D graph: layer 0 carries horizontal wires, layer 1 vertical
   ones, vias join them. The pitch is the largest ``via pad + spacing`` of the
   two layers, so a via or a wire end on any node is legal next to any other
   net on the neighbouring tracks. Nodes and edges whose shapes would come
   closer than the spacing rule to a cell are removed (cells are obstacles).
2. **Pin access + sides.** Each block pin offers ports on one or more block
   sides (rail ends E/W, tie ring N/E/S/W). For every net the side
   combination with the smallest HPWL is chosen (exhaustively, as in the
   paper), then each pin gets a stub on its own layer (met1/met2) out to a
   landing point just outside its cell, with a via up to the router layer.
   Nodes and edges close to that via are reserved for the pin's net.
   Combinations within half a pitch of the smallest HPWL are a tie, broken
   toward the one whose route region holds the fewest landings already
   chosen (longest nets choose first). Without this, a rail reaching both
   block edges always took the first-listed side, so every such net piled
   into the same channel. Spreading does not know how many pins a cell side
   can land, so if it does not route, the first-listed rule is tried and
   kept: it reproduces the original landings, and never routes worse.
3. **Decomposition.** Multi-pin nets are connected in minimum-spanning-tree
   order; each new pin is routed to the part of its net already routed.
4. **Net order.** More past failures first, then larger HPWL, then more pins.
5. **Search.** Bidirectional A* with the paper's costs::

       D(n,k) = |dx| + |dy| + c_via·|dz|                          (Eq. 3)
       g(n)   = g(k) + D(n,k) + c_DRC·[n used by another net] + H(n)  (Eq. 4)
       h(n)   = D(t,n)·(1+q),  q = 1e-4
       f(n)   = g + h            if g < h
              = (g + (2κ-1)h)/κ  otherwise, κ = 3                 (Eq. 5)

6. **Rip-up and reroute.** Nets that share a node with another net are
   ripped up, the history cost H of the nodes they used is raised, and they
   are rerouted. After 35 iterations with conflicts left, routing fails.
7. **Detours.** Rip-up and reroute fixes conflicts, not detours: a net
   walled off by other nets' landings routes around a block and counts as
   routed. A routed net whose wire exceeds ``detour_ratio`` times the MST
   of its landings (and by ``detour_min``) is re-landed: its side
   combination is excluded, everything is routed again, and the change is
   kept only if wirelength + c_via·vias goes down. Worst detour first, at
   most ``max_relands`` tries.

Layers are directional, so every bend is a via: the paper's low-bending rule
is the via cost. Wires are drawn at via-pad width rather than minimum width,
so a via never needs extra enclosure.
"""
from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

from glayout.util.process_table import ProcessTable, print_table

H, V = 0, 1
Rect = tuple[float, float, float, float]   # x0, y0, x1, y1


def _gap(a: Rect, b: Rect) -> tuple[float, float]:
    return (max(b[0] - a[2], a[0] - b[2]), max(b[1] - a[3], a[1] - b[3]))


def _too_close(a: Rect, b: Rect, sep: float, eps: float = 1e-9) -> bool:
    """Square-metric spacing check (stricter than euclidean at corners)."""
    gx, gy = _gap(a, b)
    return gx < sep - eps and gy < sep - eps


def _sq(x: float, y: float, s: float) -> Rect:
    return (x - s / 2, y - s / 2, x + s / 2, y + s / 2)


# ---------------------------------------------------------------------------
# technology
# ---------------------------------------------------------------------------

@dataclass
class RouterTech:
    layers: tuple[str, str]                  # (horizontal, vertical) glayer names
    pitch: float
    wire: tuple[float, float]                # drawn wire width per router layer
    sep: tuple[float, float]                 # spacing rule per router layer
    layer_sep: dict[str, float]              # spacing rule for every layer a stub/pad may use
    access_pads: dict[tuple[str, int], dict[str, float]]   # (port layer, landing z) -> {layer: pad}
    snap: Callable[[float], float] = lambda v: v
    c_via: float = 0.0
    c_drc: float = 0.0
    h_inc: float = 0.0
    q: float = 1e-4
    kappa: float = 3.0
    max_iterations: int = 35
    detour_ratio: float = 2.0                # 0 turns detour re-landing off
    detour_min: float = 0.0                  # minimum excess wire to count as a detour
    max_relands: int = 8

    def __post_init__(self):
        p = self.pitch
        self.c_via = self.c_via or 2 * p
        self.c_drc = self.c_drc or 20 * p
        self.h_inc = self.h_inc or 2 * p
        self.detour_min = self.detour_min or 4 * p

    def pad(self, port_layer: str, z: int, layer: str) -> float:
        return self.access_pads.get((port_layer, z), {}).get(layer, 0.0)

    @classmethod
    def from_pdk(cls, pdk, layers: Sequence[str] = ("met3", "met4"), **costs) -> "RouterTech":
        from glayout.primitives.via_gen import via_stack
        from glayout.util.comp_utils import evaluate_bbox
        pdk.activate()

        def pads(a: str, b: str) -> dict[str, float]:
            v = via_stack(pdk, a, b)
            out = {}
            for lay in v.get_layers():
                g = pdk.layer_to_glayer(tuple(lay))
                if g.startswith("met"):
                    out[g] = max(evaluate_bbox(v.extract(layers=[tuple(lay)])))
            return out

        hl, vl = layers
        grid_pads = pads(hl, vl)
        wire = (grid_pads[hl], grid_pads[vl])
        sep = (float(pdk.get_grule(hl)["min_separation"]), float(pdk.get_grule(vl)["min_separation"]))
        pitch = pdk.snap_to_2xgrid(max(wire[0] + sep[0], wire[1] + sep[1]))
        access = {}
        for port_layer in ("met1", "met2"):
            for z, top in ((H, hl), (V, vl)):
                access[(port_layer, z)] = pads(port_layer, top)
        layer_sep = {f"met{i}": float(pdk.get_grule(f"met{i}")["min_separation"]) for i in range(1, 6)}
        return cls(tuple(layers), pitch, wire, sep, layer_sep, access, snap=pdk.snap_to_2xgrid, **costs)

    @classmethod
    def abstract(cls, pitch: float = 1.0, **costs) -> "RouterTech":
        """Unit tech for tests: pads = wire = 0.5·pitch, spacing = 0.5·pitch."""
        w, s = 0.5 * pitch, 0.5 * pitch
        pads = {"met1": w, "met2": w, "met3": w, "met4": w}
        access = {(pl, z): dict(pads) for pl in ("met1", "met2") for z in (H, V)}
        return cls(("met3", "met4"), pitch, (w, w), (s, s), {k: s for k in pads}, access, **costs)


def track_pitch(pdk, layers: Sequence[str] = ("met3", "met4")) -> float:
    return RouterTech.from_pdk(pdk, layers).pitch


# ---------------------------------------------------------------------------
# problem
# ---------------------------------------------------------------------------

@dataclass
class AccessOption:
    side: str
    x: float                # absolute port centre
    y: float
    layer: str
    width: float
    foreign: tuple[tuple[float, float, float, float, float], ...] = ()   # absolute rect + spacing to keep


@dataclass
class RouterPin:
    net: str
    owner: str              # e.g. "DP.VOUT1"
    cell: int               # index of the obstacle this pin belongs to
    options: list[AccessOption]


@dataclass
class RoutingProblem:
    width: float
    height: float
    cells: list[Rect]                       # obstacles (cell bounding boxes)
    nets: dict[str, list[RouterPin]]


@dataclass
class Landing:
    pin: RouterPin
    option: AccessOption
    x: float                # landing (via) point
    y: float
    z: int                  # router layer of the pin node
    node: tuple
    neighbours: list[tuple]
    shapes: list[tuple[str, Rect]]          # stub + via pads, for geometry and spacing checks


@dataclass
class RoutingResult:
    success: bool
    iterations: int
    failed_nets: list[str]
    unreachable: list[str]                  # pins that got no legal landing
    paths: dict[str, list[list[tuple]]]     # net -> node paths
    landings: dict[str, list[Landing]]
    wirelength: float
    vias: int
    conflicts: int
    tech: RouterTech
    grid: "RoutingGrid"
    history: list[dict] = field(default_factory=list)
    hotspots: list[tuple[float, float]] = field(default_factory=list)   # where routing failed

    def summary(self) -> dict:
        return {"success": self.success, "iterations": self.iterations, "failed_nets": self.failed_nets,
                "unreachable": self.unreachable, "wirelength_um": round(self.wirelength, 3),
                "vias": self.vias, "conflicts": self.conflicts, "hotspots": len(self.hotspots)}


# ---------------------------------------------------------------------------
# grid
# ---------------------------------------------------------------------------

class RoutingGrid:
    def __init__(self, problem: RoutingProblem, tech: RouterTech):
        self.p = problem
        self.t = tech
        pitch = tech.pitch
        self.x0 = tech.snap(pitch / 2)
        self.y0 = tech.snap(pitch / 2)
        self.nx = max(1, int((problem.width - self.x0) // pitch) + 1)
        self.ny = max(1, int((problem.height - self.y0) // pitch) + 1)
        self.blocked: set[tuple] = set()
        self.blocked_edges: set[tuple] = set()
        # node/edge -> ids of the landings whose via pads it would come too close to.
        # Such a node is usable only as a direct neighbour of that landing's pin
        # node (so its wire touches the pad); everything else, including the
        # pin's own net, must keep away: a same-net shape near a pad without
        # touching it is still a spacing violation, and a via there a cut one.
        self.reserved: dict[tuple, set[int]] = {}
        self.reserved_edges: dict[tuple, set[int]] = {}
        self.landings: list = []
        self.adj: list[set[tuple]] = []
        self.pin_adj: dict[tuple, list[tuple]] = {}       # pin node -> grid neighbours
        self.pin_of: dict[tuple, str] = {}                # pin node -> net
        self.pos: dict[tuple, tuple[float, float]] = {}   # pin node positions
        self.pin_z: dict[tuple, int] = {}                 # pin node router layer
        self._block_cells()

    # coordinates -------------------------------------------------------
    def xy(self, n: tuple) -> tuple[float, float]:
        if n[0] == "P":
            return self.pos[n]
        return (self.x0 + n[1] * self.t.pitch, self.y0 + n[2] * self.t.pitch)

    def layer(self, n: tuple) -> int:
        return self.pin_z[n] if n[0] == "P" else n[0]

    def inside(self, i: int, j: int) -> bool:
        return 0 <= i < self.nx and 0 <= j < self.ny

    def node_rect(self, z: int, i: int, j: int) -> Rect:
        x, y = self.xy((z, i, j))
        return _sq(x, y, self.t.wire[z])

    def edge_rect(self, z: int, i: int, j: int) -> Rect:
        """Wire from (z,i,j) to its +1 neighbour along the layer's direction."""
        w = self.t.wire[z]
        x, y = self.xy((z, i, j))
        if z == H:
            return (x - w / 2, y - w / 2, x + self.t.pitch + w / 2, y + w / 2)
        return (x - w / 2, y - w / 2, x + w / 2, y + self.t.pitch + w / 2)

    def _window(self, r: Rect, margin: float):
        p = self.t.pitch
        i0 = max(0, int(math.floor((r[0] - margin - self.x0) / p)) - 1)
        i1 = min(self.nx - 1, int(math.ceil((r[2] + margin - self.x0) / p)) + 1)
        j0 = max(0, int(math.floor((r[1] - margin - self.y0) / p)) - 1)
        j1 = min(self.ny - 1, int(math.ceil((r[3] + margin - self.y0) / p)) + 1)
        return range(i0, i1 + 1), range(j0, j1 + 1)

    def _hits(self, z: int, r: Rect, sep: float):
        """Nodes and edges on layer z whose shapes come within sep of r."""
        nodes, edges = [], []
        ii, jj = self._window(r, sep + self.t.pitch)
        for i in ii:
            for j in jj:
                if _too_close(self.node_rect(z, i, j), r, sep):
                    nodes.append((z, i, j))
                if (z == H and i + 1 < self.nx) or (z == V and j + 1 < self.ny):
                    if _too_close(self.edge_rect(z, i, j), r, sep):
                        edges.append((z, i, j))
        return nodes, edges

    def _block_cells(self) -> None:
        for r in self.p.cells:
            for z in (H, V):
                nodes, edges = self._hits(z, r, self.t.sep[z])
                self.blocked.update(nodes)
                self.blocked_edges.update(edges)

    def would_reserve(self, shapes: Sequence[tuple[str, Rect]]) -> tuple[set[tuple], set[tuple]]:
        nodes: set[tuple] = set()
        edges: set[tuple] = set()
        for layer, r in shapes:
            for z, lname in enumerate(self.t.layers):
                if lname == layer:
                    n, e = self._hits(z, r, self.t.sep[z])
                    nodes.update(n)
                    edges.update(e)
        return nodes, edges

    def has_escape(self, net: str, adj: Sequence[tuple], extra_nodes: set[tuple], extra_edges: set[tuple],
                   own_nodes: set[tuple] = frozenset(), own_edges: set[tuple] = frozenset(),
                   max_depth: int = 4) -> bool:
        """Can a wire leave a pin's neighbour nodes and reach a node nobody reserves?

        ``extra_*``: reservations of a landing being planned (foreign to this
        pin unless they are its own, ``own_*``).
        """
        adj_set = set(adj)

        def free(m: tuple) -> bool:
            return (m not in self.blocked and not self.reserved.get(m) and m not in extra_nodes
                    and m not in own_nodes)

        def edge_fine(a: tuple, b: tuple) -> bool:
            if a[0] != b[0]:
                return True
            lo = min(a, b)
            if lo in self.blocked_edges or (lo in extra_edges and lo not in own_edges):
                return False
            if lo in own_edges:
                return a in adj_set or b in adj_set
            return self.edge_ok(a, b, net)

        frontier = [n for n in adj if n not in self.blocked and (n in own_nodes or n not in extra_nodes)]
        seen = set(frontier)
        for _ in range(max_depth):
            nxt = []
            for n in frontier:
                for m in self.neighbours(n):
                    if m[0] == "P" or m in seen or not edge_fine(n, m):
                        continue
                    if free(m):
                        return True
                    if m in adj_set:
                        seen.add(m)
                        nxt.append(m)
            frontier = nxt
        return False

    def reserve(self, lid: int, layer: str, r: Rect) -> None:
        for z, lname in enumerate(self.t.layers):
            if lname != layer:
                continue
            nodes, edges = self._hits(z, r, self.t.sep[z])
            for n in nodes:
                self.reserved.setdefault(n, set()).add(lid)
            for e in edges:
                self.reserved_edges.setdefault(e, set()).add(lid)

    # passability ----------------------------------------------------------
    def node_ok(self, n: tuple, net: str) -> bool:
        if n[0] == "P":
            return self.pin_of[n] == net
        if n in self.blocked:
            return False
        owners = self.reserved.get(n)
        return not owners or all(self.landings[l].pin.net == net and n in self.adj[l] for l in owners)

    def edge_ok(self, a: tuple, b: tuple, net: str) -> bool:
        if a[0] == "P" or b[0] == "P":
            return True
        if a[0] != b[0]:
            return True          # via: both nodes already checked
        lo = min(a, b)
        if lo in self.blocked_edges:
            return False
        owners = self.reserved_edges.get(lo)
        # an edge out of a pin's neighbour is part of the wire that touches the pad
        return not owners or all(self.landings[l].pin.net == net and (a in self.adj[l] or b in self.adj[l])
                                 for l in owners)

    def neighbours(self, n: tuple) -> Iterable[tuple]:
        if n[0] == "P":
            yield from self.pin_adj[n]
            return
        z, i, j = n
        if z == H:
            if i > 0:
                yield (H, i - 1, j)
            if i + 1 < self.nx:
                yield (H, i + 1, j)
        else:
            if j > 0:
                yield (V, i, j - 1)
            if j + 1 < self.ny:
                yield (V, i, j + 1)
        yield (1 - z, i, j)
        for pn in self._pin_back.get(n, ()):
            yield pn

    _pin_back: dict = {}


# ---------------------------------------------------------------------------
# pin access
# ---------------------------------------------------------------------------

_DIR = {"W": (-1, 0), "E": (1, 0), "S": (0, -1), "N": (0, 1)}


def _landing_shapes(tech: RouterTech, opt: AccessOption, x: float, y: float, z: int) -> list[tuple[str, Rect]]:
    sw = min(opt.width, tech.pad(opt.layer, z, opt.layer) or opt.width)
    dx, dy = _DIR[opt.side]
    # start half a width inside the port's own metal so the two overlap
    if opt.side in "EW":
        x0 = opt.x - dx * sw / 2
        stub = (min(x0, x), y - sw / 2, max(x0, x), y + sw / 2)
    else:
        y0 = opt.y - dy * sw / 2
        stub = (x - sw / 2, min(y0, y), x + sw / 2, max(y0, y))
    shapes = [(opt.layer, stub)]
    for lay, s in tech.access_pads.get((opt.layer, z), {}).items():
        shapes.append((lay, _sq(x, y, s)))
    return shapes


def _try_landing(grid: RoutingGrid, pin: RouterPin, opt: AccessOption, claimed: list[Landing],
                 max_steps: int = 60) -> Optional[Landing]:
    t = grid.t
    dx, dy = _DIR[opt.side]
    z = V if opt.side in "EW" else H
    own = grid.p.cells[pin.cell]
    for step in range(max_steps):
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
        shapes = _landing_shapes(t, opt, x, y, z)
        pads = shapes[1:]
        # the landing pads must clear every cell, including the pin's own
        if any(_too_close(r, cell, t.layer_sep.get(lay, 0.0)) for lay, r in pads for cell in grid.p.cells):
            continue
        # the stub may only cross its own cell, and there it must clear the
        # cell's other shapes (the corridor is fixed, so this option is dead)
        stub_lay, stub = shapes[0]
        if any(_too_close(stub, f[:4], f[4]) for f in opt.foreign):
            return None
        if any(_too_close(stub, cell, t.layer_sep.get(stub_lay, 0.0))
               for k, cell in enumerate(grid.p.cells) if k != pin.cell):
            continue
        if not (0 <= x <= grid.p.width and 0 <= y <= grid.p.height):
            return None
        clash = False
        for other in claimed:
            same = other.pin.net == pin.net
            for k, (lay, r) in enumerate(shapes):
                for ok, (ol, orr) in enumerate(other.shapes):
                    if lay != ol or not _too_close(r, orr, t.layer_sep.get(lay, 0.0)):
                        continue
                    gx, gy = _gap(r, orr)
                    # same net may overlap, not nearly touch. Two via pads (index > 0; 0 is the stub)
                    # may only overlap when concentric: off-centre, their via cuts sit closer than
                    # the cut spacing (gf180 V2.2a/V3.2a: two VDD landings 0.49um apart)
                    concentric = abs(x - other.x) < 1e-6 and abs(y - other.y) < 1e-6
                    if not (same and gx <= 0 and gy <= 0 and (k == 0 or ok == 0 or concentric)):
                        clash = True
                        break
                if clash:
                    break
            if clash:
                break
        if clash:
            continue
        neigh = [n for n in cand if n not in grid.blocked and not grid.reserved.get(n)]
        if not neigh:
            continue
        # the new pin must be able to get out, and must not trap a pin already landed
        new_nodes, new_edges = grid.would_reserve(pads)
        if not grid.has_escape(pin.net, neigh, set(), set(), new_nodes, new_edges):
            continue
        if any(not grid.has_escape(other.pin.net, [n for n in other.neighbours if grid.node_ok(n, other.pin.net)],
                                   new_nodes, new_edges)
               for other in claimed):
            continue
        node = ("P", len(grid.pos))
        return Landing(pin, opt, x, y, z, node, neigh, shapes)
    return None


def _combo_key(pins: Sequence[RouterPin], combo: Sequence[AccessOption]) -> tuple:
    """Identity of one access option per pin, for excluding a side combination."""
    return tuple((p.owner, o.side, round(o.x, 3), round(o.y, 3)) for p, o in zip(pins, combo))


def _hpwl(pts: Sequence[tuple[float, float]]) -> float:
    return (max(x for x, _ in pts) - min(x for x, _ in pts)) + (max(y for _, y in pts) - min(y for _, y in pts))


def _plan_access(grid: RoutingGrid, pt: Optional[ProcessTable], exclude: Optional[dict[str, set[tuple]]] = None,
                 spread: bool = True) -> tuple[dict[str, list[Landing]], list[str]]:
    """Choose each pin's side and land it.

    ``exclude``: net -> side combinations (``_combo_key``) not to choose.
    ``spread=False`` breaks HPWL ties by option order alone (the original rule).
    """
    t = grid.t
    margin = t.pitch * 1.5
    exclude = exclude or {}

    def est(o: AccessOption) -> tuple[float, float]:
        dx, dy = _DIR[o.side]
        return (o.x + dx * margin, o.y + dy * margin)

    def chan(p: RouterPin, o: AccessOption) -> tuple[float, float]:
        """Where the pin will land: just outside its cell, on the option's side."""
        x0, y0, x1, y1 = grid.p.cells[p.cell]
        return {"W": (x0 - margin, o.y), "E": (x1 + margin, o.y),
                "S": (o.x, y0 - margin), "N": (o.x, y1 + margin)}[o.side]

    taken: list[tuple[float, float]] = []      # landing estimates of the pins already given a side

    def load(pts: Sequence[tuple[float, float]]) -> int:
        """Landings already chosen inside the region a net with these landings would route through."""
        x0, x1 = min(x for x, _ in pts) - margin, max(x for x, _ in pts) + margin
        y0, y1 = min(y for _, y in pts) - margin, max(y for _, y in pts) + margin
        return sum(x0 <= x <= x1 and y0 <= y <= y1 for x, y in taken)

    # 1. side choice per net (paper step 2): exhaustive over pin options, min HPWL.
    # Combinations within half a pitch of the minimum are ties (landings snap to
    # the grid anyway), broken by load, then HPWL, then option order.
    cands: dict[str, list[tuple[float, tuple[AccessOption, ...]]]] = {}
    for net, pins in grid.p.nets.items():
        opts = [p.options for p in pins]
        if math.prod(max(1, len(o)) for o in opts) <= 4096:
            scored = [(_hpwl([est(o) for o in combo]), combo) for combo in itertools.product(*opts)]
            kept = [s for s in scored if _combo_key(pins, s[1]) not in exclude.get(net, ())]
            cands[net] = kept or scored
        else:      # too many to enumerate: nearest option to the centroid (exclusions not applied)
            cx = sum(o.x for p in pins for o in p.options) / sum(len(p.options) for p in pins)
            cy = sum(o.y for p in pins for o in p.options) / sum(len(p.options) for p in pins)
            cands[net] = [(0.0, tuple(min(p.options, key=lambda o: abs(est(o)[0] - cx) + abs(est(o)[1] - cy))
                                      for p in pins))]
    chosen: dict[str, list[tuple[RouterPin, list[AccessOption]]]] = {}
    for net in sorted(cands, key=lambda n: (-min(hp for hp, _ in cands[n]), n)):     # longest nets first
        pins = grid.p.nets[net]
        best_hp = min(hp for hp, _ in cands[net])
        ties = [(hp, c) for hp, c in cands[net] if hp <= best_hp + t.pitch / 2]
        _, best = min(ties, key=lambda hc: (load([chan(p, o) for p, o in zip(pins, hc[1])]) if spread else 0,
                                            round(hc[0], 9)))
        pref = list(best)
        taken.extend(chan(p, o) for p, o in zip(pins, pref))
        ranked = []
        for p, first in zip(pins, pref):
            rest = sorted((o for o in p.options if o is not first),
                          key=lambda o: sum(abs(est(o)[0] - est(f)[0]) + abs(est(o)[1] - est(f)[1]) for f in pref))
            ranked.append((p, [first] + rest))
        chosen[net] = ranked
    # 2. landings, deterministic order
    order = sorted(((p, opts) for ranked in chosen.values() for p, opts in ranked),
                   key=lambda po: (po[0].cell, po[1][0].side, round(po[1][0].y, 3), round(po[1][0].x, 3), po[0].owner))
    landings: dict[str, list[Landing]] = {}
    claimed: list[Landing] = []
    unreachable = []
    back: dict[tuple, list[tuple]] = {}
    for pin, opts in order:
        land = None
        for opt in opts:
            land = _try_landing(grid, pin, opt, claimed)
            if land is not None:
                break
        if land is None:
            unreachable.append(pin.owner)
            continue
        claimed.append(land)
        landings.setdefault(pin.net, []).append(land)
        lid = len(grid.landings)
        grid.landings.append(land)
        grid.adj.append(set(land.neighbours))
        grid.pos[land.node] = (land.x, land.y)
        grid.pin_z[land.node] = land.z
        grid.pin_of[land.node] = pin.net
        grid.pin_adj[land.node] = land.neighbours
        for n in land.neighbours:
            back.setdefault(n, []).append(land.node)
        for lay, r in land.shapes[1:]:
            grid.reserve(lid, lay, r)
    # a later reservation can take away an earlier pin's only neighbour
    for lid, land in enumerate(grid.landings):
        ok = [n for n in land.neighbours if grid.node_ok(n, land.pin.net)]
        if not ok:
            unreachable.append(land.pin.owner)
            landings[land.pin.net].remove(land)
        land.neighbours[:] = ok
        grid.adj[lid] = set(ok)
    grid._pin_back = back
    return landings, unreachable


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def _D(grid: RoutingGrid, a: tuple, b: tuple) -> float:
    (ax, ay), (bx, by) = grid.xy(a), grid.xy(b)
    return abs(ax - bx) + abs(ay - by) + grid.t.c_via * abs(grid.layer(a) - grid.layer(b))


def _f(g: float, h: float, kappa: float) -> float:
    return g + h if g < h else (g + (2 * kappa - 1) * h) / kappa


def bidirectional_astar(grid: RoutingGrid, net: str, source: tuple, target_tree: set[tuple], target_hint: tuple,
                        occ: dict[tuple, set[str]], hist: dict[tuple, float]) -> Optional[list[tuple]]:
    """Path from ``source`` to any node of ``target_tree`` (paper Eq. 3-5)."""
    t = grid.t

    def step_cost(a: tuple, b: tuple) -> float:
        c = _D(grid, a, b) + hist.get(b, 0.0)
        others = occ.get(b)
        if others and (others - {net}):
            c += t.c_drc
        return c

    def h(n: tuple, goal: tuple) -> float:
        return _D(grid, n, goal) * (1 + t.q)

    if source in target_tree:
        return [source]
    sides = []
    # the tree's order is the heap's tie-break: a set's order follows string hashing (pin nodes are
    # ("P", k)), which changes with every interpreter, and so did the routes; sort it instead
    tree = sorted(target_tree, key=lambda n: (1, n[1], 0, 0) if n[0] == "P" else (0, *n))
    for starts, goal in (([source], target_hint), (tree, source)):
        g = {s: 0.0 for s in starts}
        parent = {s: None for s in starts}
        heap = [(_f(0.0, h(s, goal), t.kappa), k, s) for k, s in enumerate(starts)]
        heapq.heapify(heap)
        sides.append({"g": g, "parent": parent, "heap": heap, "goal": goal, "closed": set()})
    counter = itertools.count(len(target_tree) + 1)
    turn = 0
    while sides[0]["heap"] or sides[1]["heap"]:
        s = sides[turn] if sides[turn]["heap"] else sides[1 - turn]
        o = sides[1] if s is sides[0] else sides[0]
        _, _, u = heapq.heappop(s["heap"])
        turn = 1 - turn
        if u in s["closed"]:
            continue
        s["closed"].add(u)
        if u in o["g"]:
            # meet: stitch forward(source..u) + backward(u..tree)
            fwd, bwd = (s, o) if s is sides[0] else (o, s)
            path, n = [], u
            while n is not None:
                path.append(n)
                n = fwd["parent"][n]
            path.reverse()
            n = bwd["parent"][u]
            while n is not None:
                path.append(n)
                n = bwd["parent"][n]
            return path
        gu = s["g"][u]
        for v in grid.neighbours(u):
            if not grid.node_ok(v, net) or not grid.edge_ok(u, v, net):
                continue
            # the backward search walks edges in reverse; costs are symmetric except H(n),
            # which is charged on the node entered in the forward direction
            gv = gu + (step_cost(u, v) if s is sides[0] else step_cost(v, u))
            if gv < s["g"].get(v, math.inf) - 1e-12:
                s["g"][v] = gv
                s["parent"][v] = u
                heapq.heappush(s["heap"], (_f(gv, h(v, s["goal"]), t.kappa), next(counter), v))
    return None


def _mst_order(grid: RoutingGrid, lands: list[Landing]) -> list[tuple[Landing, Landing]]:
    """Prim's MST over pin landings; returns (new pin, parent pin) in tree order."""
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


def _path_wire(grid: RoutingGrid, plist: Sequence[Sequence[tuple]]) -> float:
    """Router-layer wire length of a net's paths (vias and stubs not included)."""
    wl = 0.0
    for path in plist:
        for a, b in zip(path, path[1:]):
            if grid.layer(a) == grid.layer(b):
                (ax, ay), (bx, by) = grid.xy(a), grid.xy(b)
                wl += abs(ax - bx) + abs(ay - by)
    return wl


def _mst_length(pts: Sequence[tuple[float, float]]) -> float:
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
        wire = _path_wire(g, plist)
        ref = _mst_length([(l.x, l.y) for l in result.landings.get(net, [])])
        if wire > t.detour_ratio * max(ref, t.pitch) and wire - ref >= t.detour_min:
            out[net] = wire - ref
    return out


def _cost(r: RoutingResult) -> float:
    return r.wirelength + r.tech.c_via * r.vias


def _attempt(problem: RoutingProblem, tech: RouterTech, pt: ProcessTable,
             exclude: Optional[dict[str, set[tuple]]] = None, spread: bool = True) -> RoutingResult:
    """One routing pass: grid, pin access, routing with rip-up/reroute. Stages go to ``pt``."""
    with pt.stage("Grid") as st:
        grid = RoutingGrid(problem, tech)
        st.detail(f"{grid.nx}x{grid.ny}x2 nodes, {len(grid.blocked)} blocked by {len(problem.cells)} cells")
    with pt.stage("Pin access") as st:
        landings, unreachable = _plan_access(grid, pt, exclude, spread)
        n_land = sum(len(v) for v in landings.values())
        sides = {}
        for lands in landings.values():
            for l in lands:
                sides[l.option.side] = sides.get(l.option.side, 0) + 1
        st.detail(f"{n_land} pins landed, sides {sides}")
        if unreachable:
            st.fail(f"no legal landing: {unreachable}")
    nets = [n for n in problem.nets if len(landings.get(n, [])) >= 2]
    hpwl = {}
    for n in nets:
        xs = [l.x for l in landings[n]]
        ys = [l.y for l in landings[n]]
        hpwl[n] = (max(xs) - min(xs)) + (max(ys) - min(ys))
    fails = {n: 0 for n in nets}
    occ: dict[tuple, set[str]] = {}
    hist: dict[tuple, float] = {}
    paths: dict[str, list[list[tuple]]] = {}
    dead: set[str] = set()
    history = []

    def rip(net: str) -> None:
        for path in paths.pop(net, []):
            for n in path:
                s = occ.get(n)
                if s:
                    s.discard(net)
                    if not s:
                        del occ[n]

    def route_net(net: str) -> bool:
        tree: set[tuple] = set()
        out = []
        for new, parent in _mst_order(grid, landings[net]):
            if new is parent:
                tree.add(new.node)
                continue
            path = bidirectional_astar(grid, net, new.node, tree, parent.node, occ, hist)
            if path is None:
                return False
            out.append(path)
            tree.update(path)
        paths[net] = out
        for path in out:
            for n in path:
                occ.setdefault(n, set()).add(net)
        return True

    with pt.stage("Route + rip-up/reroute") as st:
        queue = sorted(nets, key=lambda n: (-fails[n], -hpwl[n], -len(landings[n]), n))
        it = 0
        conflicts = {}
        while True:
            it += 1
            for net in queue:
                rip(net)
                if not route_net(net):
                    dead.add(net)
            conflicts = {n: s for n, s in occ.items() if len(s) > 1}
            bad = sorted({net for s in conflicts.values() for net in s} - dead)
            history.append({"iteration": it, "conflict_nodes": len(conflicts), "ripped": len(bad),
                            "unroutable": len(dead)})
            if not bad or it >= tech.max_iterations:
                break
            for net in bad:
                fails[net] += 1
                for path in paths.get(net, []):
                    for n in path:
                        hist[n] = hist.get(n, 0.0) + tech.h_inc
            queue = sorted(bad, key=lambda n: (-fails[n], -hpwl[n], -len(landings[n]), n))
        st.detail(f"{it} iteration(s), {len(conflicts)} conflict node(s) left, {len(dead)} unroutable")
    failed = sorted(dead | {net for s in conflicts.values() for net in s})
    wl, vias = 0.0, 0
    for net, plist in paths.items():
        wl += _path_wire(grid, plist)
        vias += sum(1 for path in plist for a, b in zip(path, path[1:]) if grid.layer(a) != grid.layer(b))
    for lands in landings.values():
        for l in lands:
            wl += abs(l.x - l.option.x) + abs(l.y - l.option.y)
            vias += 1
    success = not failed and not unreachable
    spots = [grid.xy(n) for n in conflicts]
    for net in dead:
        spots += [(l.x, l.y) for l in landings.get(net, [])]
    for owner in unreachable:
        for pins in problem.nets.values():
            for p in pins:
                if p.owner == owner:
                    spots += [(o.x, o.y) for o in p.options]
    return RoutingResult(success, it, failed, unreachable, paths, landings, wl, vias, len(conflicts), tech,
                         grid, history, spots)


def _reland_detours(problem: RoutingProblem, tech: RouterTech, result: RoutingResult, st,
                    spread: bool = True) -> RoutingResult:
    """Retry detoured nets with their side combination excluded (module docstring, step 7)."""
    found = detours(result)
    if not found:
        st.detail("none")
        return result
    best, exclude, tried, kept = result, {}, set(), []
    for _ in range(tech.max_relands):
        cand = {n: e for n, e in detours(best).items() if n not in tried}
        if not cand:
            break
        net = max(cand, key=lambda n: (cand[n], n))
        tried.add(net)
        pins = problem.nets[net]
        landed = {l.pin.owner: l.option for l in best.landings.get(net, [])}
        if any(p.owner not in landed for p in pins):
            continue
        trial_ex = {**exclude, net: set(exclude.get(net, ())) | {_combo_key(pins, [landed[p.owner] for p in pins])}}
        trial = _attempt(problem, tech, ProcessTable("detour retry"), trial_ex, spread)     # never printed
        if trial.success and _cost(trial) < _cost(best) - 1e-9:
            best, exclude = trial, trial_ex
            kept.append(net)
    found_txt = ", ".join(f"{n} +{e:.1f}µm" for n, e in sorted(found.items()))
    if kept:
        st.detail(f"{found_txt}; re-landed {', '.join(kept)}: wirelength {result.wirelength:.1f} -> "
                  f"{best.wirelength:.1f}µm, vias {result.vias} -> {best.vias}")
    else:
        st.detail(f"{found_txt}; no re-landing was cheaper")
    return best


def route(problem: RoutingProblem, tech: RouterTech, title: str = "Route", verbose: bool = True) -> RoutingResult:
    with ProcessTable(title, f"{len(problem.nets)} nets, pitch {tech.pitch}µm on {'/'.join(tech.layers)}") as pt:
        result, spread = _attempt(problem, tech, pt), True
        if not result.success:
            # spreading ties ignores how many pins a cell side can land: it can
            # take the spot a pin with no other legal side needed. The original
            # tie rule reproduces the old router's landings, so never route worse.
            # On a double failure the plain result is kept too, so the closed
            # loop sees the same failure spots and grows the same padding.
            with pt.stage("Ties fallback") as st:
                result, spread = _attempt(problem, tech, ProcessTable("plain ties"), spread=False), False    # never printed
                if result.success:
                    st.detail("spread side ties did not route; first-listed sides do")
                else:
                    st.warn("first-listed sides do not route either")
        if result.success and tech.detour_ratio > 0:
            with pt.stage("Detours") as st:
                result = _reland_detours(problem, tech, result, st, spread)
        with pt.stage("Result") as st:
            st.detail(f"wirelength {result.wirelength:.2f}µm, {result.vias} via stacks")
            if not result.success:
                st.fail(f"failed nets {result.failed_nets}"
                        + (f", unreachable pins {result.unreachable}" if result.unreachable else ""))
        pt.result("routed", "yes" if result.success else "NO")
        pt.result("iterations", result.iterations)
        pt.result("wirelength_um", f"{result.wirelength:.2f}")
        pt.result("vias", result.vias)
    if verbose and len(result.history) > 1:
        print_table(f"{title}: rip-up/reroute", ["iteration", "conflict nodes", "ripped", "unroutable"],
                    [(h["iteration"], h["conflict_nodes"], h["ripped"], h["unroutable"]) for h in result.history])
    return result
