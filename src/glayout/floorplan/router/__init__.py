"""Two-layer grid router for the nets between floorplan blocks (paper §1.10).

1. **Grid** (``grid``). A 3-D graph: layer 0 carries horizontal wires, layer 1 vertical
   ones, vias join them. The pitch is the largest ``via pad + spacing`` of the
   two layers, so a via or a wire end on any node is legal next to any other
   net on the neighbouring tracks. Nodes and edges whose shapes would come
   closer than the spacing rule to a cell are removed (cells are obstacles).
2. **Pin access + sides** (``access``). Each block pin offers ports on one or more
   block sides (rail ends E/W, tie ring N/E/S/W). For every net the side
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
3. **Decomposition** (``negotiate``). Multi-pin nets are connected in
   minimum-spanning-tree order; each new pin is routed to the part of its net
   already routed.
4. **Net order** (``negotiate``). More past failures first, then larger HPWL, then more pins.
5. **Search** (``astar``). Bidirectional A* with the paper's costs::

       D(n,k) = |dx| + |dy| + c_via·|dz|                          (Eq. 3)
       g(n)   = g(k) + D(n,k) + c_DRC·[n used by another net] + H(n)  (Eq. 4)
       h(n)   = D(t,n)·(1+q),  q = 1e-4
       f(n)   = g + h            if g < h
              = (g + (2κ-1)h)/κ  otherwise, κ = 3                 (Eq. 5)

6. **Rip-up and reroute** (``negotiate``). Nets that share a node with another net are
   ripped up, the history cost H of the nodes they used is raised, and they
   are rerouted. After 35 iterations with conflicts left, routing fails.
7. **Detours** (``driver``). Rip-up and reroute fixes conflicts, not detours: a net
   walled off by other nets' landings routes around a block and counts as
   routed. A routed net whose wire exceeds ``detour_ratio`` times the MST
   of its landings (and by ``detour_min``) is re-landed: its side
   combination is excluded, everything is routed again, and the change is
   kept only if wirelength + c_via·vias goes down. Worst detour first, at
   most ``max_relands`` tries.

Layers are directional, so every bend is a via: the paper's low-bending rule
is the via cost. Wires are drawn at via-pad width rather than minimum width,
so a via never needs extra enclosure.

Modules: ``geometry`` (rectangles, spacing test), ``tech`` (``RouterTech``), ``problem``
(problem and result types), ``grid`` (``RoutingGrid``), ``access`` (pin access), ``astar``,
``metrics`` (HPWL, MST, wirelength, detours), ``negotiate`` (one routing pass) and
``driver`` (``route``).
"""
from glayout.floorplan.router.astar import bidirectional_astar, f_cost, step_distance
from glayout.floorplan.router.driver import route
from glayout.floorplan.router.geometry import H, V, Rect, too_close
from glayout.floorplan.router.grid import RoutingGrid
from glayout.floorplan.router.metrics import detours, mst_length, path_wire
from glayout.floorplan.router.problem import AccessOption, Landing, RouterPin, RoutingProblem, RoutingResult
from glayout.floorplan.router.tech import RouterTech, track_pitch

__all__ = [
    "AccessOption", "H", "Landing", "Rect", "RouterPin", "RouterTech", "RoutingGrid", "RoutingProblem",
    "RoutingResult", "V", "bidirectional_astar", "detours", "f_cost", "mst_length", "path_wire", "route",
    "step_distance", "too_close", "track_pitch",
]
