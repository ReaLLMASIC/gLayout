"""Candidate enumeration: six discrete axes per device group.

Axis                 values                                         meaning
arrangement          block | interleave | abba | mirror             finger order family (abba: exactly 2 devices with
                                                                    even nf; mirror: every device has even nf;
                                                                    otherwise the tuple is rejected)
orientation          alt_SD | alt_DS | seek_SD | seek_DS            alt_*: orientations alternate along the row starting
                                                                    with source-left (SD) or drain-left (DS);
                                                                    seek_*: start SD/DS, then every finger takes the
                                                                    orientation whose left terminal carries the net of the
                                                                    previous finger's right terminal (else it alternates)
diffusion            none | all_legal                               none: only joins between adjacent fingers of the SAME
                                                                    device (standard multi-finger device); all_legal:
                                                                    every adjacent boundary whose facing nets are equal
gate                 per_device | per_net                           one poly strap per device | one per gate net
strap_start          bottom | top                                   side of the first strap group (by first finger);
                                                                    later groups take that side unless their interval
                                                                    overlaps a group already there, then the other side;
                                                                    overlap on both sides -> rejected (unroutable)
contact_end          left | right                                   pad end of every strap (two top straps: the left one
                                                                    must reach left, the right one right; a contradicting
                                                                    value is rejected)

Raw tuples per group: 4 x 4 x 2 x 2 x 2 x 2 = 256.  Orientation uses the 'seek' policies rather than a uniform
source-left or source-right orientation: a uniform orientation puts S|D of the same device face to face at every finger
boundary, so no node could be shared even inside one device, and every such candidate is dominated by its alternating
counterpart, while the seek policies make cross-device sharing reachable for block and interleaved orders.
Each tuple -> SharingPlan -> static legality (validate_plan + strap routability) -> canonical plan id (geometry-relevant
fields) -> duplicates removed.  No geometry is generated and no measurement is used here.  Plans written directly as a
SharingPlan can express more than these axes (any finger order or strap partition); the enumeration is a family, not
the whole plan space."""
from __future__ import annotations
import itertools
from .spec import DeviceSpec, SharingPlan, FingerRef, GateGroup
from .group import validate_plan, independent_plan
from .rules import rules_for

ARRANGEMENTS = ("block", "interleave", "abba", "mirror")
ORIENTATIONS = ("alt_SD", "alt_DS", "seek_SD", "seek_DS")
DIFFUSION = ("none", "all_legal")
GATE = ("per_device", "per_net")
STRAP_START = ("bottom", "top")
CONTACT_END = ("left", "right")
AXES = {"arrangement": ARRANGEMENTS, "orientation": ORIENTATIONS, "diffusion": DIFFUSION, "gate": GATE,
        "strap_start": STRAP_START, "contact_end": CONTACT_END}
RAW_PER_GROUP = 4 * 4 * 2 * 2 * 2 * 2


