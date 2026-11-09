"""Plan-level physical cost estimate (rule frozen before any measurement at the held-out sizes).

Inputs: the candidate's SharingPlans, the PDK rule table, and ONE baseline assembly per task (the independent plan,
built once; its geometry cost is charged to the method as one geometry generation).  No candidate geometry is
generated, no measured area or verification label of any candidate is read.

Group level (same formulas as glayout.sharing.group.build_mos_group, evaluated without drawing):
  W_g = sum_islands [2*end_ext + k*L + (k-1)*inner_node] + (n_islands-1)*island_gap + top-strap end-pad overhang
  H_g = W_unit + bottom part (endcap [+poly_sep if a top strap crosses a bottom strap span] + strap + pad levels*pad_pitch)
        + top part (endcap [+poly_sep] + strap, only with top straps) + S/D pin rows
Task level:  rowspan_r(c) = rowspan_r(base) + sum_{g in r} (W_g(c) - W_g(base));  H_r(c) = H_r(base) + max_g H_g(c) - max_g H_g(base)
  W(c) = max_r rowspan_r(c) + (W_total(base) - max_r rowspan_r(base));   H(c) = H_total(base) + sum_r (H_r(c) - H_r(base))
  Channels (added after the development-size validation, before any other size was measured): every diffusion node of a
  group cell has a pin on the cell's top edge and every gate group has a pad on its strap side, so the set of nets a
  candidate brings into each routing channel follows from the plan alone.  With N_ch the nets of channel ch (other cells
  and tap strips taken from the baseline assembly), H(c) += track_pitch * sum_ch (|N_ch(c)| - |N_ch(base)|)
  (+/- 2*channel_margin when a channel appears / disappears).  Track packing changes, cross-row stub shifts and the
  split-channel alternative are not modelled.
  A_hat(c) = W(c) * H(c).   The decomposition terms (shared-node width saving, strap/pad height cost, row dominance,
  passive-row dominance) are returned with the estimate."""
from __future__ import annotations
from glayout.sharing.rules import snap, snap_up


def group_dims(R, devices, plan):
    W = snap(devices[0].unit_width); L = snap(devices[0].length); n = plan.n()
    inner_node = snap_up(max(2 * R.cont_gate_sep + R.cont_w, R.m1_sep + R.m1_bar_w() - L))
    outer_m1_half = max(R.m1_bar_w(), R.via1_m1_w()) / 2
    active_end_half = R.cont_w / 2 + R.act_enc_cont
    island_gap = snap_up(max(R.act_sep, R.m1_sep + 2 * max(0.0, outer_m1_half - active_end_half)))
    end_off = max(snap_up(R.cont_gate_sep + R.cont_w / 2), snap_up(inner_node / 2))
    end_ext = max(snap_up(end_off + R.cont_w / 2 + R.act_enc_cont), snap_up(R.act_sd_ext_min))
    isl = plan.islands()
    w_act = sum(2 * end_ext + (b - a + 1) * L + (b - a) * inner_node for a, b in isl) + (len(isl) - 1) * island_gap
    gpad = snap_up(max(R.cont_w + 2 * R.poly_enc_cont, R.poly_w_min, R.sq_from_area(R.poly_area_min),
                       R.cont_w + 2 * R.m1_enc_cont, R.m1_w, R.sq_from_area(R.m1_area_min), R.via1_m1_w()))
    d_pad = snap_up(max(R.contpoly_act_sep, R.m1_sep + 2 * R.m1_enc_cont - R.act_enc_cont, R.poly_act_sep + R.poly_enc_cont))
    pad_out = d_pad + R.cont_w / 2 + R.poly_enc_cont + (gpad - R.cont_w - 2 * R.poly_enc_cont) / 2 + gpad / 2
    side_of = {}
    for gi, g in enumerate(plan.gate_groups):
        for p in g.fingers: side_of[p] = g.side
    tops = [g for g in plan.gate_groups if g.side == "top"]; bottoms = [g for g in plan.gate_groups if g.side == "bottom"]
    over_l = max([pad_out for g in tops if g.pad_end == "left"] + [0.0]); over_r = max([pad_out for g in tops if g.pad_end == "right"] + [0.0])
    w = w_act + over_l + over_r
    def iv(g):
        lo, hi = min(g.fingers), max(g.fingers)
        if g.side == "top": lo, hi = (0, hi) if g.pad_end == "left" else (lo, n - 1)
        return lo, hi
    off_b = any(side_of[p] == "top" for g in bottoms for p in range(iv(g)[0], iv(g)[1] + 1))
    off_t = any(side_of[p] == "bottom" for g in tops for p in range(iv(g)[0], iv(g)[1] + 1))
    strap_w = snap_up(R.poly_w_min); pad_pitch = snap_up(gpad + max(R.poly_sep, R.m1_sep, R.m2_sep))
    levels = min(2, len(bottoms))
    h_bottom = R.endcap + (R.poly_sep if off_b else 0.0) + strap_w + levels * pad_pitch if bottoms else R.endcap
    h_top = (R.endcap + (R.poly_sep if off_t else 0.0) + strap_w) if tops else R.endcap
    pin = max(R.m1_sep, R.poly_act_sep, 0.1) + snap_up(R.via1_pad_w() + R.m2_sep) + R.via1_pad_w()
    h = W + h_bottom + h_top + pin
    s = plan.summary()
    return {"w": round(w, 4), "h": round(h, 4), "islands": len(isl), "cross_joins": s["cross_device_diffusion_joins"],
            "shared_gate_groups": s["cross_device_gate_groups"], "top_band": bool(tops), "pad_levels": levels,
            "top_pad_overhang": round(over_l + over_r, 4), "active_w": round(w_act, 4)}


