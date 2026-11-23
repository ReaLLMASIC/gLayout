"""One routing pass: grid, pin access, then routing with rip-up and reroute.

Multi-pin nets are connected in minimum-spanning-tree order, each new pin routed to the part
of its net already routed. Nets go in order of more past failures, then larger HPWL, then more
pins. Nets that share a node with another net are ripped up, the history cost H of the nodes
they used is raised, and they are routed again; after ``max_iterations`` rounds with conflicts
left, the pass fails.
"""
from __future__ import annotations

from typing import Optional

from glayout.floorplan.router.access import plan_access
from glayout.floorplan.router.astar import bidirectional_astar
from glayout.floorplan.router.grid import RoutingGrid
from glayout.floorplan.router.metrics import hpwl, mst_order, path_wire
from glayout.floorplan.router.problem import Landing, RoutingProblem, RoutingResult
from glayout.floorplan.router.tech import RouterTech
from glayout.util.process_table import ProcessTable


class _Negotiation:
    """Rip-up and reroute state: which nets use each node, history costs, and each net's paths."""

    def __init__(self, grid: RoutingGrid, landings: dict[str, list[Landing]], nets: list[str], tech: RouterTech):
        """Start with nothing routed; ``nets`` are the nets with at least two landed pins."""
        self.grid = grid
        self.landings = landings
        self.nets = nets
        self.tech = tech
        self.hpwl = {n: hpwl([(l.x, l.y) for l in landings[n]]) for n in nets}
        self.fails = {n: 0 for n in nets}
        self.occ: dict[tuple, set[str]] = {}            # node -> nets using it
        self.hist: dict[tuple, float] = {}              # node -> history cost H
        self.paths: dict[str, list[list[tuple]]] = {}
        self.dead: set[str] = set()                     # nets A* found no path for
        self.history: list[dict] = []

    def order(self, nets) -> list[str]:
        """Routing order: more past failures first, then larger HPWL, then more pins, then name."""
        return sorted(nets, key=lambda n: (-self.fails[n], -self.hpwl[n], -len(self.landings[n]), n))

    def rip(self, net: str) -> None:
        """Remove ``net``'s paths and free the nodes they used."""
        for path in self.paths.pop(net, []):
            for n in path:
                s = self.occ.get(n)
                if s:
                    s.discard(net)
                    if not s:
                        del self.occ[n]

    def route_net(self, net: str) -> bool:
        """Route ``net`` pin by pin in MST order; False (nothing recorded) if a pin cannot be reached."""
        tree: set[tuple] = set()
        out = []
        for new, parent in mst_order(self.landings[net]):
            if new is parent:
                tree.add(new.node)          # the root starts the tree
                continue
            path = bidirectional_astar(self.grid, net, new.node, tree, parent.node, self.occ, self.hist)
            if path is None:
                return False
            out.append(path)
            tree.update(path)
        self.paths[net] = out
        for path in out:
            for n in path:
                self.occ.setdefault(n, set()).add(net)
        return True

    def run(self) -> tuple[int, dict[tuple, set[str]]]:
        """Route everything, then rip up and reroute until no node is shared or the iteration limit.

        Returns the number of iterations and the nodes still used by more than one net.
        """
        queue = self.order(self.nets)
        it = 0
        conflicts: dict[tuple, set[str]] = {}
        while True:
            it += 1
            for net in queue:
                self.rip(net)
                if not self.route_net(net):
                    self.dead.add(net)
            conflicts = {n: s for n, s in self.occ.items() if len(s) > 1}
            bad = sorted({net for s in conflicts.values() for net in s} - self.dead)
            self.history.append({"iteration": it, "conflict_nodes": len(conflicts), "ripped": len(bad),
                                 "unroutable": len(self.dead)})
            if not bad or it >= self.tech.max_iterations:
                break
            # make contested nodes dearer for everyone; a node on several of a net's paths counts each time
            for net in bad:
                self.fails[net] += 1
                for path in self.paths.get(net, []):
                    for n in path:
                        self.hist[n] = self.hist.get(n, 0.0) + self.tech.h_inc
            queue = self.order(bad)
        return it, conflicts


def _totals(grid: RoutingGrid, paths: dict[str, list[list[tuple]]],
            landings: dict[str, list[Landing]]) -> tuple[float, int]:
    """Wirelength and via count: grid wires and vias, plus each landing's stub and via stack."""
    wl, vias = 0.0, 0
    for net, plist in paths.items():
        wl += path_wire(grid, plist)
        vias += sum(1 for path in plist for a, b in zip(path, path[1:]) if grid.layer(a) != grid.layer(b))
    for lands in landings.values():
        for l in lands:
            wl += abs(l.x - l.option.x) + abs(l.y - l.option.y)
            vias += 1
    return wl, vias


def _hotspots(grid: RoutingGrid, problem: RoutingProblem, landings: dict[str, list[Landing]],
              conflicts: dict[tuple, set[str]], dead: set[str], unreachable: list[str]) -> list[tuple[float, float]]:
    """Where routing failed: conflict nodes, the landings of unroutable nets, the ports of unlanded pins."""
    spots = [grid.xy(n) for n in conflicts]
    for net in sorted(dead):        # a set of names iterates in string-hash order, which varies per process
        spots += [(l.x, l.y) for l in landings.get(net, [])]
    for owner in unreachable:
        for pins in problem.nets.values():
            for p in pins:
                if p.owner == owner:
                    spots += [(o.x, o.y) for o in p.options]
    return spots


def attempt(problem: RoutingProblem, tech: RouterTech, pt: ProcessTable,
            exclude: Optional[dict[str, set[tuple]]] = None, spread: bool = True) -> RoutingResult:
    """One routing pass: grid, pin access, routing with rip-up/reroute. Stages go to ``pt``.

    ``exclude`` and ``spread`` are passed to ``plan_access``.
    """
    with pt.stage("Grid") as st:
        grid = RoutingGrid(problem, tech)
        st.detail(f"{grid.nx}x{grid.ny}x2 nodes, {len(grid.blocked)} blocked by {len(problem.cells)} cells")
    with pt.stage("Pin access") as st:
        landings, unreachable = plan_access(grid, exclude, spread)
        n_land = sum(len(v) for v in landings.values())
        sides = {}
        for lands in landings.values():
            for l in lands:
                sides[l.option.side] = sides.get(l.option.side, 0) + 1
        st.detail(f"{n_land} pins landed, sides {sides}")
        if unreachable:
            st.fail(f"no legal landing: {unreachable}")
    nets = [n for n in problem.nets if len(landings.get(n, [])) >= 2]
    neg = _Negotiation(grid, landings, nets, tech)
    with pt.stage("Route + rip-up/reroute") as st:
        it, conflicts = neg.run()
        st.detail(f"{it} iteration(s), {len(conflicts)} conflict node(s) left, {len(neg.dead)} unroutable")
    failed = sorted(neg.dead | {net for s in conflicts.values() for net in s})
    wl, vias = _totals(grid, neg.paths, landings)
    success = not failed and not unreachable
    spots = _hotspots(grid, problem, landings, conflicts, neg.dead, unreachable)
    return RoutingResult(success, it, failed, unreachable, neg.paths, landings, wl, vias, len(conflicts), tech,
                         grid, neg.history, spots)
