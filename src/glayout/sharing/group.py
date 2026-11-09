"""build_mos_group: connection-aware joint construction of several logical MOS devices.

Geometry is generated column by column from the plan (not by boolean-merging
finished devices): unit fingers are placed in the requested order, a diffusion
node between two fingers is drawn once and shared only when the plan joins the
fingers and the facing terminals carry the same net, and gate fingers of one
gate group are tied by a single poly strap outside the channel with its own
contact pad.  All pins are exported as met2 pads on the top edge (source/drain
and top-strap gates) or on the bottom edge (bottom-strap gates), so that a
row-based channel router can connect them without knowing the internals.

Coordinate convention (local): the channel active spans y in [0, W]; fingers
are ordered left to right along x.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional
from .spec import DeviceSpec, SharingPlan, FingerRef, GateGroup, EligibilityReport, SharingPlanRejected, GroupResult
from .rules import rules_for, snap, snap_up, GRID


@dataclass
class _Node:
    index: int
    island: int
    x: float                    # contact column centre
    net: str
    terminals: list             # [(device, 'S'|'D')]
    is_end: bool
    pin_row: int = 0            # 0 or 1 (staggered)
    pin_name: str = ""


@dataclass
class _Gate:
    pos: int
    device: str
    k: int
    net: str
    x: float                    # gate centre
    group: int
    island: int


@dataclass
class _Rects:
    rects: dict = field(default_factory=dict)   # layer tuple -> list of (x0,y0,x1,y1)

    def add(self, layer, x0, y0, x1, y1):
        if layer is None:
            return
        if x1 < x0: x0, x1 = x1, x0
        if y1 < y0: y0, y1 = y1, y0
        self.rects.setdefault(tuple(layer), []).append((snap(x0), snap(y0), snap(x1), snap(y1)))


def validate_plan(rules, devices: list[DeviceSpec], plan: SharingPlan) -> EligibilityReport:
    rep = EligibilityReport(ok=True)
    if not devices:
        rep.add_error("no_devices", "group needs at least one device"); return rep
    ids = [d.logical_id for d in devices]
    if len(set(ids)) != len(ids):
        rep.add_error("duplicate_ids", "logical ids must be unique")
    roles = {d.model_role for d in devices}
    if len(roles) > 1:
        rep.add_error("mixed_polarity", f"cannot share across polarities {sorted(roles)}")
    if any(d.m != 1 for d in devices):
        rep.add_error("multiplier_unsupported", "SPICE m>1 must be expanded into fingers before building a group")
    Ls = {round(d.length, 4) for d in devices}
    if len(Ls) > 1:
        rep.add_error("length_mismatch", f"all devices of a group must share L, got {sorted(Ls)}")
    uws = {round(d.unit_width, 4) for d in devices}
    if len(uws) > 1:
        rep.add_error("unit_width_mismatch", f"all devices of a group must share the unit finger width, got {sorted(uws)}")
    bodies = {d.b for d in devices}
    if len(bodies) > 1:
        rep.add_error("body_mismatch", f"devices of one group must share the body net, got {sorted(bodies)}")
    uw = devices[0].unit_width
    if uw + 1e-9 < rules.min_contactable_width:
        rep.add_error("unit_width_below_contactable", f"unit width {uw:.3f} < contactable minimum {rules.min_contactable_width:.3f} (dogbone not supported)")
    if devices[0].length + 1e-9 < rules.L_min:
        rep.add_error("length_below_min", f"L={devices[0].length} < min {rules.L_min}")
    if rep.errors:
        return rep
    # finger coverage
    expected = {(d.logical_id, k) for d in devices for k in range(d.nf)}
    got = [(f.device, f.index) for f in plan.finger_order]
    if len(got) != len(set(got)) or set(got) != expected:
        rep.add_error("finger_coverage", "finger_order must list every unit finger of every device exactly once",
                      {"missing": sorted(expected - set(got)), "extra": sorted(set(got) - expected)})
        return rep
    n = len(got)
    if len(plan.orientations) != n or any(o not in ("SD", "DS") for o in plan.orientations):
        rep.add_error("orientations", "orientations must be a list of 'SD'/'DS' with one entry per finger"); return rep
    if len(plan.diffusion_joins) != n - 1:
        rep.add_error("joins_length", "diffusion_joins must have n-1 entries"); return rep
    dev = {d.logical_id: d for d in devices}
    def lr(p):
        f = plan.finger_order[p]; d = dev[f.device]
        return (d.s, d.d) if plan.orientations[p] == "SD" else (d.d, d.s)
    for i in range(n - 1):
        if plan.diffusion_joins[i]:
            rn = lr(i)[1]; ln = lr(i + 1)[1 - 1]
            if rn != ln:
                rep.add_error("join_net_mismatch", f"fingers {i} and {i+1} cannot share a diffusion node: nets {rn} vs {ln}", {"position": i})
    # gate groups
    seen = {}
    for gi, g in enumerate(plan.gate_groups):
        for p in g.fingers:
            if p < 0 or p >= n:
                rep.add_error("gate_group_index", f"gate group {gi} references position {p}")
            elif p in seen:
                rep.add_error("gate_group_partition", f"position {p} is in gate groups {seen[p]} and {gi}")
            seen[p] = gi
        nets = {dev[plan.finger_order[p].device].g for p in g.fingers if 0 <= p < n}
        if len(nets) > 1:
            rep.add_error("gate_group_net_mismatch", f"gate group {gi} ties different gate nets {sorted(nets)}", {"group": gi})
        if g.side not in ("bottom", "top") or g.pad_end not in ("left", "right"):
            rep.add_error("gate_group_fields", f"gate group {gi} has invalid side/pad_end")
    if len(seen) != n:
        rep.add_error("gate_group_partition", "every finger must belong to exactly one gate group")
    if rep.errors:
        return rep
    # strap routability: bottom straps span their own interval; top straps reach from their fingers to the pad end
    bottom = [(min(g.fingers), max(g.fingers), gi) for gi, g in enumerate(plan.gate_groups) if g.side == "bottom"]
    top = []
    for gi, g in enumerate(plan.gate_groups):
        if g.side == "top":
            lo, hi = min(g.fingers), max(g.fingers)
            if plan.gate_contact_policy == "both_ends":
                lo, hi = 0, n - 1
            elif g.pad_end == "left":
                lo = 0
            else:
                hi = n - 1
            top.append((lo, hi, gi))
    for a in range(len(bottom)):
        for b in range(a + 1, len(bottom)):
            la, ha, ga = bottom[a]; lb, hb, gb = bottom[b]
            if la <= hb and lb <= ha:
                rep.add_error("gate_strap_interleave_unroutable", f"bottom straps of gate groups {ga} and {gb} overlap; move one to side 'top'", {"groups": [ga, gb]})
    for a in range(len(top)):
        for b in range(a + 1, len(top)):
            la, ha, ga = top[a]; lb, hb, gb = top[b]
            if la <= hb and lb <= ha:
                rep.add_error("gate_strap_interleave_unroutable", f"top straps of gate groups {ga} and {gb} overlap in reach", {"groups": [ga, gb]})
    rep.checks = {"fingers": n, "islands": len(plan.islands()), "bottom_groups": len(bottom), "top_groups": len(top)}
    return rep


def independent_plan(devices: list[DeviceSpec]) -> SharingPlan:
    """Canonical plan with no cross-device sharing: devices consecutive, own strap each."""
    order, orient, joins, groups = [], [], [], []
    pos = 0
    for di, d in enumerate(devices):
        start = pos
        for k in range(d.nf):
            order.append(FingerRef(d.logical_id, k)); orient.append("SD" if k % 2 == 0 else "DS")
            if k > 0: joins.append(True)
            pos += 1
        if di < len(devices) - 1: joins.append(False)
        groups.append(GateGroup(tuple(range(start, pos)), "bottom", "left"))
    return SharingPlan(order, orient, joins, groups, mode_label="independent")


def build_mos_group(pdk, devices: list[DeviceSpec], connectivity=None, plan: Optional[SharingPlan] = None,
                    constraints: Optional[dict] = None, name: str = "mos_group") -> GroupResult:
    from glayout.backend import Component
    rules = rules_for(pdk)
    constraints = constraints or {}
    if plan is None:
        plan = independent_plan(devices)
    rep = validate_plan(rules, devices, plan)
    if not rep.ok:
        raise SharingPlanRejected(rep)
    dev = {d.logical_id: d for d in devices}
    n = plan.n(); W = snap(devices[0].unit_width); L = snap(devices[0].length)
    pol = devices[0].model_role
    R = rules

    # ---------------- x layout ----------------
    islands = plan.islands()
    nodes: list[_Node] = []; gates: list[_Gate] = []
    gate_group_of = {}
    for gi, g in enumerate(plan.gate_groups):
        for p in g.fingers: gate_group_of[p] = gi
    x = 0.0
    island_x = []  # (x0, x1) active extents
    def lr(p):
        f = plan.finger_order[p]; d = dev[f.device]
        return (("S", d.s), ("D", d.d)) if plan.orientations[p] == "SD" else (("D", d.d), ("S", d.s))
    # inner node width: contact rules, and metal-1 bar spacing between adjacent nodes (bars are cont_w + 2*m1 enclosure wide)
    inner_node = snap_up(max(2 * R.cont_gate_sep + R.cont_w, R.m1_sep + R.m1_bar_w() - L))
    # gap between islands: active spacing, and metal-1 spacing between the end bars / pin pads that stick out past the active end
    outer_m1_half = max(R.m1_bar_w(), R.via1_m1_w()) / 2
    active_end_half = R.cont_w / 2 + R.act_enc_cont
    island_gap = snap_up(max(R.act_sep, R.m1_sep + 2 * max(0.0, outer_m1_half - active_end_half)))
    # end node: same gate-to-contact offset as inner nodes so that end bars keep metal spacing to the first inner bar
    end_off = max(snap_up(R.cont_gate_sep + R.cont_w / 2), snap_up(inner_node / 2))
    end_ext = snap_up(end_off + R.cont_w / 2 + R.act_enc_cont)          # active beyond last gate at an island end
    end_ext = max(end_ext, snap_up(R.act_sd_ext_min))
    for isl, (a, b) in enumerate(islands):
        x0 = x
        # left end node
        cx = snap(x0 + end_ext - end_off)
        t, net = lr(a)[0]
        nodes.append(_Node(len(nodes), isl, cx, net, [(plan.finger_order[a].device, t)], True))
        xg = snap(x0 + end_ext)
        for p in range(a, b + 1):
            f = plan.finger_order[p]
            gates.append(_Gate(p, f.device, f.index, dev[f.device].g, xg + L / 2, gate_group_of[p], isl))
            right_t, right_net = lr(p)[1]
            if p < b:
                cx = snap(xg + L + inner_node / 2)
                nxt_t, nxt_net = lr(p + 1)[0]
                assert nxt_net == right_net
                nodes.append(_Node(len(nodes), isl, cx, right_net, [(f.device, right_t), (plan.finger_order[p + 1].device, nxt_t)], False))
                xg = snap(xg + L + inner_node)
            else:
                cx = snap(xg + L + end_off)
                nodes.append(_Node(len(nodes), isl, cx, right_net, [(f.device, right_t)], True))
                x1 = snap(xg + L + end_ext)
        island_x.append((x0, x1))
        x = snap(x1 + island_gap)
    x_act_min, x_act_max = island_x[0][0], island_x[-1][1]

    # ---------------- vertical structure ----------------
    strap_w = snap_up(R.poly_w_min)
    bottom_groups = [gi for gi, g in enumerate(plan.gate_groups) if g.side == "bottom"]
    top_groups = [gi for gi, g in enumerate(plan.gate_groups) if g.side == "top"]
    pos_side = {p: plan.gate_groups[gate_group_of[p]].side for p in range(n)}
    def interval(gi):
        g = plan.gate_groups[gi]; lo, hi = min(g.fingers), max(g.fingers)
        if g.side == "top":
            if plan.gate_contact_policy == "both_ends": lo, hi = 0, n - 1
            elif g.pad_end == "left": lo = 0
            else: hi = n - 1
        return lo, hi
    need_off_bottom = False
    for gi in bottom_groups:
        lo, hi = interval(gi)
        if any(pos_side[p] == "top" for p in range(lo, hi + 1)): need_off_bottom = True
    need_off_top = False
    for gi in top_groups:
        lo, hi = interval(gi)
        if any(pos_side[p] == "bottom" for p in range(lo, hi + 1)): need_off_top = True
    y_sb_top = snap(-R.endcap - (R.poly_sep if need_off_bottom else 0.0))      # bottom strap band top edge
    y_sb_bot = snap(y_sb_top - strap_w)
    y_st_bot = snap(W + R.endcap + (R.poly_sep if need_off_top else 0.0))
    y_st_top = snap(y_st_bot + strap_w)
    # gate pad sizes
    gpad_poly = snap_up(max(R.cont_w + 2 * R.poly_enc_cont, R.poly_w_min, R.sq_from_area(R.poly_area_min)))
    gpad_m1 = snap_up(max(R.cont_w + 2 * R.m1_enc_cont, R.m1_w, R.sq_from_area(R.m1_area_min), R.via1_m1_w()))
    gpad_m2 = R.via1_pad_w()
    gpad = snap_up(max(gpad_poly, gpad_m1))
    # bottom gate pad levels: level0 directly below strap band, level1 further down
    pad_pitch_y = snap_up(gpad + max(R.poly_sep, R.m1_sep, R.m2_sep))
    y_pad0_top = y_sb_bot
    def pad_y(level):
        top = snap(y_pad0_top - level * pad_pitch_y)
        return top - gpad, top
    # S/D pin rows above the top band (or above endcap if no top band)
    m1_bar_w = R.m1_bar_w()
    pin_pad = R.via1_pad_w()
    pin_m1 = R.via1_m1_w()
    y_top_geom = y_st_top if top_groups else snap(W + R.endcap)
    pin_row_pitch = snap_up(pin_pad + R.m2_sep)
    y_pinA = snap(y_top_geom + max(R.m1_sep, R.poly_act_sep, 0.1))
    y_pinB = snap(y_pinA + pin_row_pitch)
    pin_rows = (y_pinA, y_pinB)

    rects = _Rects(); lay = R.layers
    comp = Component(name)
    ports = {}; pin_nets = {}; pin_meta = {}

    # ---------------- active / implant / well ----------------
    for (x0, x1) in island_x:
        rects.add(lay["active"], x0, 0, x1, W)
    if pol == "nfet":
        enc = R.nimp_enc_act
        if R.nimp_layer is not None:
            rects.add(R.nimp_layer, x_act_min - enc, -enc, x_act_max + enc, W + enc)
    else:
        enc = max(R.pimp_enc_act, R.pimp_enc_gate)
        rects.add(R.pimp_layer, x_act_min - enc, -enc, x_act_max + enc, W + enc)
        nwe = R.nwell_enc_pact
        rects.add(R.nwell_layer, x_act_min - nwe, -nwe, x_act_max + nwe, W + nwe)

    # ---------------- contacts and S/D bars ----------------
    ncont = max(1, int(math.floor((W - 2 * R.act_enc_cont - R.cont_w) / (R.cont_w + R.cont_sep) + 1e-9)) + 1)
    while ncont > 1 and (ncont * R.cont_w + (ncont - 1) * R.cont_sep) > W - 2 * R.act_enc_cont + 1e-9:
        ncont -= 1
    hcol = ncont * R.cont_w + (ncont - 1) * R.cont_sep
    yc0 = snap((W - hcol) / 2)
    if yc0 < R.act_enc_cont - 1e-9:
        yc0 = snap_up(R.act_enc_cont)
    for i, nd in enumerate(nodes):
        nd.pin_row = i % 2
        half = R.cont_w / 2
        for c in range(ncont):
            y0 = snap(yc0 + c * (R.cont_w + R.cont_sep))
            rects.add(lay["cont"], nd.x - half, y0, nd.x + half, y0 + R.cont_w)
        bar_y0 = snap(yc0 - R.m1_enc_cont)
        ypin = pin_rows[nd.pin_row]
        rects.add(lay["met1"], nd.x - m1_bar_w / 2, bar_y0, nd.x + m1_bar_w / 2, ypin + pin_m1 / 2)
        # via1 + met2 pad (pin)
        rects.add(lay["met1"], nd.x - pin_m1 / 2, ypin - pin_m1 / 2, nd.x + pin_m1 / 2, ypin + pin_m1 / 2)
        rects.add(lay["via1"], nd.x - R.via1_w / 2, ypin - R.via1_w / 2, nd.x + R.via1_w / 2, ypin + R.via1_w / 2)
        rects.add(lay["met2"], nd.x - pin_pad / 2, ypin - pin_pad / 2, nd.x + pin_pad / 2, ypin + pin_pad / 2)
        pname = f"sd{i}"
        nd.pin_name = pname
        comp.add_port(name=pname, center=(nd.x, snap(ypin + pin_pad / 2)), width=pin_pad, orientation=90, layer=lay["met2"])
        pin_nets[pname] = nd.net
        pin_meta[pname] = {"side": "top", "x": nd.x, "y": snap(ypin + pin_pad / 2), "width": pin_pad, "net": nd.net,
                           "terminals": [f"{d}:{t}" for d, t in nd.terminals], "node": i, "island": nd.island}
        for d, t in nd.terminals:
            ports.setdefault(f"{d}:{t}", []).append(pname)

    # ---------------- gates, straps, gate pads ----------------
    gate_pin_count = 0
    bottom_level = {}
    for li, gi in enumerate(sorted(bottom_groups, key=lambda gi: min(plan.gate_groups[gi].fingers))):
        bottom_level[gi] = li % 2
    gpad_records = []
    for gi, g in enumerate(plan.gate_groups):
        gxs = [gates[p].x for p in g.fingers]
        lo, hi = min(g.fingers), max(g.fingers)
        net = dev[plan.finger_order[lo].device].g
        if g.side == "bottom":
            yb0, yb1 = y_sb_bot, y_sb_top
            # strap over the finger interval
            rects.add(lay["poly"], min(gxs) - L / 2, yb0, max(gxs) + L / 2, yb1)
            # pads: at the strap's first gate (and last gate if both_ends)
            level = bottom_level[gi]
            pad_xs = [gates[lo].x] if plan.gate_contact_policy == "single_end" else sorted({gates[lo].x, gates[hi].x})
            if plan.gate_contact_policy == "single_end" and g.pad_end == "right":
                pad_xs = [gates[hi].x]
            for pxe in pad_xs:
                px = snap(pxe)          # pad/contact geometry on the 5 nm grid; the stub follows the exact gate edges
                py0, py1 = pad_y(level)
                rects.add(lay["poly"], pxe - L / 2, py1 - GRID, pxe + L / 2, yb0 + GRID)   # poly stub from strap to pad
                rects.add(lay["poly"], px - gpad / 2, py0, px + gpad / 2, py1)
                cy = snap((py0 + py1) / 2)
                rects.add(lay["cont"], px - R.cont_w / 2, cy - R.cont_w / 2, px + R.cont_w / 2, cy + R.cont_w / 2)
                if R.pdk_name == "sky130":   # nitride poly cut around every poly contact (npc.1 width 0.27, enclosure 0.10)
                    npc_h = max(0.27, R.cont_w + 0.2) / 2
                    rects.add((95, 20), px - npc_h, cy - npc_h, px + npc_h, cy + npc_h)
                rects.add(lay["met1"], px - gpad_m1 / 2, cy - gpad_m1 / 2, px + gpad_m1 / 2, cy + gpad_m1 / 2)
                rects.add(lay["via1"], px - R.via1_w / 2, cy - R.via1_w / 2, px + R.via1_w / 2, cy + R.via1_w / 2)
                rects.add(lay["met2"], px - gpad_m2 / 2, cy - gpad_m2 / 2, px + gpad_m2 / 2, cy + gpad_m2 / 2)
                pname = f"g{gate_pin_count}"; gate_pin_count += 1
                comp.add_port(name=pname, center=(px, snap(cy - gpad_m2 / 2)), width=gpad_m2, orientation=270, layer=lay["met2"])
                pin_nets[pname] = net
                pin_meta[pname] = {"side": "bottom", "x": px, "y": snap(cy - gpad_m2 / 2), "width": gpad_m2, "net": net,
                                   "terminals": sorted({f"{plan.finger_order[p].device}:G" for p in g.fingers}), "gate_group": gi}
                for d in sorted({plan.finger_order[p].device for p in g.fingers}):
                    ports.setdefault(f"{d}:G", []).append(pname)
                gpad_records.append({"group": gi, "x": px, "y": cy, "side": "bottom"})
        else:
            yb0, yb1 = y_st_bot, y_st_top
            d_pad = snap_up(max(R.contpoly_act_sep, R.m1_sep + 2 * R.m1_enc_cont - R.act_enc_cont, R.poly_act_sep + R.poly_enc_cont))
            ends = []
            if plan.gate_contact_policy == "both_ends":
                ends = ["left", "right"]
            else:
                ends = [g.pad_end]
            xs_reach = [min(gxs) - L / 2, max(gxs) + L / 2]
            for e in ends:
                if e == "left":
                    px = snap(x_act_min - d_pad - R.cont_w / 2 - R.poly_enc_cont - (gpad - R.cont_w - 2 * R.poly_enc_cont) / 2)
                    xs_reach[0] = min(xs_reach[0], px - gpad / 2)
                else:
                    px = snap(x_act_max + d_pad + R.cont_w / 2 + R.poly_enc_cont + (gpad - R.cont_w - 2 * R.poly_enc_cont) / 2)
                    xs_reach[1] = max(xs_reach[1], px + gpad / 2)
                cy = snap((yb0 + yb1) / 2)
                pad_bot = snap(cy - gpad / 2); pad_top = snap(cy + gpad / 2)
                rects.add(lay["poly"], px - gpad / 2, pad_bot, px + gpad / 2, pad_top)
                rects.add(lay["cont"], px - R.cont_w / 2, cy - R.cont_w / 2, px + R.cont_w / 2, cy + R.cont_w / 2)
                if R.pdk_name == "sky130":
                    npc_h = max(0.27, R.cont_w + 0.2) / 2
                    rects.add((95, 20), px - npc_h, cy - npc_h, px + npc_h, cy + npc_h)
                # met1 pad and riser to the pin row (use the row opposite to the nearest end node)
                near_node = nodes[0] if e == "left" else nodes[-1]
                row = 1 - near_node.pin_row
                ypin = pin_rows[row]
                rects.add(lay["met1"], px - gpad_m1 / 2, cy - gpad_m1 / 2, px + gpad_m1 / 2, cy + gpad_m1 / 2)
                rects.add(lay["met1"], px - m1_bar_w / 2, cy, px + m1_bar_w / 2, ypin + pin_m1 / 2)
                rects.add(lay["met1"], px - pin_m1 / 2, ypin - pin_m1 / 2, px + pin_m1 / 2, ypin + pin_m1 / 2)
                rects.add(lay["via1"], px - R.via1_w / 2, ypin - R.via1_w / 2, px + R.via1_w / 2, ypin + R.via1_w / 2)
                rects.add(lay["met2"], px - pin_pad / 2, ypin - pin_pad / 2, px + pin_pad / 2, ypin + pin_pad / 2)
                pname = f"g{gate_pin_count}"; gate_pin_count += 1
                comp.add_port(name=pname, center=(px, snap(ypin + pin_pad / 2)), width=pin_pad, orientation=90, layer=lay["met2"])
                pin_nets[pname] = net
                pin_meta[pname] = {"side": "top", "x": px, "y": snap(ypin + pin_pad / 2), "width": pin_pad, "net": net,
                                   "terminals": sorted({f"{plan.finger_order[p].device}:G" for p in g.fingers}), "gate_group": gi}
                for d in sorted({plan.finger_order[p].device for p in g.fingers}):
                    ports.setdefault(f"{d}:G", []).append(pname)
                gpad_records.append({"group": gi, "x": px, "y": cy, "side": "top"})
            rects.add(lay["poly"], xs_reach[0], yb0, xs_reach[1], yb1)
    # gate fingers
    for gt in gates:
        side = plan.gate_groups[gt.group].side
        y0 = y_sb_top - GRID if side == "bottom" else snap(-R.endcap)
        y1 = y_st_bot + GRID if side == "top" else snap(W + R.endcap)
        rects.add(lay["poly"], gt.x - L / 2, y0, gt.x + L / 2, y1)

    # ---------------- emit ----------------
    for layer, rl in rects.rects.items():
        for (x0, y0, x1, y1) in rl:
            comp.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=layer)
    bbox = _bbox(rects)
    device_map = {}
    for d in devices:
        device_map[d.logical_id] = {
            "fingers": [{"position": gt.pos, "k": gt.k, "x": gt.x, "island": gt.island, "gate_group": gt.group} for gt in gates if gt.device == d.logical_id],
            "terminals": {t: ports.get(f"{d.logical_id}:{t}", []) for t in ("D", "G", "S")},
            "nets": d.nets(), "width_total": d.width_total, "unit_width": W, "length": L, "nf": d.nf,
        }
    node_records = [{"node": nd.index, "island": nd.island, "x": nd.x, "net": nd.net, "terminals": [f"{a}:{b}" for a, b in nd.terminals], "is_end": nd.is_end, "pin": nd.pin_name} for nd in nodes]
    from .evidence import evidence_from_rects
    evidence = evidence_from_rects(rules, rects.rects, node_records, [{"pos": g.pos, "device": g.device, "x": g.x, "net": g.net, "group": g.group} for g in gates], W, len(devices), plan)
    stats = {"bbox": bbox, "width": snap(bbox[2] - bbox[0]), "height": snap(bbox[3] - bbox[1]), "n_fingers": n, "n_islands": len(islands),
             "n_sd_nodes": len(nodes), "n_sd_contacts": len(nodes) * ncont, "contacts_per_node": ncont, "n_gate_pads": gate_pin_count,
             "unit_width": W, "length": L, "pin_rows": pin_rows, "active_bbox": (x_act_min, 0.0, x_act_max, W), "bands": {"bottom": [y_sb_bot, y_sb_top], "top": [y_st_bot, y_st_top] if top_groups else None}}
    comp.info["pin_meta"] = pin_meta
    comp.info["pin_nets"] = pin_nets
    comp.info["group_stats"] = stats
    return GroupResult(component=comp, ports=ports, pin_nets=pin_nets, device_map=device_map, applied_plan=plan.to_json(),
                       eligibility_report=rep.to_json(), physical_sharing_evidence=evidence, geometry_stats=stats)


def _bbox(rects: _Rects):
    xs0 = []; ys0 = []; xs1 = []; ys1 = []
    for rl in rects.rects.values():
        for (x0, y0, x1, y1) in rl:
            xs0.append(x0); ys0.append(y0); xs1.append(x1); ys1.append(y1)
    return (min(xs0), min(ys0), max(xs1), max(ys1))