def _order(devices, arrangement):
    ids = [d.logical_id for d in devices]; nf = {d.logical_id: d.nf for d in devices}
    fingers = {i: [FingerRef(i, k) for k in range(nf[i])] for i in ids}
    if arrangement == "block":
        return [f for i in ids for f in fingers[i]], None
    if arrangement == "interleave":
        if len(ids) < 2: return [f for i in ids for f in fingers[i]], None
        out = []; q = {i: list(fingers[i]) for i in ids}
        while any(q.values()):
            for i in ids:
                if q[i]: out.append(q[i].pop(0))
        return out, None
    if arrangement == "abba":
        if len(ids) != 2 or any(nf[i] % 2 for i in ids):
            return None, "abba needs exactly two devices with even finger counts"
        a, b = ids; fa, fb = list(fingers[a]), list(fingers[b]); out = []
        while fa or fb:
            if fa: out.append(fa.pop(0))
            if fb: out.append(fb.pop(0))
            if fb: out.append(fb.pop(0))
            if fa: out.append(fa.pop(0))
        return out, None
    if arrangement == "mirror":
        if any(nf[i] % 2 for i in ids):
            return None, "mirror needs even finger counts for every device"
        halves = [fingers[i][: nf[i] // 2] for i in ids]; rest = [fingers[i][nf[i] // 2:] for i in ids]
        return [f for h in halves for f in h] + [f for h in reversed(rest) for f in h], None
    raise ValueError(arrangement)


def _orientations(order, dev, policy):
    out = []
    start = "SD" if policy.endswith("SD") else "DS"
    for i, f in enumerate(order):
        if i == 0:
            out.append(start); continue
        if policy.startswith("alt"):
            out.append("DS" if out[-1] == "SD" else "SD"); continue
        pd = dev[order[i - 1].device]; d = dev[f.device]
        prev_right = pd.d if out[-1] == "SD" else pd.s
        if d.s == prev_right: out.append("SD")
        elif d.d == prev_right: out.append("DS")
        else: out.append("DS" if out[-1] == "SD" else "SD")
    return out


def _joins(order, orient, dev, diffusion):
    j = []
    for i in range(len(order) - 1):
        a, b = order[i], order[i + 1]; da, db = dev[a.device], dev[b.device]
        ar = da.d if orient[i] == "SD" else da.s
        bl = db.s if orient[i + 1] == "SD" else db.d
        same = a.device == b.device
        j.append(bool(ar == bl and (same or diffusion == "all_legal")))
    return j


def _gate_groups(order, dev, gate, strap_start, contact_end):
    n = len(order)
    key = (lambda p: order[p].device) if gate == "per_device" else (lambda p: dev[order[p].device].g)
    groups = {}
    for p in range(n): groups.setdefault(key(p), []).append(p)
    glist = sorted((tuple(v) for v in groups.values()), key=lambda g: g[0])
    other = "top" if strap_start == "bottom" else "bottom"
    def reach(g, side, end):
        lo, hi = min(g), max(g)
        if side == "top": return (0, hi) if end == "left" else (lo, n - 1)
        return (lo, hi)
    assigned = []   # (group, side)
    for g in glist:
        lo, hi = min(g), max(g)
        def clash(side):
            for h, s in assigned:
                if s != side: continue
                if lo <= max(h) and min(h) <= hi: return True
            return False
        if not clash(strap_start): assigned.append((g, strap_start))
        elif not clash(other): assigned.append((g, other))
        else: return None, "gate straps overlap on both sides (unroutable)"
    tops = [g for g, s in assigned if s == "top"]
    ends = {}
    if len(tops) > 2:
        return None, "more than two top straps"
    if len(tops) == 2:
        a, b = sorted(tops, key=lambda g: min(g))
        ends[a] = "left"; ends[b] = "right"
        if contact_end == "right":
            return None, "two top straps need left/right pad ends; contact_end=right contradicts the left strap"
    out = []
    for g, s in assigned:
        out.append(GateGroup(tuple(g), s, ends.get(g, contact_end)))
    return out, None


def group_candidates(pdk, devices: list[DeviceSpec]):
    """Enumerate all raw tuples of one group. Returns {'rows': [...], 'unique': {plan_id: (tuple, plan)}, 'counts': {...}}."""
    rules = rules_for(pdk); dev = {d.logical_id: d for d in devices}
    rows = []; unique = {}
    for t in itertools.product(*AXES.values()):
        tup = dict(zip(AXES.keys(), t))
        order, why = _order(devices, tup["arrangement"])
        if order is None:
            rows.append({"tuple": tup, "status": "static_illegal", "reason": why}); continue
        orient = _orientations(order, dev, tup["orientation"])
        joins = _joins(order, orient, dev, tup["diffusion"])
        gg, why = _gate_groups(order, dev, tup["gate"], tup["strap_start"], tup["contact_end"])
        if gg is None:
            rows.append({"tuple": tup, "status": "static_illegal", "reason": why}); continue
        plan = SharingPlan(order, orient, joins, gg, mode_label="axes:" + ",".join(f"{v}" for v in t))
        rep = validate_plan(rules, devices, plan)
        if not rep.ok:
            rows.append({"tuple": tup, "status": "static_illegal", "reason": "; ".join(e["code"] if isinstance(e, dict) else str(e) for e in rep.errors)}); continue
        pid = plan.plan_id()
        if pid in unique:
            rows.append({"tuple": tup, "status": "equivalent_duplicate", "plan_id": pid, "duplicate_of": unique[pid][0]}); continue
        unique[pid] = (tup, plan)
        rows.append({"tuple": tup, "status": "unique", "plan_id": pid, "summary": plan.summary()})
    counts = {"raw": len(rows), "static_illegal": sum(r["status"] == "static_illegal" for r in rows),
              "equivalent_duplicate": sum(r["status"] == "equivalent_duplicate" for r in rows), "unique": len(unique)}
    return {"rows": rows, "unique": unique, "counts": counts}


NAMED_FLAGS = {"diffusion_only": ("all_legal", "per_device"), "gate_only": ("none", "per_net"), "combined": ("all_legal", "per_net")}


def named_plans(pdk, devices, cand=None):
    """Named modes of one group.  independent = devices in order, alternating fingers per device, one bottom strap per
    device (what a generator that builds one transistor at a time produces).  diffusion_only / gate_only / combined = the first unique candidate,
    in the fixed axis order of AXES, whose diffusion/gate values are the mode's and that really shares (>= 1
    cross-device diffusion join for diffusion modes, >= 1 multi-device strap for gate modes; both for combined)."""
    cand = cand or group_candidates(pdk, devices)
    out = {"independent": independent_plan(devices)}
    for mode, (dflag, gflag) in NAMED_FLAGS.items():
        pick = None
        for row in cand["rows"]:
            if row["status"] != "unique": continue
            t = row["tuple"]
            if t["diffusion"] != dflag or t["gate"] != gflag: continue
            s = row["summary"]
            need_d = mode in ("diffusion_only", "combined"); need_g = mode in ("gate_only", "combined")
            if need_d and s["cross_device_diffusion_joins"] == 0: continue
            if need_g and s["cross_device_gate_groups"] == 0: continue
            pick = cand["unique"][row["plan_id"]][1]; break
        if pick is not None:
            pick.mode_label = mode + ":" + pick.mode_label
        out[mode] = pick
    return out
