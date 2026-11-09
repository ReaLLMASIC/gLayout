"""Plan-selection methods evaluated on the fully verified catalogue of each task (offline replay; every method
sees only what it is entitled to see and pays for it).  Budget = number of full verifications (1, 2, 4, 8, 16).
Methods
  fixed_mode      : the named modes in a frozen order (FIXED_ORDER, set from development-size results before test
                    sizes were measured), then the remaining candidates by share score.
  share_most      : candidates ranked by (cross-device diffusion joins + shared gate conductors), more first.
  random          : uniform random order, 10 fixed seeds.
  neighbourhood   : structural beam search (width 4) over the axis vectors (neighbours differ in one axis value
                    of one group), starting from the independent plan, ranking unqueried neighbours by share score.
  cost_rank       : ascending cost.py estimate (one baseline assembly + plan formulas; no candidate geometry).
  geometry_first  : build EVERY candidate's geometry (charged), rank by its bounding-box area, verify in that order.
  baseline_independent: verify only the independent (unshared) plan.
  best_evaluated  : offline upper bound = best feasible candidate among all evaluated (not an online method).
A query returns the candidate's full result (feasible = primary_status auto_passed).  Result after n queries = smallest
feasible area among the queried candidates (None if none).  Time = method precomputation + sum of the per-candidate
verification wall time of the queried candidates (geometry, DRC, LVS, sizing, PEX, checks, render, post-layout sim)."""
from __future__ import annotations
import json, random
from pathlib import Path
from textbook_sharing import paths

PREFIXES = (1, 2, 4, 8, 16)


def _frozen_order():
    f = paths.FROZEN / "fixed_order.json"
    return json.load(open(f))["order"] if f.exists() else None


FIXED_ORDER = _frozen_order()   # frozen by selection.fixed_order from development sizes (data/frozen/fixed_order.json)
SEEDS = list(range(10))


TIMING = None


def _timing():
    """Controlled timings (textbook_sharing.selection.timing) when available: geometry times measured one at a time, and the
    per-task median end-to-end verification time charged for every full verification (same for every method)."""
    global TIMING
    if TIMING is None:
        f = paths.ANALYSIS / "timing_controlled.json"
        TIMING = json.load(open(f))["tasks"] if f.exists() else {}
    return TIMING


def load_task(td):
    td = Path(td); cat = json.load(open(td / "catalogue.json")); est = json.load(open(td / "estimates.json"))
    res = {}
    for cid in cat["entries"]:
        rp = td / cid / "result.json"
        if rp.exists(): res[cid] = json.load(open(rp))
    T = _timing().get(td.name)
    if T:
        for cid, r in res.items():
            r = dict(r); t = dict(r.get("timing_s") or {})
            t["geometry_generation"] = T["geometry_s"].get(cid, t.get("geometry_generation", 0.0))
            t["end_to_end"] = T["verification_median_s"]; r["timing_s"] = t; res[cid] = r
        est = dict(est); est["timing_s"] = {"baseline_geometry": T["baseline_geometry_s"], "estimates_total": T["cost_estimates_total_s"]}
    return cat, est, res


def share_score(cat, cid):
    s = 0
    for gi, pid in enumerate(cat["entries"][cid]["plan_ids"]):
        pl = cat["tables"][gi]["plans"][pid]
        fo = pl["finger_order"]
        s += sum(1 for i, j in enumerate(pl["diffusion_joins"]) if j and fo[i][0] != fo[i + 1][0])
        s += sum(1 for g in pl["gate_groups"] if len({fo[p][0] for p in g[0]}) > 1)
    return s


def axis_vec(cat, cid):
    v = []
    for gi, pid in enumerate(cat["entries"][cid]["plan_ids"]):
        tup = next((t for p, t in cat["tables"][gi]["unique"] if p == pid), None)
        v += [tup[k] for k in ("arrangement", "orientation", "diffusion", "gate", "strap_start", "contact_end")] if tup else ["independent"] * 6
    return tuple(v)


def named(cat, mode):
    return next((c for c, e in cat["entries"].items() if f"named:{mode}" in e["labels"]), None)