def group_side_nets(devices, plan):
    """Nets a group cell exposes on its own top and bottom edges (cell-local, before any row flip)."""
    by_id = {d.logical_id: d for d in devices}
    top = set(); bot = set()
    for d in devices: top |= {d.s, d.d}
    for g in plan.gate_groups:
        net = by_id[plan.finger_order[g.fingers[0]].device].g
        (top if g.side == "top" else bot).add(net)
    return top, bot


def channel_nets(base_stats, groups, plans, group_names):
    """Per-channel net sets when the groups use `plans`; other cells and tap strips as in the baseline assembly."""
    src = base_stats["channel_net_sources"]; flip = src["row_flip"]; nch = len(flip) + 1
    N = [set() for _ in range(nch)]
    for ch, nets in src["taps"].items(): N[int(ch)] |= set(nets)
    gset = set(group_names)
    for cname, d in src["cells"].items():
        if cname in gset: continue
        for ch, nets in d.items(): N[int(ch)] |= set(nets)
    for g, p, cname in zip(groups, plans, group_names):
        ri = src["row_of_cell"][cname]; top, bot = group_side_nets(g, p)
        up, down = (bot, top) if flip[ri] else (top, bot)
        N[ri + 1] |= up; N[ri] |= down
    return N


CHANNEL_RULE = "nets"   # chosen on the development sizes ("nets" or "density") and frozen before the held-out sizes


def estimate(R, groups, plans, base_dims, base_stats, group_row, base_plans=None, group_names=None, channel_rule=None):
    """groups: list of device lists; plans: list of SharingPlan (candidate); base_dims: list of group_dims of the
    baseline plans; base_stats: textbook_sharing.assembly stats of the baseline assembly (row_dims, width, height); group_row: list of the
    row index (in base_stats['row_dims']) holding each group."""
    dims = [group_dims(R, g, p) for g, p in zip(groups, plans)]
    rows = base_stats["row_dims"]
    span0 = [r["width"] + 2 * r["tap_extent"] for r in rows]
    span = list(span0); hrow = [r["height"] for r in rows]
    for gi, (d, d0) in enumerate(zip(dims, base_dims)):
        span[group_row[gi]] += d["w"] - d0["w"]
    for ri in range(len(rows)):
        gs = [gi for gi in range(len(groups)) if group_row[gi] == ri]
        if gs:
            hrow[ri] = rows[ri]["height"] + max(dims[gi]["h"] for gi in gs) - max(base_dims[gi]["h"] for gi in gs)
    Wt = max(span) + (base_stats["width"] - max(span0))
    Ht = base_stats["height"] + sum(hrow[ri] - rows[ri]["height"] for ri in range(len(rows)))
    dch = None
    if base_plans is not None and "channel_net_sources" in base_stats and (channel_rule or CHANNEL_RULE) != "none":
        names = group_names or [f"grp{gi}" for gi in range(len(groups))]
        Nb = channel_nets(base_stats, groups, base_plans, names); Nc = channel_nets(base_stats, groups, plans, names)
        pitch = base_stats["track_pitch"]; marg = base_stats["channel_margin"]; dch = []
        rule = channel_rule or CHANNEL_RULE
        for ch, (b, c) in enumerate(zip(Nb, Nc)):
            if rule == "density" and b:
                hb = base_stats["channel_heights"][ch]
                tb = round((hb - 2 * marg) / pitch) if hb > 0 else 0
                dt = round((len(c) - len(b)) * tb / len(b))
            else:
                dt = len(c) - len(b)
            dh = dt * pitch
            if b and not c: dh -= 2 * marg
            if c and not b: dh += 2 * marg
            dch.append(round(dh, 4))
        Ht += sum(dch)
    widest = max(range(len(rows)), key=lambda ri: span[ri])
    return {"area_hat": round(Wt * Ht, 4), "w_hat": round(Wt, 4), "h_hat": round(Ht, 4), "groups": dims,
            "row_spans": [round(x, 4) for x in span], "widest_row_kind": rows[widest]["kind"],
            "passive_dominated": rows[widest]["kind"] == "passive", "channel_dh": dch}
