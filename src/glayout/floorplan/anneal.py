"""Simulated-annealing floorplanner over sequence pairs and block variants.

Cost (paper Eq. 1, as a quantity to minimise):

    α · F_area / ΣA  +  β · HPWL / HPWL_ref  +  γ · (Ar* - Ar)²  +  δ · asym

- blocks are DRR-padded (``apply_drr``) before packing, so F_area includes
  the reserved routing space;
- HPWL uses real pin positions of the chosen variant;
- HPWL_ref is the best HPWL among random initial states (the paper uses the
  best metaheuristic result, HPWL_min);
- ``asym`` is the residual distance from the symmetry axis after a greedy
  legalisation that slides symmetric blocks onto the axis where free, divided
  by sqrt(ΣA). The paper has no symmetry term; it rejects violations with a
  −1000 penalty instead.

Moves: swap two blocks in Γ+, in Γ-, or in both; change one block's variant
(its symmetric partner follows).

Router feedback (the paper's named future work): with ``route_check``, every
candidate that would become the new best is routed first, and each failed
net or unreachable pin adds ``route_weight`` to its cost. A floorplan that
does not route can then neither be kept as the best nor hold the walk.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from glayout.floorplan.circuit import Circuit
from glayout.floorplan.sequence_pair import overlaps, pack
from glayout.util.process_table import ProcessTable, print_table


@dataclass
class FloorplanWeights:
    alpha: float = 10.0       # area
    beta: float = 100.0       # wirelength
    gamma: float = 5.0        # aspect ratio
    delta: float = 50.0       # symmetry residual
    aspect_target: float = 1.0


@dataclass
class Placed:
    instance: str
    x: float                  # padded box lower-left, µm
    y: float
    w: float                  # padded size
    h: float
    variant: int
    mirrored: bool = False


@dataclass
class FloorplanResult:
    circuit: Circuit
    placed: dict[str, Placed]
    metrics: dict
    weights: FloorplanWeights
    trace: list[dict] = field(default_factory=list)


@dataclass
class _State:
    gp: list[int]
    gn: list[int]
    var: list[int]

    def copy(self) -> "_State":
        return _State(list(self.gp), list(self.gn), list(self.var))


class _Evaluator:
    def __init__(self, circuit: Circuit, weights: FloorplanWeights):
        self.c = circuit
        self.wt = weights
        self.insts = circuit.instances
        self.idx = {inst.name: i for i, inst in enumerate(self.insts)}
        self.sum_area = sum(inst.block.area for inst in self.insts)
        self.partner = {}
        self.mirrored = set()
        for a, b in circuit.symmetric_pairs:
            self.partner[self.idx[a]] = self.idx[b]
            self.partner[self.idx[b]] = self.idx[a]
            self.mirrored.add(self.idx[b])
        self.self_sym = [self.idx[n] for n in circuit.self_symmetric]
        self.pairs = [(self.idx[a], self.idx[b]) for a, b in circuit.symmetric_pairs]
        self.nets = [[(self.idx[i], bnet) for i, bnet in pins]
                     for pins in circuit.net_pins(min_pins=2).values()]
        self.hpwl_ref = 1.0

    def geometry(self, s: _State):
        n = len(self.insts)
        vs = [self.insts[i].block.variants[s.var[i]] for i in range(n)]
        w = [v.padded_size[0] for v in vs]
        h = [v.padded_size[1] for v in vs]
        x, y = pack(s.gp, s.gn, w, h)
        width = max(x[i] + w[i] for i in range(n))
        height = max(y[i] + h[i] for i in range(n))
        self._legalise_symmetry(x, y, w, h, width)
        return vs, x, y, w, h, width, height

    def _legalise_symmetry(self, x, y, w, h, width):
        axis = width / 2
        for i in sorted(self.self_sym, key=lambda i: y[i]):
            target = axis - w[i] / 2
            if 0 <= target and target + w[i] <= width + 1e-9 and not overlaps(x, y, w, h, i, target):
                x[i] = target
        for a, b in self.pairs:
            half = abs((x[b] + w[b] / 2) - (x[a] + w[a] / 2)) / 2
            ta, tb = axis - half - w[a] / 2, axis + half - w[b] / 2
            if min(ta, tb) >= 0 and max(ta + w[a], tb + w[b]) <= width + 1e-9:
                xa, xb = x[a], x[b]
                x[a] = ta
                if overlaps(x, y, w, h, a, ta):
                    x[a] = xa
                    continue
                x[b] = tb
                if overlaps(x, y, w, h, b, tb):
                    x[a], x[b] = xa, xb

    def hpwl(self, vs, x, y) -> float:
        total = 0.0
        for pins in self.nets:
            xs, ys = [], []
            for i, bnet in pins:
                px, py = vs[i].pin_xy(bnet, mirrored=i in self.mirrored)
                xs.append(x[i] + px)
                ys.append(y[i] + py)
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
        return total

    def asymmetry(self, x, y, w, h, width) -> float:
        axis = width / 2
        r = sum(abs(x[i] + w[i] / 2 - axis) for i in self.self_sym)
        for a, b in self.pairs:
            r += abs((x[a] + w[a] / 2 + x[b] + w[b] / 2) / 2 - axis) + abs(y[a] - y[b])
        return r

    def evaluate(self, s: _State) -> tuple[float, dict]:
        vs, x, y, w, h, width, height = self.geometry(s)
        f_area = width * height
        hp = self.hpwl(vs, x, y)
        ar = width / height
        asym = self.asymmetry(x, y, w, h, width)
        terms = {
            "area": self.wt.alpha * f_area / self.sum_area,
            "hpwl": self.wt.beta * hp / self.hpwl_ref,
            "aspect": self.wt.gamma * (self.wt.aspect_target - ar) ** 2,
            "symmetry": self.wt.delta * asym / math.sqrt(self.sum_area),
        }
        used = sum(v.area for v in vs)
        info = {"width": width, "height": height, "area": f_area, "hpwl": hp, "aspect": ar,
                "dead_space": 1 - used / f_area, "asym_um": asym, "terms": terms,
                "x": x, "y": y, "w": w, "h": h}
        return sum(terms.values()), info


def _random_state(n: int, rng: random.Random, ev: _Evaluator) -> _State:
    gp = list(range(n))
    gn = list(range(n))
    rng.shuffle(gp)
    rng.shuffle(gn)
    var = [0] * n
    return _State(gp, gn, var)


def _move(s: _State, rng: random.Random, ev: _Evaluator) -> _State:
    t = s.copy()
    n = len(t.gp)
    kind = rng.random()
    multi = [i for i, inst in enumerate(ev.insts) if len(inst.block.variants) > 1]
    if kind < 0.2 and multi:
        i = rng.choice(multi)
        t.var[i] = rng.choice([k for k in range(len(ev.insts[i].block.variants)) if k != t.var[i]])
        if i in ev.partner:
            t.var[ev.partner[i]] = t.var[i]
        return t
    if n < 2:
        return t
    a, b = rng.sample(range(n), 2)
    if kind < 0.5:
        seqs = (t.gp,)
    elif kind < 0.8:
        seqs = (t.gn,)
    else:
        seqs = (t.gp, t.gn)
    for seq in seqs:
        ia, ib = seq.index(a), seq.index(b)
        seq[ia], seq[ib] = seq[ib], seq[ia]
    return t


def anneal_floorplan(
    circuit: Circuit,
    weights: Optional[FloorplanWeights] = None,
    seed: int = 0,
    cooling: float = 0.93,
    moves_per_stage: Optional[int] = None,
    max_stages: int = 250,
    patience: int = 25,
    ref_samples: int = 200,
    trace_every: int = 10,
    route_check: Optional[Callable[[dict, list[int]], dict]] = None,
    route_weight: float = 200.0,
) -> FloorplanResult:
    """``route_check(info, variants)`` returns a routing summary dict with
    ``failed_nets`` and ``unreachable`` lists (see ``route_flow.make_route_check``)."""
    weights = weights or FloorplanWeights()
    rng = random.Random(seed)
    ev = _Evaluator(circuit, weights)
    n = len(circuit.instances)
    moves_per_stage = moves_per_stage or max(60, 25 * n)
    trace: list[dict] = []
    routes = {"calls": 0, "failed": 0}
    route_cache: dict = {}

    def routed_cost(state: _State, c: float, info: dict) -> float:
        """Cost including the router's verdict (cached per state)."""
        if route_check is None:
            return c
        key = (tuple(state.gp), tuple(state.gn), tuple(state.var))
        if key not in route_cache:
            routes["calls"] += 1
            r = route_check(info, list(state.var))
            route_cache[key] = r
            if not r["success"]:
                routes["failed"] += 1
        r = route_cache[key]
        info["route"] = r
        return c + route_weight * (len(r["failed_nets"]) + len(r["unreachable"]))

    title = f"Floorplan anneal {circuit.name}" + (" (router feedback)" if route_check else "")
    with ProcessTable(title, f"{n} blocks, seed {seed}") as pt:
        with pt.stage("HPWL reference") as st:
            ev.hpwl_ref = 1.0
            samples = [_random_state(n, rng, ev) for _ in range(ref_samples)]
            hps = []
            for s in samples:
                vs, x, y, *_ = ev.geometry(s)
                hps.append(ev.hpwl(vs, x, y))
            ev.hpwl_ref = max(min(hps), 1e-6)
            st.detail(f"best of {ref_samples} random states: {ev.hpwl_ref:.2f}µm "
                      f"(median {sorted(hps)[len(hps) // 2]:.2f}µm)")
        with pt.stage("Initial state") as st:
            cur = min(samples, key=lambda s: ev.evaluate(s)[0])
            cur_cost, cur_info = ev.evaluate(cur)
            cur_cost = routed_cost(cur, cur_cost, cur_info)
            best, best_cost, best_info = cur.copy(), cur_cost, cur_info
            st.detail(f"cost {cur_cost:.2f}, HPWL {cur_info['hpwl']:.2f}µm, area {cur_info['area']:.1f}µm²")
        with pt.stage("T0 calibration") as st:
            ups = []
            for _ in range(100):
                c, _ = ev.evaluate(_move(cur, rng, ev))
                if c > cur_cost:
                    ups.append(c - cur_cost)
            t0 = (sum(ups) / len(ups)) / -math.log(0.8) if ups else 1.0
            st.detail(f"T0={t0:.3g} (80% uphill acceptance, {len(ups)} uphill samples)")
        with pt.stage("Anneal") as st:
            t = t0
            stale = 0
            stages = 0
            evaluated = 0
            for stage in range(max_stages):
                stages += 1
                accepted = 0
                improved = False
                for _ in range(moves_per_stage):
                    cand = _move(cur, rng, ev)
                    c, info = ev.evaluate(cand)
                    evaluated += 1
                    if c <= cur_cost or rng.random() < math.exp(-(c - cur_cost) / t):
                        if c < best_cost - 1e-9:
                            c = routed_cost(cand, c, info)
                        cur, cur_cost, cur_info = cand, c, info
                        accepted += 1
                        if c < best_cost - 1e-9:
                            best, best_cost, best_info = cand.copy(), c, info
                            improved = True
                if stage % trace_every == 0:
                    trace.append({"stage": stage, "T": t, "accept": accepted / moves_per_stage,
                                  "cost": cur_cost, "best": best_cost})
                stale = 0 if improved else stale + 1
                if stale >= patience or t < t0 * 1e-4:
                    break
                t *= cooling
            trace.append({"stage": stages - 1, "T": t, "accept": accepted / moves_per_stage,
                          "cost": cur_cost, "best": best_cost})
            st.detail(f"{stages} stages × {moves_per_stage} moves ({evaluated} evaluations), "
                      f"stopped at T={t:.3g}{' (no improvement)' if stale >= patience else ''}")
        if route_check is not None:
            with pt.stage("Router checks") as st:
                r = best_info.get("route") or route_check(best_info, list(best.var))
                best_info["route"] = r
                st.detail(f"{routes['calls']} floorplans routed, {routes['failed']} failed; "
                          f"best {'routes' if r['success'] else 'does NOT route: ' + str(r['failed_nets'] + r['unreachable'])}")
                if not r["success"]:
                    st.warn("no routable floorplan found")
        with pt.stage("Best") as st:
            terms = best_info["terms"]
            st.detail("terms " + ", ".join(f"{k}={v:.2f}" for k, v in terms.items()))
            if best_info["asym_um"] > 1e-6:
                st.warn(f"symmetry residual {best_info['asym_um']:.3f}µm")
        pt.result("cost", f"{best_cost:.2f}")
        pt.result("size_um", f"{best_info['width']:.2f}x{best_info['height']:.2f}")
        pt.result("HPWL_um", f"{best_info['hpwl']:.2f}")
        pt.result("dead_space", f"{best_info['dead_space']:.1%}")
    print_table(f"Anneal trace {circuit.name}", ["stage", "T", "accept", "cost", "best"],
                [(r["stage"], r["T"], f"{r['accept']:.0%}", r["cost"], r["best"]) for r in trace])
    placed = {}
    for i, inst in enumerate(circuit.instances):
        placed[inst.name] = Placed(inst.name, best_info["x"][i], best_info["y"][i], best_info["w"][i],
                                   best_info["h"][i], best.var[i], i in ev.mirrored)
    metrics = {k: v for k, v in best_info.items() if k not in ("x", "y", "w", "h")}
    metrics["cost"] = best_cost
    metrics["hpwl_ref"] = ev.hpwl_ref
    metrics["sum_block_area"] = ev.sum_area
    metrics["sequence_pair"] = {"gp": [circuit.instances[i].name for i in best.gp],
                                "gn": [circuit.instances[i].name for i in best.gn]}
    metrics["router_calls"] = routes["calls"]
    result = FloorplanResult(circuit, placed, metrics, weights, trace)
    print_placement(result)
    return result


def print_placement(result: FloorplanResult) -> None:
    rows = []
    for name, p in result.placed.items():
        inst = result.circuit[name]
        v = inst.block.variants[p.variant]
        rows.append((name, inst.block.kind, p.variant, f"({p.x + v.pad.left:.2f}, {p.y + v.pad.bottom:.2f})",
                     f"{v.width:.2f}x{v.height:.2f}", f"{p.w:.2f}x{p.h:.2f}", "yes" if p.mirrored else ""))
    m = result.metrics
    print_table(f"Placement {result.circuit.name}",
                ["instance", "kind", "variant", "cell origin µm", "cell µm", "padded µm", "mirrored"], rows,
                caption=f"floorplan {m['width']:.2f}x{m['height']:.2f}µm, dead space {m['dead_space']:.1%}, "
                        f"HPWL {m['hpwl']:.2f}µm, aspect {m['aspect']:.2f}")
