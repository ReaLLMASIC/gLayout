"""Glue between the floorplanner and the router.

- ``problem_from_placement``: routing problem (cells as obstacles, pin access
  ports) straight from a placement, with no geometry built, so the annealer
  can call the router inside its loop.
- ``make_route_check``: that call, packaged for ``anneal_floorplan(route_check=...)``.
- ``closed_loop_floorplan``: router feedback on the padding. Start from little
  or no DRR padding, anneal with the router in the loop, route the result,
  and grow the padding only around blocks whose nets failed, until it routes.
- ``route_floorplan``: realise the cells, route, draw wires/vias/stubs, add
  top-level labels and the composed netlist, so the result can be checked
  with DRC *and* LVS end to end.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from glayout.backend import Component
from glayout.floorplan.anneal import FloorplanResult, FloorplanWeights, Placed, anneal_floorplan
from glayout.floorplan.block import Block
from glayout.floorplan.circuit import Circuit
from glayout.floorplan.drr import apply_drr
from glayout.floorplan.realize import cell_origin, realize_floorplan
from glayout.floorplan.router import (
    AccessOption, H, RouterPin, RouterTech, RoutingProblem, RoutingResult, route,
)
from glayout.pdk.mappedpdk import MappedPDK
from glayout.spice.netlist import Netlist
from glayout.util.process_table import ProcessTable, print_table

_MIRROR_SIDE = {"W": "E", "E": "W", "N": "N", "S": "S"}


def problem_from_placement(circuit: Circuit, placed: dict[str, Placed], width: float, height: float,
                           snap=lambda v: v) -> RoutingProblem:
    cells, nets = [], {}
    for k, inst in enumerate(circuit.instances):
        p = placed[inst.name]
        v = inst.block.variants[p.variant]
        ox, oy = snap(p.x + v.pad.left), snap(p.y + v.pad.bottom)
        cells.append((ox, oy, ox + v.width, oy + v.height))
        for bnet, pin in v.pins.items():
            cnet = inst.nets[bnet]
            access = pin.access or _projected(pin, v)
            opts = []
            for a in access:
                ax = v.width - a.x if p.mirrored else a.x
                side = _MIRROR_SIDE[a.side] if p.mirrored else a.side
                foreign = tuple(((v.width - f[2]) if p.mirrored else f[0], f[1],
                                 (v.width - f[0]) if p.mirrored else f[2], f[3], f[4]) for f in a.foreign)
                foreign = tuple((ox + f[0], oy + f[1], ox + f[2], oy + f[3], f[4]) for f in foreign)
                opts.append(AccessOption(side, ox + ax, oy + a.y, a.layer, a.width, foreign))
            nets.setdefault(cnet, []).append(RouterPin(cnet, f"{inst.name}.{bnet}", k, opts))
    return RoutingProblem(width, height, cells, nets)


def _projected(pin, v):
    """Abstract blocks (no ports): project the pin onto each of its sides, on met2."""
    from glayout.floorplan.block import Access
    out = []
    for s in pin.sides:
        x = {"W": 0.0, "E": v.width}.get(s, pin.x)
        y = {"S": 0.0, "N": v.height}.get(s, pin.y)
        out.append(Access(s, x, y, "met2", 0.0))
    return tuple(out)


def _placed_from_info(circuit: Circuit, info: dict, variants: Sequence[int]) -> dict[str, Placed]:
    return {inst.name: Placed(inst.name, info["x"][i], info["y"][i], info["w"][i], info["h"][i], variants[i])
            for i, inst in enumerate(circuit.instances)}


def make_route_check(circuit: Circuit, tech: RouterTech):
    """Router call for ``anneal_floorplan(route_check=...)``. Tables off inside the loop."""
    import os

    def check(info: dict, variants: list[int]) -> dict:
        placed = _placed_from_info(circuit, info, variants)
        prob = problem_from_placement(circuit, placed, info["width"], info["height"], tech.snap)
        old = os.environ.get("GLAYOUT_TABLES")
        os.environ["GLAYOUT_TABLES"] = "0"
        try:
            r = route(prob, tech, verbose=False)
        finally:
            if old is None:
                os.environ.pop("GLAYOUT_TABLES", None)
            else:
                os.environ["GLAYOUT_TABLES"] = old
        return r.summary()
    return check


def route_result(circuit: Circuit, result: FloorplanResult, tech: RouterTech, title: str = "Route") -> RoutingResult:
    m = result.metrics
    prob = problem_from_placement(circuit, result.placed, m["width"], m["height"], tech.snap)
    return route(prob, tech, title=title)


# ---------------------------------------------------------------------------
# closed loop
# ---------------------------------------------------------------------------

@dataclass
class ClosedLoopResult:
    floorplan: FloorplanResult
    routing: RoutingResult
    scales: dict[str, float]
    rounds: list[dict]


def closed_loop_floorplan(
    pdk: MappedPDK,
    circuit: Circuit,
    blocks: Sequence[Block],
    tech: Optional[RouterTech] = None,
    weights: Optional[FloorplanWeights] = None,
    seed: int = 0,
    start_scale: float = 0.0,
    step: float = 0.25,
    max_scale: float = 2.0,
    rounds: int = 10,
    in_loop: bool = False,
) -> ClosedLoopResult:
    """Router-feedback floorplanning.

    Each round: pad (per-block DRR scale), anneal, route the best floorplan.
    If routing fails, the DRR scale grows by ``step`` on the blocks nearest to
    where it failed: the conflict nodes left after rip-up and reroute, and
    the pins of unroutable nets or with no legal landing.

    ``in_loop`` also puts the router inside the annealer (every new best is
    routed, failures penalised). It is off by default: with little padding
    most compact floorplans fail, and the penalty then drives the search to
    sparse ones (63% vs 42% dead space on the two-stage OTA, gf180).
    """
    tech = tech or RouterTech.from_pdk(pdk)
    scales = {b.name: start_scale for b in blocks}
    log = []
    check = make_route_check(circuit, tech) if in_loop else None
    with ProcessTable(f"Closed-loop floorplan {circuit.name}",
                      f"start scale {start_scale}, step {step}, seed {seed}") as pt:
        for rnd in range(rounds):
            with pt.stage(f"round {rnd}") as st:
                apply_drr(pdk, blocks, scales=scales, layers=tech.layers, title=f"DRR padding (round {rnd})")
                fp = anneal_floorplan(circuit, weights, seed=seed, route_check=check)
                rr = route_result(circuit, fp, tech, title=f"Route (round {rnd})")
                m = fp.metrics
                failed = rr.failed_nets + [o.split(".")[1] for o in rr.unreachable]
                log.append({"round": rnd, "scales": dict(scales), "dead_space": m["dead_space"],
                            "area": m["area"], "hpwl": m["hpwl"], "routed": rr.success,
                            "failed": rr.failed_nets, "unreachable": rr.unreachable,
                            "wirelength": rr.wirelength, "vias": rr.vias, "iterations": rr.iterations,
                            "router_calls": m.get("router_calls", 0)})
                st.detail(f"dead space {m['dead_space']:.1%}, {'routed' if rr.success else 'failed ' + str(failed)}"
                          f" in {rr.iterations} it.")
                if rr.success:
                    break
                culprits = _culprits(circuit, fp, rr)
                grown = [b for b in sorted(culprits) if scales[b] < max_scale]
                if not grown:
                    st.warn("padding at max_scale everywhere it would help; giving up")
                    break
                for b in grown:
                    scales[b] = min(max_scale, scales[b] + step)
                st.detail(f"grow {grown}")
        pt.result("rounds", len(log))
        pt.result("routed", "yes" if log[-1]["routed"] else "NO")
        pt.result("dead_space", f"{log[-1]['dead_space']:.1%}")
    print_table(f"Closed loop {circuit.name}: rounds",
                ["round", "DRR scales", "dead space", "HPWL µm", "routed", "failed", "WL µm", "vias", "RRR it.",
                 "router calls"],
                [(r["round"], " ".join(f"{k}={v:g}" for k, v in r["scales"].items()), f"{r['dead_space']:.1%}",
                  f"{r['hpwl']:.1f}", "yes" if r["routed"] else "no", ",".join(r["failed"] + r["unreachable"]) or "—",
                  f"{r['wirelength']:.1f}", r["vias"], r["iterations"], r["router_calls"]) for r in log])
    return ClosedLoopResult(fp, rr, dict(scales), log)


def _culprits(circuit: Circuit, fp: FloorplanResult, rr: RoutingResult) -> set[str]:
    """Blocks whose padded box is nearest to each place routing failed."""
    out = set()
    boxes = [(inst.block.name, fp.placed[inst.name]) for inst in circuit.instances]
    for x, y in rr.hotspots:
        def dist(p) -> float:
            dx = max(p.x - x, 0.0, x - (p.x + p.w))
            dy = max(p.y - y, 0.0, y - (p.y + p.h))
            return dx + dy
        out.add(min(boxes, key=lambda b: (dist(b[1]), b[0]))[0])
    return out


def _net_of(circuit: Circuit, owner: str) -> str:
    inst, bnet = owner.split(".", 1)
    return circuit[inst].nets[bnet]


# ---------------------------------------------------------------------------
# geometry, labels, netlist
# ---------------------------------------------------------------------------

def _rect(comp: Component, pdk: MappedPDK, layer: str, r) -> None:
    x0, y0, x1, y1 = r
    comp.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=pdk.get_glayer(layer))


def draw_routes(pdk: MappedPDK, comp: Component, rr: RoutingResult) -> dict:
    """Draw stubs, landing vias, wires and vias of a RoutingResult into comp."""
    from glayout.primitives.via_gen import via_stack
    t, g = rr.tech, rr.grid
    counts = {"stubs": 0, "segments": 0, "vias": 0}
    for lands in rr.landings.values():
        for l in lands:
            _rect(comp, pdk, *l.shapes[0])
            ref = comp << via_stack(pdk, l.option.layer, t.layers[l.z])
            ref.move((l.x, l.y))
            counts["stubs"] += 1
    grid_via = via_stack(pdk, t.layers[H], t.layers[1 - H])
    for net, plist in rr.paths.items():
        for path in plist:
            run = [path[0]]
            for a, b in zip(path, path[1:]):
                za, zb = g.layer(a), g.layer(b)
                if za != zb:
                    _draw_run(comp, pdk, rr, run)
                    ref = comp << grid_via
                    ref.move(g.xy(a))
                    counts["vias"] += 1
                    run = [b]
                else:
                    run.append(b)
            _draw_run(comp, pdk, rr, run)
            counts["segments"] += 1
    return counts


def _draw_run(comp: Component, pdk: MappedPDK, rr: RoutingResult, run: list[tuple]) -> None:
    if len(run) < 2:
        return
    g, t = rr.grid, rr.tech
    z = g.layer(run[0])
    w = t.wire[z]
    pts = [g.xy(n) for n in run]
    # a run on one layer is straight, except where it passes through a pin node
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        r = (min(ax, bx) - w / 2, min(ay, by) - w / 2, max(ax, bx) + w / 2, max(ay, by) + w / 2)
        _rect(comp, pdk, t.layers[z], r)


def floorplan_netlist(circuit: Circuit, result: FloorplanResult, name: str) -> Netlist:
    top = Netlist(circuit_name=name, nodes=list(circuit.ports))
    for inst in circuit.instances:
        v = inst.block.variants[result.placed[inst.name].variant]
        nl = v.component.info["netlist"]
        top.connect_netlist(nl, [(node, inst.nets[node]) for node in nl.nodes])
    return top


def route_floorplan(pdk: MappedPDK, circuit: Circuit, result: FloorplanResult, tech: Optional[RouterTech] = None,
                    name: str = "routed_floorplan", labels: Optional[bool] = None) -> tuple[Component, RoutingResult]:
    """Realise, route and draw. ``labels`` defaults to gf180 only (klayout LVS needs them)."""
    tech = tech or RouterTech.from_pdk(pdk)
    labels = (pdk.name.lower() == "gf180") if labels is None else labels
    with ProcessTable(f"Routed floorplan {circuit.name}", name) as pt:
        with pt.stage("Realise") as st:
            top = realize_floorplan(pdk, result, name=f"{name}_cells", flatten=False)
            st.detail(f"{len(top.references)} cells")
        with pt.stage("Check placement vs problem") as st:
            prob = problem_from_placement(circuit, result.placed, result.metrics["width"],
                                          result.metrics["height"], tech.snap)
            worst = 0.0
            for ref, cell in zip(top.references, prob.cells):
                (x0, y0), (x1, y1) = ref.bbox
                worst = max(worst, abs(x0 - cell[0]), abs(y0 - cell[1]), abs(x1 - cell[2]), abs(y1 - cell[3]))
            st.detail(f"max cell bbox mismatch {worst:.4f}µm")
            if worst > 1e-6:
                st.fail("router and layout disagree on cell positions")
        with pt.stage("Route") as st:
            rr = route(prob, tech, title=f"Route {circuit.name}")
            st.detail("routed" if rr.success else f"FAILED {rr.failed_nets + rr.unreachable}")
            if not rr.success:
                st.status = "fail"
        with pt.stage("Draw") as st:
            counts = draw_routes(pdk, top, rr)
            st.detail(", ".join(f"{k} {v}" for k, v in counts.items()))
        with pt.stage("Labels") as st:
            placed = []
            if labels:
                for net in circuit.ports:
                    port = _label_port(circuit, result, prob, net)
                    if port is None:
                        st.warn(f"no met2 access for {net}")
                        continue
                    x, y = port
                    pin = Component(f"lbl_{net}")
                    _rect(pin, pdk, "met2_pin", (x - 0.135, y - 0.135, x + 0.135, y + 0.135))
                    pin.add_label(text=net, position=(x, y), layer=pdk.get_glayer("met2_label"))
                    top << pin
                    placed.append(net)
                st.detail(f"{placed}")
            else:
                st.status = "skip"
        with pt.stage("Netlist") as st:
            nl = floorplan_netlist(circuit, result, name.upper())
            st.detail(f"{name.upper()}({', '.join(circuit.ports)}), {len(circuit.instances)} instances")
        with pt.stage("Flatten") as st:
            flat = top.flatten()
            flat.name = name
            flat.info["netlist"] = nl
            flat.info["routing"] = rr.summary()
            st.detail(f"{flat.xsize:.2f}x{flat.ysize:.2f}µm")
        pt.result("routed", "yes" if rr.success else "NO")
        pt.result("wirelength_um", f"{rr.wirelength:.1f}")
        pt.result("vias", rr.vias)
    return flat, rr


def _label_port(circuit: Circuit, result: FloorplanResult, prob: RoutingProblem, net: str):
    """A point on met2 that belongs to ``net``: just inside a rail end."""
    for pin in prob.nets.get(net, []):
        for o in pin.options:
            if o.layer == "met2" and o.side in "EW":
                inward = 0.3 if o.side == "W" else -0.3
                return (o.x + inward, o.y)
    for pin in prob.nets.get(net, []):
        for o in pin.options:
            if o.layer == "met2":
                inward = -0.3 if o.side == "N" else 0.3
                return (o.x, o.y + inward)
    return None