def order_for(method, cat, est, res, seed=None, fixed_order=None):
    ids = sorted(cat["entries"])
    if method == "share_most":
        return sorted(ids, key=lambda c: (-share_score(cat, c), c)), 0.0
    if method == "random":
        r = random.Random(seed); o = list(ids); r.shuffle(o); return o, 0.0
    if method == "cost_rank":
        pre = est["timing_s"]["baseline_geometry"] + est["timing_s"]["estimates_total"]
        return sorted(ids, key=lambda c: (est["estimates"][c]["area_hat"], c)), pre
    if method == "geometry_first":
        pre = sum((res.get(c, {}).get("timing_s") or {}).get("geometry_generation", 0.0) for c in ids)
        return sorted(ids, key=lambda c: ((res.get(c, {}).get("area_um2_assembly") or 1e18), c)), pre
    if method == "fixed_mode":
        first = [named(cat, m) for m in (fixed_order or FIXED_ORDER or ["combined", "gate_only", "diffusion_only", "independent"])]
        first = [c for i, c in enumerate(first) if c and c not in first[:i]]
        rest = sorted([c for c in ids if c not in first], key=lambda c: (-share_score(cat, c), c))
        return first + rest, 0.0
    raise ValueError(method)


def neighbourhood_order(cat, width=4, budget=16):
    ids = sorted(cat["entries"]); vec = {c: axis_vec(cat, c) for c in ids}
    start = named(cat, "independent") or ids[0]
    traj = [start]; seen = {start}; beam = [start]
    while len(traj) < min(budget, len(ids)):
        cand = set()
        for b in beam:
            for c in ids:
                if c in seen: continue
                if sum(1 for x, y in zip(vec[b], vec[c]) if x != y) == 1: cand.add(c)
        cand = sorted(cand, key=lambda c: (-share_score(cat, c), c))
        if not cand:
            cand = sorted([c for c in ids if c not in seen], key=lambda c: (-share_score(cat, c), c))
            if not cand: break
        for c in cand[:width]:
            if len(traj) >= budget: break
            traj.append(c); seen.add(c)
        beam = traj[-width:]
    return traj


def replay(order, res, pre_s):
    out = {}; best = None; t = pre_s; found_at = None
    for n, c in enumerate(order[:max(PREFIXES)], start=1):
        r = res.get(c, {})
        t += (r.get("timing_s") or {}).get("end_to_end", 0.0)
        if r.get("primary_status") == "auto_passed" and r.get("area_um2"):
            if best is None or r["area_um2"] < best: best = r["area_um2"]
            found_at = found_at or n
        if n in PREFIXES: out[n] = {"best_area": best, "time_s": round(t, 1)}
    for n in PREFIXES:
        if n not in out: out[n] = dict(out[max(k for k in out)]) if out else {"best_area": None, "time_s": round(t, 1)}
    return out, found_at


def evaluate_task(td, fixed_order=None):
    cat, est, res = load_task(td)
    feas = {c: r["area_um2"] for c, r in res.items() if r.get("primary_status") == "auto_passed" and r.get("area_um2")}
    best = min(feas.values()) if feas else None
    rows = []
    def add(method, order, pre, seed=None):
        rp, found = replay(order, res, pre)
        rows.append({"task": Path(td).name, "method": method, "seed": seed, "first_feasible_query": found, "precompute_s": round(pre, 2),
                     "prefix": {str(n): {**v, "gap": (v["best_area"] / best - 1) if (v["best_area"] and best) else None} for n, v in rp.items()},
                     "best_evaluated": best, "n_evaluated": len(res), "n_feasible": len(feas)})
    for m in ("fixed_mode", "share_most", "cost_rank", "geometry_first"):
        o, pre = order_for(m, cat, est, res, fixed_order=fixed_order); add(m, o, pre)
    for s in SEEDS:
        o, pre = order_for("random", cat, est, res, seed=s); add("random", o, pre, seed=s)
    add("neighbourhood", neighbourhood_order(cat), 0.0)
    ind = named(cat, "independent")
    add("baseline_independent", [ind] if ind else [], 0.0)   # the unshared reference only (one verification)
    return rows
