"""The routing grid: nodes, edges, cells as obstacles, and reservations around pin landings.

A grid node is ``(z, i, j)``: router layer ``z`` (``H`` or ``V``) at column ``i``, row ``j``. A
landed pin is an extra node ``("P", k)`` joined to the grid nodes next to its via. Layer ``H``
only has edges along x and layer ``V`` only along y, and every (i, j) has a via between the
two, so every bend is a via. An edge is keyed by its lower end, ``min(a, b)``.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from glayout.floorplan.router.geometry import H, V, Rect, square, too_close
from glayout.floorplan.router.problem import Landing, RoutingProblem
from glayout.floorplan.router.tech import RouterTech


class RoutingGrid:
    """The grid over a ``RoutingProblem`` and which nodes and edges each net may use.

    ``p`` and ``t`` are the problem and the tech. Nodes and edges whose shapes come closer than
    the spacing rule to a cell are ``blocked``; those close to a landing's via pads are
    ``reserved`` for that landing (see ``node_ok``).
    """

    def __init__(self, problem: RoutingProblem, tech: RouterTech):
        """Lay the grid over the problem, half a pitch in from the origin, and block the cells."""
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
        self.landings: list[Landing] = []
        self.adj: list[set[tuple]] = []                   # landing id -> its pin's grid neighbours
        self.pin_adj: dict[tuple, list[tuple]] = {}       # pin node -> grid neighbours
        self.pin_of: dict[tuple, str] = {}                # pin node -> net
        self.pos: dict[tuple, tuple[float, float]] = {}   # pin node positions
        self.pin_z: dict[tuple, int] = {}                 # pin node router layer
        self.pin_back: dict[tuple, list[tuple]] = {}      # grid node -> pin nodes next to it (set after access)
        self._block_cells()

    # coordinates -------------------------------------------------------
    def xy(self, n: tuple) -> tuple[float, float]:
        """Position of a grid or pin node, µm."""
        if n[0] == "P":
            return self.pos[n]
        return (self.x0 + n[1] * self.t.pitch, self.y0 + n[2] * self.t.pitch)

    def layer(self, n: tuple) -> int:
        """Router layer of a node (a pin node is on the layer its via lands on)."""
        return self.pin_z[n] if n[0] == "P" else n[0]

    def inside(self, i: int, j: int) -> bool:
        """Whether column ``i``, row ``j`` is on the grid."""
        return 0 <= i < self.nx and 0 <= j < self.ny

    def node_rect(self, z: int, i: int, j: int) -> Rect:
        """The wire-width square a wire end or bend draws at node (z, i, j)."""
        x, y = self.xy((z, i, j))
        return square(x, y, self.t.wire[z])

    def edge_rect(self, z: int, i: int, j: int) -> Rect:
        """Wire from (z,i,j) to its +1 neighbour along the layer's direction."""
        w = self.t.wire[z]
        x, y = self.xy((z, i, j))
        if z == H:
            return (x - w / 2, y - w / 2, x + self.t.pitch + w / 2, y + w / 2)
        return (x - w / 2, y - w / 2, x + w / 2, y + self.t.pitch + w / 2)

    # obstacles and reservations -----------------------------------------
    def _window(self, r: Rect, margin: float):
        """Column and row ranges of the nodes that can come within ``margin`` of ``r`` (one extra each way)."""
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
                if too_close(self.node_rect(z, i, j), r, sep):
                    nodes.append((z, i, j))
                if (z == H and i + 1 < self.nx) or (z == V and j + 1 < self.ny):
                    if too_close(self.edge_rect(z, i, j), r, sep):
                        edges.append((z, i, j))
        return nodes, edges

    def _block_cells(self) -> None:
        """Block every node and edge on either layer that would come too close to a cell."""
        for r in self.p.cells:
            for z in (H, V):
                nodes, edges = self._hits(z, r, self.t.sep[z])
                self.blocked.update(nodes)
                self.blocked_edges.update(edges)

    def would_reserve(self, shapes: Sequence[tuple[str, Rect]]) -> tuple[set[tuple], set[tuple]]:
        """Nodes and edges that landing pads ``shapes`` would reserve, without reserving them."""
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
        pin unless they are its own, ``own_*``). A breadth-first walk of at most
        ``max_depth`` steps that may only pass through the pin's own neighbours.
        """
        adj_set = set(adj)

        def free(m: tuple) -> bool:
            """Not blocked and reserved by nobody, including the landing being planned."""
            return (m not in self.blocked and not self.reserved.get(m) and m not in extra_nodes
                    and m not in own_nodes)

        def edge_fine(a: tuple, b: tuple) -> bool:
            """Whether this pin's wire may use the edge a-b (a via between layers always may)."""
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
        """Reserve for landing ``lid`` the nodes and edges too close to its pad ``r`` on ``layer``."""
        for z, lname in enumerate(self.t.layers):
            if lname != layer:
                continue
            nodes, edges = self._hits(z, r, self.t.sep[z])
            for n in nodes:
                self.reserved.setdefault(n, set()).add(lid)
            for e in edges:
                self.reserved_edges.setdefault(e, set()).add(lid)

    def register_landing(self, land: Landing) -> int:
        """Add a landed pin as a node of the graph; returns its landing id.

        Its pads are reserved separately (``reserve``) and the links from grid nodes back to it
        (``pin_back``) are set once all pins have landed.
        """
        lid = len(self.landings)
        self.landings.append(land)
        self.adj.append(set(land.neighbours))
        self.pos[land.node] = (land.x, land.y)
        self.pin_z[land.node] = land.z
        self.pin_of[land.node] = land.pin.net
        self.pin_adj[land.node] = land.neighbours
        return lid

    # passability ----------------------------------------------------------
    def node_ok(self, n: tuple, net: str) -> bool:
        """Whether ``net`` may use node ``n``.

        A pin node only by its own net; a reserved node only as a direct neighbour of a landing
        of ``net`` that reserved it (so the wire touches that pad), for every landing that did.
        """
        if n[0] == "P":
            return self.pin_of[n] == net
        if n in self.blocked:
            return False
        owners = self.reserved.get(n)
        return not owners or all(self.landings[l].pin.net == net and n in self.adj[l] for l in owners)

    def edge_ok(self, a: tuple, b: tuple, net: str) -> bool:
        """Whether ``net`` may use the edge a-b, by the same rule as ``node_ok``."""
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
        """Nodes one step from ``n``: along its layer's direction, the via, and any pin landed next to it."""
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
        for pn in self.pin_back.get(n, ()):
            yield pn
