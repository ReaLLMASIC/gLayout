"""Row/channel assembly engine (see package docstring)."""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional
from glayout.sharing.rules import rules_for, snap, snap_up, GRID


class AssemblyError(RuntimeError):
    pass


@dataclass
class RowSpec:
    cells: list                      # list[PinCell], left to right
    polarity: str                    # 'n', 'p', 'passive'
    flip: bool = False               # mirror vertically (pins that were 'top' face down)
    body_net: Optional[str] = None   # net for the tap strips of this row
    taps: bool = True
    gap: Optional[float] = None      # override cell gap


@dataclass
class _PlacedPin:
    net: str; x: float; y: float; width: float; row: int; channel: int; name: str; cell: str; key: str = ""

    def k(self):
        return self.key or self.net


class _Rects:
    def __init__(self):
        self.r = {}
    def add(self, layer, x0, y0, x1, y1):
        if layer is None: return
        if x1 < x0: x0, x1 = x1, x0
        if y1 < y0: y0, y1 = y1, y0
        self.r.setdefault(tuple(layer), []).append((snap(x0), snap(y0), snap(x1), snap(y1)))


def _flip_component(comp, y0, y1):
    """Return a mirrored copy (y -> y0+y1-y) of a component via a reference."""
    return comp


def assemble(pdk, rows: list, ports: list, name: str = "dut", labels: bool = True, extra_nets_order: Optional[list] = None,
             channel_margin: Optional[float] = None, port_layer: str = "met3") -> dict:
    """Channel rule (identical for every sharing mode): assemble with the 'shared' channel strategy (one trunk per
    net and channel; cross-row stub conflicts are resolved by shifting the upper row) and, when some net is fed from both
    rows of a channel, also with the 'split' strategy (such a net gets one trunk for the lower-row stubs and one for the
    upper-row stubs, joined by a met2 jumper beyond the pins, so lower and upper stubs never overlap and no row shift is
    needed).  The result with the smaller bounding-box area is returned (ties: shared); both areas are recorded."""
    trials = {}
    try:
        trials["shared"] = _assemble(pdk, rows, ports, name + "__trial_shared", labels, extra_nets_order, channel_margin, port_layer, split_shared=False)
    except AssemblyError as e:
        trials["shared_error"] = repr(e)
    if any(_cross_fed(rows)):
        try:
            trials["split"] = _assemble(pdk, rows, ports, name + "__trial_split", labels, extra_nets_order, channel_margin, port_layer, split_shared=True)
        except AssemblyError as e:
            trials["split_error"] = repr(e)
    cands = [(trials[k]["stats"]["area_um2"], 0 if k == "shared" else 1, k) for k in ("shared", "split") if k in trials]
    if not cands:
        raise AssemblyError(f"both channel strategies failed: {trials}")
    best = min(cands)[2]; out = trials[best]
    # trials are built under distinct internal cell names (no registry collision); the kept one gets the requested name
    comp = out["component"]
    if hasattr(comp, "unlock"): comp.unlock()
    comp.name = name
    if comp.name != name:
        raise AssemblyError(f"could not rename assembled cell to {name!r} (got {comp.name!r})")
    out["stats"]["channel_strategy"] = best
    out["stats"]["channel_strategy_trials"] = {k: (v["stats"]["area_um2"] if isinstance(v, dict) else v) for k, v in trials.items()}
    out["component"].info["assembly_stats"] = out["stats"]
    return out


def _cross_fed(rows):
    """yield True for every (channel, net) that receives pins from both the row below and the row above."""
    feed = {}
    for ri, row in enumerate(rows):
        for c in row.cells:
            for p in c.pins:
                side = p.side if not row.flip else ("bottom" if p.side == "top" else "top")
                ch = ri + 1 if side == "top" else ri
                feed.setdefault((ch, p.net), set()).add("lower" if ch == ri + 1 else "upper")
    for v in feed.values():
        yield v == {"lower", "upper"}


def _channel_net_sources(rows) -> dict:
    """{"cells": {cell_name: {channel: [nets]}}, "taps": {channel: [nets]}} for the row/flip structure of `rows`."""
    cells = {}; taps = {}
    for ri, row in enumerate(rows):
        for c in row.cells:
            d = cells.setdefault(c.name, {})
            for p in c.pins:
                side = p.side if not row.flip else ("bottom" if p.side == "top" else "top")
                ch = ri + 1 if side == "top" else ri
                d.setdefault(str(ch), set()).add(p.net)
        if row.taps and row.body_net:
            ch = ri + 1 if not row.flip else ri
            taps.setdefault(str(ch), set()).add(row.body_net)
    return {"cells": {k: {ch: sorted(v) for ch, v in d.items()} for k, d in cells.items()},
            "taps": {ch: sorted(v) for ch, v in taps.items()},
            "row_of_cell": {c.name: ri for ri, row in enumerate(rows) for c in row.cells},
            "row_flip": [bool(row.flip) for row in rows]}


def _assemble(pdk, rows: list, ports: list, name: str = "dut", labels: bool = True, extra_nets_order: Optional[list] = None,
              channel_margin: Optional[float] = None, port_layer: str = "met3", split_shared: bool = False) -> dict:
    """Place rows bottom-to-top, route nets through channels, add taps/blankets/labels.
    Returns {"component", "stats", "pin_map", "trunks", ...}."""
    from glayout.backend import Component
    R = rules_for(pdk); lay = R.layers
    comp = Component(name + "_hier")
    rects = _Rects()
    trunk_w = snap_up(max(R.m3_w, R.via2_w + 2 * R.m3_enc_via2, R.sq_from_area(R.m3_area_min)))
    track_pitch = snap_up(trunk_w + R.m3_sep)
    via2_m2_pad = snap_up(max(R.m2_w, R.via2_w + 2 * R.m2_enc_via2))
    stub_w = snap_up(R.m2_w)
    ch_margin = channel_margin if channel_margin is not None else snap_up(max(R.m2_sep, R.m3_sep) + via2_m2_pad / 2 + R.m2_sep)
    tap_w = snap_up(R.cont_w + 2 * R.act_enc_cont_tap)
    nrows = len(rows)

    # ---------- 1. place cells in rows (x), compute row heights ----------
    placed = []   # per row: list of (cell, x_offset, y_offset, flipped)
    row_dims = []
    for ri, row in enumerate(rows):
        gap = row.gap if row.gap is not None else snap_up(max(R.act_sep, R.poly_sep, R.m1_sep, R.m2_sep, R.imp_sep if row.polarity == "p" else 0.0) + 0.1)
        x = 0.0; items = []
        ymin = min(c.bbox[1] for c in row.cells); ymax = max(c.bbox[3] for c in row.cells)
        for ci, c in enumerate(row.cells):
            items.append((c, snap(x - c.bbox[0])))
            x = snap(x + (c.bbox[2] - c.bbox[0]) + gap)
        width = snap(x - gap)
        # MOS rows carry a horizontal tie strip on their gate side (cell-local bottom): reserve its height
        if row.taps and row.body_net and row.polarity in ("n", "p"):
            ymin = snap(ymin - snap_up(max(R.tap_act_sep, R.pimp_to_nact + R.pimp_enc_act) + tap_w + 0.1))
        placed.append(items); row_dims.append((width, ymin, ymax))

    # ---------- 2. determine channel nets ----------
    # channel c lies between row c-1 (below) and row c (above); c in 0..nrows
    chan_nets = [dict() for _ in range(nrows + 1)]   # channel -> net -> list of pins (filled after y placement)
    pin_channel = {}
    for ri, row in enumerate(rows):
        for c in row.cells:
            for p in c.pins:
                side = p.side if not row.flip else ("bottom" if p.side == "top" else "top")
                ch = ri + 1 if side == "top" else ri
                pin_channel[(ri, c.name, p.name)] = ch
                chan_nets[ch].setdefault(p.net, [])
        if row.taps and row.body_net:
            ch = ri + 1 if not row.flip else ri
            chan_nets[ch].setdefault(row.body_net, [])
    # track order: deterministic by first appearance in the port list, then alphabetic
    order_hint = {n: i for i, n in enumerate(list(ports) + list(extra_nets_order or []))}
    # which rows feed each (channel, net): lower row = ch-1, upper row = ch
    feed = {}
    for ri, row in enumerate(rows):
        for c in row.cells:
            for p in c.pins:
                side = p.side if not row.flip else ("bottom" if p.side == "top" else "top")
                ch = ri + 1 if side == "top" else ri
                feed.setdefault((ch, p.net), set()).add("lower" if ch == ri + 1 else "upper")
        if row.taps and row.body_net:
            ch = ri + 1 if not row.flip else ri
            feed.setdefault((ch, row.body_net), set()).add("lower" if ch == ri + 1 else "upper")
    # ---- split channel strategy: trunk entities keyed per (net, feeding side) for nets fed from both rows ----
    split_set = {k for k, v in feed.items() if v == {"lower", "upper"}} if split_shared else set()
    def K(ch, net, ri):
        if (ch, net) in split_set:
            return f"{net}|{'L' if ch == ri + 1 else 'U'}"
        return net
    def ORIG(k):
        return k.split("|")[0]
    if split_set:
        chan_nets = [dict() for _ in range(nrows + 1)]; feed2 = {}
        for ri, row in enumerate(rows):
            for c in row.cells:
                for p in c.pins:
                    side = p.side if not row.flip else ("bottom" if p.side == "top" else "top")
                    ch = ri + 1 if side == "top" else ri
                    k = K(ch, p.net, ri); chan_nets[ch].setdefault(k, [])
                    feed2.setdefault((ch, k), set()).add("lower" if ch == ri + 1 else "upper")
            if row.taps and row.body_net:
                ch = ri + 1 if not row.flip else ri
                k = K(ch, row.body_net, ri); chan_nets[ch].setdefault(k, [])
                feed2.setdefault((ch, k), set()).add("lower" if ch == ri + 1 else "upper")
        feed = feed2
    def band(ch, n):
        f = feed.get((ch, n), set())
        if f == {"lower"}: return 0
        if f == {"upper"}: return 2
        return 1
    # x-extent of each (channel, net) trunk, used to pack non-overlapping trunks on one track.
    # Extents depend on the final row x shifts, which depend on channel heights (track counts): iterate to a fixed point.
    def compute_net_x(shifts):
        nx = {}
        for ri, row in enumerate(rows):
            for c, xoff in placed[ri]:
                for p in c.pins:
                    side = p.side if not row.flip else ("bottom" if p.side == "top" else "top")
                    ch = ri + 1 if side == "top" else ri
                    gx = shifts[ri] + xoff + p.x
                    kk = K(ch, p.net, ri)
                    lo, hi = nx.get((ch, kk), (1e9, -1e9))
                    nx[(ch, kk)] = (min(lo, gx), max(hi, gx))
        return nx

    def pack_tracks(net_x):
        multi_hint = {}
        for (ch, n), _ in net_x.items():
            multi_hint.setdefault(ORIG(n), set()).add((ch, n))
        for ch in range(nrows + 1):
            for n in chan_nets[ch]:
                multi_hint.setdefault(ORIG(n), set()).add((ch, n))
        chan_tracks = []; chan_ntracks = []; chan_ivs = []
        for ch in range(nrows + 1):
            nets = sorted(chan_nets[ch].keys(), key=lambda n: (band(ch, n), order_hint.get(n, 10 ** 6), n))
            tracks = {}; occ = []
            for n in nets:
                lo, hi = net_x.get((ch, n), (0.0, 0.0))
                if len(multi_hint.get(ORIG(n), ())) > 1:
                    hi = 1e9   # reaches the riser on the right
                if (ch - 1 >= 0 and ORIG(n) == rows[ch - 1].body_net) or (ch < nrows and ORIG(n) == rows[ch].body_net):
                    lo, hi = -1e9, 1e9   # tap strips sit at both ends of the row
                lo -= trunk_w + R.m3_sep; hi += trunk_w + R.m3_sep
                t = None
                for ti, iv in enumerate(occ):
                    if iv["band"] != band(ch, n): continue
                    if all(hi < a or lo > b for a, b in iv["ivs"]):
                        t = ti; break
                if t is None:
                    occ.append({"band": band(ch, n), "ivs": []}); t = len(occ) - 1
                occ[t]["ivs"].append((lo, hi)); tracks[n] = t
            chan_tracks.append(tracks); chan_ntracks.append(len(occ)); chan_ivs.append(occ)
        return chan_tracks, chan_ntracks

    def tracks_valid(net_x, chan_tracks):
        """No two nets on one track may overlap in x (with spacing margin)."""
        for ch in range(nrows + 1):
            per = {}
            for n, t in chan_tracks[ch].items():
                lo, hi = net_x.get((ch, n), (0.0, 0.0))
                if (ch - 1 >= 0 and ORIG(n) == rows[ch - 1].body_net) or (ch < nrows and ORIG(n) == rows[ch].body_net): lo, hi = -1e9, 1e9
                per.setdefault(t, []).append((lo - trunk_w - R.m3_sep, hi + trunk_w + R.m3_sep, n))
            for t, ivs in per.items():
                for i in range(len(ivs)):
                    for j in range(i + 1, len(ivs)):
                        a, b = ivs[i], ivs[j]
                        if not (a[1] < b[0] or b[1] < a[0]): return False
        return True

    shifts0 = [0.0] * nrows
    net_x = compute_net_x(shifts0)
    chan_tracks, chan_ntracks = pack_tracks(net_x)
    chan_height = [ (chan_ntracks[ch] * track_pitch + 2 * ch_margin) if chan_tracks[ch] else 0.0 for ch in range(nrows + 1)]
    for _pass in range(4):
        # ---------- 3. vertical placement of rows and channels ----------
        y = 0.0
        chan_y0 = []; row_y = []
        for ri in range(nrows):
            chan_y0.append(y); y = snap(y + chan_height[ri])
            width, ymin, ymax = row_dims[ri]
            row_y.append(y)                         # row local y=ymin maps to row_y
            y = snap(y + (ymax - ymin))
        chan_y0.append(y); y = snap(y + chan_height[nrows])

        # tap strips: positions at the row ends
        tap_gap_n = snap_up(max(R.tap_act_sep, R.pimp_to_nact + R.pimp_enc_act, R.nimp_enc_act + R.imp_sep * 0))  # p+ tap next to n+ active
        tap_gap_p = snap_up(max(R.tap_act_sep, max(R.pimp_enc_act, R.pimp_enc_gate) + R.pimp_to_ntap))                 # n+ tap next to p+ active (implant blanket to tap)
        row_x_shift = [0.0] * nrows
        tap_extent = {}
        for ri, row in enumerate(rows):
            if row.taps and row.body_net and row.polarity in ("n", "p"):
                tg = tap_gap_n if row.polarity == "n" else tap_gap_p
                tap_extent[ri] = snap_up(tg + tap_w + max(R.m1_sep, 0.1))
            else:
                tap_extent[ri] = 0.0
        # centre rows horizontally relative to the widest (keeps things compact); taps add to the left of each row
        max_w = max(row_dims[ri][0] + 2 * tap_extent[ri] for ri in range(nrows))
        for ri in range(nrows):
            row_x_shift[ri] = snap((max_w - (row_dims[ri][0] + 2 * tap_extent[ri])) / 2 + tap_extent[ri])

        # ---------- 4. collect pins in global coordinates ----------
        def pin_global(ri, c, xoff, p):
            row = rows[ri]; width, ymin, ymax = row_dims[ri]
            gx = snap(row_x_shift[ri] + xoff + p.x)
            if not row.flip:
                gy = snap(row_y[ri] + (p.y - ymin))
                side = p.side
            else:
                gy = snap(row_y[ri] + (ymax - p.y))
                side = "bottom" if p.side == "top" else "top"
            return gx, gy, side

        pins_g = []
        for ri, items in enumerate(placed):
            for c, xoff in items:
                for p in c.pins:
                    gx, gy, side = pin_global(ri, c, xoff, p)
                    ch = ri + 1 if side == "top" else ri
                    pins_g.append(_PlacedPin(p.net, gx, gy, p.width, ri, ch, p.name, c.name, K(ch, p.net, ri)))

        # a via2 pad of one net next to the stub of another net (pads of different nets never share a track)
        min_dx = snap_up(max(stub_w, via2_m2_pad, R.via1_pad_w()) / 2 + stub_w / 2 + R.m2_sep)
        # ---------- 4b. tap strips: compute pin positions (row-relative) before conflict resolution ----------
        tap_specs = []   # dicts with row-relative geometry; drawn after row shifts are final
        for ri, row in enumerate(rows):
            if not (row.taps and row.body_net and row.polarity in ("n", "p")): continue
            width, ymin, ymax = row_dims[ri]
            tg = tap_gap_n if row.polarity == "n" else tap_gap_p
            acts = [c.active_bbox or c.bbox for c, _ in placed[ri]]
            ay0 = min(a[1] for a in acts); ay1 = max(a[3] for a in acts)
            if not row.flip:
                gy0 = snap(row_y[ri] + (ay0 - ymin)); gy1 = snap(row_y[ri] + (ay1 - ymin))
            else:
                gy0 = snap(row_y[ri] + (ymax - ay1)); gy1 = snap(row_y[ri] + (ay0 - ymin) * 0 + (ymax - ay0))
            # minimum tap length for active min area, centred on the row active span
            span = gy1 - gy0
            need = snap_up(max(span, R.act_area_min / tap_w if tap_w > 0 else 0.0, R.act_w_min))
            if need > span:
                ext = snap_up((need - span) / 2); gy0 = snap(gy0 - ext); gy1 = snap(gy1 + ext)
            rx0_act = min((c.active_bbox or c.bbox)[0] + xo for c, xo in placed[ri])
            rx1_act = max((c.active_bbox or c.bbox)[2] + xo for c, xo in placed[ri])
            ch = ri + 1 if not row.flip else ri
            pad = R.via1_pad_w()
            row_pins_x = [p.x + xo for c, xo in placed[ri] for p in c.pins]
            tap_clear = snap_up(max(min_dx, max(p.width for c, _ in placed[ri] for p in c.pins) / 2 + pad / 2 + R.m2_sep))
            # the cell bbox may extend beyond the active (gate pads / risers): keep metal spacing from it as well
            rx0_bb = min(c.bbox[0] + xo for c, xo in placed[ri]); rx1_bb = max(c.bbox[2] + xo for c, xo in placed[ri])
            bb_clear = snap_up(max(R.m1_sep, R.m2_sep, R.act_sep) + tap_w / 2 + 0.05)
            rxc_L = min(snap(rx0_act - tg - tap_w / 2), snap(min(row_pins_x) - tap_clear), snap(rx0_bb - bb_clear))
            rxc_R = max(snap(rx1_act + tg + tap_w / 2), snap(max(row_pins_x) + tap_clear), snap(rx1_bb + bb_clear))
            for side, rxc in (("L", rxc_L), ("R", rxc_R)):
                pin_y = snap(row_y[ri] + (ymax - ymin)) if ch == ri + 1 else snap(row_y[ri])
                vy = snap(pin_y - pad / 2) if ch == ri + 1 else snap(pin_y + pad / 2)
                edge_y = snap(vy + pad / 2) if ch == ri + 1 else snap(vy - pad / 2)
                pp = _PlacedPin(row.body_net, snap(row_x_shift[ri] + rxc), edge_y, pad, ri, ch, f"tap{side}", f"row{ri}", K(ch, row.body_net, ri))
                pins_g.append(pp)
                tap_specs.append({"row": ri, "side": side, "rxc": rxc, "gy0": gy0, "gy1": gy1, "vy": vy, "pin_y": pin_y, "ch": ch, "pin": pp,
                                  "rx0_act": rx0_act, "rx1_act": rx1_act, "tg": tg})

        # ---------- 5. stub conflict check and row shifting (upper rows shift right) ----------
        def trunk_y(ch, net):
            return snap(chan_y0[ch] + ch_margin + chan_tracks[ch][net] * track_pitch + trunk_w / 2)
        def stub_span(pp):
            ty = trunk_y(pp.channel, pp.k())
            return (min(pp.y, ty), max(pp.y, ty))
        def conflicts_for(pins):
            out = []
            for i in range(len(pins)):
                for j in range(i + 1, len(pins)):
                    a, b = pins[i], pins[j]
                    if a.channel != b.channel: continue
                    if a.net == b.net and a.k() != b.k():
                        continue   # split entities of one net: lower stub ends below the upper trunk entity, no overlap
                    if a.net == b.net:
                        # same net: vias on the same trunk must either coincide exactly or keep via spacing
                        dx = abs(a.x - b.x)
                        if dx > 1e-9 and dx + 1e-9 < R.via2_w + R.via2_sep:
                            out.append((a, b))
                        continue
                    if abs(a.x - b.x) + 1e-9 >= min_dx: continue
                    sa, sb = stub_span(a), stub_span(b)
                    if sa[0] <= sb[1] + R.m2_sep and sb[0] <= sa[1] + R.m2_sep:
                        out.append((a, b))
            return out
        # same-row conflicts cannot be fixed by shifting rows
        for a, b in conflicts_for(pins_g):
            if a.row == b.row:
                raise AssemblyError(f"stub conflict inside row {a.row} between {a.cell}.{a.name} ({a.net}) and {b.cell}.{b.name} ({b.net}) at x={a.x},{b.x}")
        # resolve cross-row conflicts row by row (from row 1 upwards) with the smallest |shift| that clears them
        for ri in range(1, nrows):
            lower = [pp for pp in pins_g if pp.row < ri]; mine = [pp for pp in pins_g if pp.row == ri]
            def ok(shift):
                moved = [_PlacedPin(pp.net, snap(pp.x + shift), pp.y, pp.width, pp.row, pp.channel, pp.name, pp.cell, pp.key) for pp in mine]
                return not any(a.row != b.row for a, b in conflicts_for(lower + moved))
            chosen = None
            step = 2 * GRID
            span = max(8.0, sum(row_dims[r][0] for r in range(nrows)) + 4.0)
            for k in range(0, int(span / step)):
                for sgn in ((1,) if k == 0 else (1, -1)):
                    sh = snap(sgn * k * step)
                    if ok(sh): chosen = sh; break
                if chosen is not None: break
            if chosen is None:
                raise AssemblyError(f"could not resolve stub conflicts for row {ri} by shifting")
            if chosen != 0.0:
                for pp in pins_g:
                    if pp.row == ri: pp.x = snap(pp.x + chosen)
                row_x_shift[ri] = snap(row_x_shift[ri] + chosen)
        # keep everything at x >= 0
        xmin_all = min(min(row_x_shift[ri] + min(c.bbox[0] + xo for c, xo in placed[ri]) for ri in range(nrows)), min(pp.x - pp.width for pp in pins_g))
        if xmin_all < 0:
            d = snap_up(-xmin_all)
            for pp in pins_g: pp.x = snap(pp.x + d)
            for ri in range(nrows): row_x_shift[ri] = snap(row_x_shift[ri] + d)

        # verify the packed tracks against the final x shifts; repack and re-place when they overlap
        net_x = compute_net_x(row_x_shift)
        if tracks_valid(net_x, chan_tracks):
            break
        chan_tracks, chan_ntracks = pack_tracks(net_x)
        chan_height = [ (chan_ntracks[ch] * track_pitch + 2 * ch_margin) if chan_tracks[ch] else 0.0 for ch in range(nrows + 1)]
    else:
        raise AssemblyError("track packing did not converge")
    # ---------- 6. place cell geometry ----------
    for ri, items in enumerate(placed):
        row = rows[ri]; width, ymin, ymax = row_dims[ri]
        for c, xoff in items:
            ref = comp << c.component
            if row.flip:
                ref.mirror_y() if hasattr(ref, "mirror_y") else ref.mirror((0, 0), (1, 0))
                ref.move((snap(row_x_shift[ri] + xoff), snap(row_y[ri] + ymax)))
            else:
                ref.move((snap(row_x_shift[ri] + xoff), snap(row_y[ri] - ymin)))

    # ---------- 7. trunks, stubs, vias ----------
    for pp in pins_g:
        if not pp.name.startswith("tap"):
            chan_nets[pp.channel].setdefault(pp.k(), []).append(pp)
    tap_records = []
    for ts in tap_specs:
        ri = ts["row"]; row = rows[ri]; pp = ts["pin"]
        xc = snap(row_x_shift[ri] + ts["rxc"]); pp.x = xc
        ty0, ty1 = ts["gy0"], ts["gy1"]; vy = ts["vy"]; pin_y = ts["pin_y"]; ch = ts["ch"]
        rects.add(lay["tap"], xc - tap_w / 2, ty0, xc + tap_w / 2, ty1)
        imp = R.pimp_layer if row.polarity == "n" else R.nimp_layer
        ienc = R.pimp_enc_act if row.polarity == "n" else R.nimp_enc_act
        if imp is not None:
            rects.add(imp, xc - tap_w / 2 - ienc, ty0 - ienc, xc + tap_w / 2 + ienc, ty1 + ienc)
        ncont = max(1, int(math.floor((ty1 - ty0 - 2 * R.act_enc_cont_tap - R.cont_w) / (R.cont_w + R.cont_sep) + 1e-9)) + 1)
        hcol = ncont * R.cont_w + (ncont - 1) * R.cont_sep
        cy = snap((ty0 + ty1 - hcol) / 2)
        for k in range(ncont):
            yy = snap(cy + k * (R.cont_w + R.cont_sep))
            rects.add(lay["cont"], xc - R.cont_w / 2, yy, xc + R.cont_w / 2, yy + R.cont_w)
        m1w = R.m1_bar_w(); pad = R.via1_pad_w(); pm1 = R.via1_m1_w()
        if ch == ri + 1:
            rects.add(lay["met1"], xc - m1w / 2, cy - R.m1_enc_cont, xc + m1w / 2, vy)
        else:
            rects.add(lay["met1"], xc - m1w / 2, vy, xc + m1w / 2, cy + hcol + R.m1_enc_cont)
        rects.add(lay["met1"], xc - pm1 / 2, vy - pm1 / 2, xc + pm1 / 2, vy + pm1 / 2)
        rects.add(lay["via1"], xc - R.via1_w / 2, vy - R.via1_w / 2, xc + R.via1_w / 2, vy + R.via1_w / 2)
        rects.add(lay["met2"], xc - pad / 2, vy - pad / 2, xc + pad / 2, vy + pad / 2)
        chan_nets[ch].setdefault(pp.k(), []).append(pp)
        tap_records.append({"row": ri, "side": ts["side"], "x": xc, "y0": ty0, "y1": ty1, "net": row.body_net, "contacts": ncont})
    # horizontal tie strip along the gate side of each MOS row, joined to the two end strips by metal-1 (U-shaped tie)
    implant_bridges = []
    for ri, row in enumerate(rows):
        if not (row.taps and row.body_net and row.polarity in ("n", "p")): continue
        width, ymin, ymax = row_dims[ri]
        taps_here = [t for t in tap_records if t["row"] == ri]
        if len(taps_here) < 2: continue
        xl = min(t["x"] for t in taps_here); xr = max(t["x"] for t in taps_here)
        strip_local_y = snap(ymin + 0.1 + tap_w / 2)          # local y of the strip centre (below the cells' bottom)
        if not row.flip: gy = snap(row_y[ri] + (strip_local_y - ymin))
        else: gy = snap(row_y[ri] + (ymax - strip_local_y))
        y0s, y1s = snap(gy - tap_w / 2), snap(gy + tap_w / 2)
        rects.add(lay["tap"], xl - tap_w / 2, y0s, xr + tap_w / 2, y1s)
        imp = R.pimp_layer if row.polarity == "n" else R.nimp_layer
        ienc = R.pimp_enc_act if row.polarity == "n" else R.nimp_enc_act
        if imp is not None: rects.add(imp, xl - tap_w / 2 - ienc, y0s - ienc, xr + tap_w / 2 + ienc, y1s + ienc)
        # when the implant of an end strip and the implant of the gate-side strip are closer than the implant
        # spacing rule (happens when a row's cells have no bottom strap band, e.g. all gate straps on top), the two
        # same-net implants are merged by a bridge over the end strip; layouts with a legal gap are unchanged.
        if imp is not None:
            for t in taps_here:
                lo_gap = (y0s - ienc) - (t["y1"] + ienc); hi_gap = (t["y0"] - ienc) - (y1s + ienc)
                for gap, yb0 in ((lo_gap, t["y1"] + ienc), (hi_gap, y1s + ienc)):
                    if 1e-9 < gap < R.imp_sep - 1e-9:
                        rects.add(imp, t["x"] - tap_w / 2 - ienc, snap(yb0), t["x"] + tap_w / 2 + ienc, snap(yb0 + gap))
                        implant_bridges.append({"row": ri, "x": t["x"], "gap_um": round(gap, 4)})
        nc = max(1, int(math.floor((xr - xl - R.cont_w) / (R.cont_w + R.cont_sep) + 1e-9)) + 1)
        cx0 = snap((xl + xr - (nc * R.cont_w + (nc - 1) * R.cont_sep)) / 2)
        for k in range(nc):
            xx = snap(cx0 + k * (R.cont_w + R.cont_sep))
            rects.add(lay["cont"], xx, gy - R.cont_w / 2, xx + R.cont_w, gy + R.cont_w / 2)
        m1w = R.m1_bar_w()
        rects.add(lay["met1"], xl - m1w / 2, gy - m1w / 2, xr + m1w / 2, gy + m1w / 2)
        # extend the vertical strips' metal-1 to the horizontal strip
        for t in taps_here:
            ylo, yhi = (min(t["y0"], gy), max(t["y1"], gy))
            rects.add(lay["met1"], t["x"] - m1w / 2, ylo, t["x"] + m1w / 2, yhi)
            t["y_strip"] = gy
        tap_records.append({"row": ri, "side": "H", "x0": xl, "x1": xr, "y": gy, "net": row.body_net, "contacts": nc})
    # row blankets: well and implant over the whole row (including taps)
    for ri, row in enumerate(rows):
        if row.polarity not in ("n", "p"): continue
        width, ymin, ymax = row_dims[ri]
        acts = [c.active_bbox or c.bbox for c, _ in placed[ri]]
        ay0 = min(a[1] for a in acts); ay1 = max(a[3] for a in acts)
        if not row.flip:
            gy0 = snap(row_y[ri] + (ay0 - ymin)); gy1 = snap(row_y[ri] + (ay1 - ymin))
        else:
            gy0 = snap(row_y[ri] + (ymax - ay1)); gy1 = snap(row_y[ri] + (ymax - ay0))
        ax0_act = snap(row_x_shift[ri] + min((c.active_bbox or c.bbox)[0] + xo for c, xo in placed[ri]))
        ax1_act = snap(row_x_shift[ri] + max((c.active_bbox or c.bbox)[2] + xo for c, xo in placed[ri]))
        taps_here = [t for t in tap_records if t["row"] == ri and t["side"] != "H"]
        hstrips = [t for t in tap_records if t["row"] == ri and t["side"] == "H"]
        if row.polarity == "p":
            wenc = R.nwell_enc_pact; tenc = R.nwell_enc_ntap
            x0 = min([ax0_act - wenc] + [t["x"] - tap_w / 2 - tenc for t in taps_here]); x1 = max([ax1_act + wenc] + [t["x"] + tap_w / 2 + tenc for t in taps_here])
            y0 = min([gy0 - wenc] + [t["y0"] - tenc for t in taps_here] + [t["y"] - tap_w / 2 - tenc for t in hstrips]); y1 = max([gy1 + wenc] + [t["y1"] + tenc for t in taps_here] + [t["y"] + tap_w / 2 + tenc for t in hstrips])
            rects.add(R.nwell_layer, snap(x0), snap(y0), snap(x1), snap(y1))
            penc = max(R.pimp_enc_act, R.pimp_enc_gate)
            rects.add(R.pimp_layer, snap(ax0_act - penc), snap(gy0 - penc), snap(ax1_act + penc), snap(gy1 + penc))
        else:
            if R.nimp_layer is not None:
                nenc = R.nimp_enc_act
                rects.add(R.nimp_layer, snap(ax0_act - nenc), snap(gy0 - nenc), snap(ax1_act + nenc), snap(gy1 + nenc))

    # risers for nets present in several channels
    net_channels = {}; net_ents = {}
    for ch in range(nrows + 1):
        for key, pl in chan_nets[ch].items():
            if pl:
                net_channels.setdefault(ORIG(key), []).append(ch); net_ents.setdefault(ORIG(key), []).append((ch, key))
    multi = sorted([n for n, ents in net_ents.items() if len(ents) > 1], key=lambda n: (order_hint.get(n, 10 ** 6), n))
    x_all_max = max([pp.x + pp.width / 2 for pp in pins_g] + [snap(row_x_shift[ri] + row_dims[ri][0] + tap_extent[ri]) for ri in range(nrows)])
    riser_pitch = snap_up(max(stub_w, via2_m2_pad) + R.m2_sep)
    riser_x = {}
    for k, net in enumerate(multi):
        riser_x[net] = snap(x_all_max + ch_margin + via2_m2_pad / 2 + k * riser_pitch)
    trunks = []; wire_len = 0.0; n_via2 = 0
    for ch in range(nrows + 1):
        for key, pl in chan_nets[ch].items():
            if not pl: continue
            net = ORIG(key)
            ty = trunk_y(ch, key)
            xs = [pp.x for pp in pl]
            x0 = min(xs) - trunk_w / 2; x1 = max(xs) + trunk_w / 2
            if net in riser_x:
                x1 = max(x1, riser_x[net] + via2_m2_pad / 2)
            if x1 - x0 < trunk_w: x1 = x0 + trunk_w
            rects.add(lay["met3"], x0, ty - trunk_w / 2, x1, ty + trunk_w / 2)
            trunks.append({"channel": ch, "net": net, "key": key, "y": ty, "x0": snap(x0), "x1": snap(x1)})
            wire_len += (x1 - x0)
            # same-net via pads that are closer than the metal spacing are bridged (one merged met2 strip)
            xs_sorted = sorted(set(pp.x for pp in pl))
            for xa, xb in zip(xs_sorted, xs_sorted[1:]):
                if xb - xa < via2_m2_pad + R.m2_sep + 1e-9:
                    rects.add(lay["met2"], xa, ty - via2_m2_pad / 2, xb, ty + via2_m2_pad / 2)
            for pp in pl:
                # stub from pin edge to trunk
                y_lo, y_hi = min(pp.y, ty), max(pp.y, ty)
                rects.add(lay["met2"], pp.x - stub_w / 2, y_lo, pp.x + stub_w / 2, y_hi)
                wire_len += (y_hi - y_lo)
                rects.add(lay["met2"], pp.x - via2_m2_pad / 2, ty - via2_m2_pad / 2, pp.x + via2_m2_pad / 2, ty + via2_m2_pad / 2)
                rects.add(lay["via2"], pp.x - R.via2_w / 2, ty - R.via2_w / 2, pp.x + R.via2_w / 2, ty + R.via2_w / 2)
                n_via2 += 1
    for net, rx in riser_x.items():
        ys = [trunk_y(ch, key) for ch, key in net_ents[net]]
        rects.add(lay["met2"], rx - stub_w / 2, min(ys), rx + stub_w / 2, max(ys))
        wire_len += (max(ys) - min(ys))
        for ty in ys:
            rects.add(lay["met2"], rx - via2_m2_pad / 2, ty - via2_m2_pad / 2, rx + via2_m2_pad / 2, ty + via2_m2_pad / 2)
            rects.add(lay["via2"], rx - R.via2_w / 2, ty - R.via2_w / 2, rx + R.via2_w / 2, ty + R.via2_w / 2)
            n_via2 += 1

    # ---------- 8. labels for external ports ----------
    label_records = []
    missing = [p for p in ports if p not in net_channels]
    if missing:
        raise AssemblyError(f"port nets without any pin: {missing}")
    for net in ports:
        ch = net_channels[net][0]
        tr = next(t for t in trunks if t["channel"] == ch and t["net"] == net)
        lx = snap((tr["x0"] + tr["x1"]) / 2); ly_ = tr["y"]
        if lay.get("met3_label") is not None:
            comp.add_label(text=net, position=(lx, ly_), layer=lay["met3_label"])
        if lay.get("met3_pin") is not None and lay.get("met3_pin") != lay.get("met3_label"):
            rects.add(lay["met3_pin"], lx - trunk_w / 2, ly_ - trunk_w / 2, lx + trunk_w / 2, ly_ + trunk_w / 2)
        # drawing-layer text too (magic attaches text to the paint under it)
        comp.add_label(text=net, position=(lx, ly_), layer=lay["met3"])
        label_records.append({"net": net, "x": lx, "y": ly_, "layer": "met3"})
        comp.add_port(name=net, center=(lx, ly_), width=trunk_w, orientation=0, layer=lay["met3"])

    for layer, rl in rects.r.items():
        for (x0, y0, x1, y1) in rl:
            comp.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=layer)
    bb = comp.bbox
    bbox = (snap(bb[0][0]), snap(bb[0][1]), snap(bb[1][0]), snap(bb[1][1]))
    stats = {"bbox": bbox, "width": snap(bbox[2] - bbox[0]), "height": snap(bbox[3] - bbox[1]),
             "area_um2": round((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 4), "wire_length_um": round(wire_len, 3),
             "n_via2": n_via2, "n_trunks": len(trunks), "n_risers": len(riser_x), "channels": chan_height, "rows": nrows,
             "row_x_shift": row_x_shift, "tap_records": tap_records, "track_pitch": track_pitch, "trunk_w": trunk_w,
             "split_trunks": sorted(f"{ch}:{n}" for ch, n in split_set),
             "row_dims": [{"kind": rows[ri].polarity, "width": snap(row_dims[ri][0]), "height": snap(row_dims[ri][2] - row_dims[ri][1]),
                           "tap_extent": tap_extent[ri], "x_shift": row_x_shift[ri], "y": row_y[ri],
                           "cells": [{"name": c.name, "w": snap(c.bbox[2] - c.bbox[0]), "h": snap(c.bbox[3] - c.bbox[1])} for c, _ in placed[ri]]} for ri in range(nrows)],
             "channel_heights": chan_height, "channel_margin": ch_margin, "implant_bridges": implant_bridges,
             # bookkeeping for the plan-level cost rule (no effect on geometry): which nets each cell / tap strip brings
             # into each channel, under the shared (unsplit) channel strategy
             "channel_net_sources": _channel_net_sources(rows)}
    # self-check: met2 / met3 spacing between shapes (any net) using klayout regions
    try:
        import klayout.db as kdb
        viol = {}
        for lname, sep in (("met2", R.m2_sep), ("met3", R.m3_sep), ("met1", R.m1_sep)):
            reg = kdb.Region()
            for (x0, y0, x1, y1) in rects.r.get(tuple(lay[lname]), []):
                reg.insert(kdb.Box(int(round(x0 * 1000)), int(round(y0 * 1000)), int(round(x1 * 1000)), int(round(y1 * 1000))))
            reg.merge()
            ep = reg.space_check(int(round(sep * 1000)))
            viol[lname] = [[e.first.p1.x / 1000, e.first.p1.y / 1000, e.second.p1.x / 1000, e.second.p1.y / 1000] for e in ep.each()][:10]
        stats["self_check_spacing"] = {k: v for k, v in viol.items() if v}
    except Exception as e:
        stats["self_check_spacing"] = {"error": str(e)}
    comp.info["assembly_stats"] = stats
    # flatten: the DUT is delivered as a single flat cell (hierarchy-free GDS for extraction and review)
    try:
        flat = comp.flatten()
        flat.name = name
        flat.unlock() if hasattr(flat, 'unlock') else None
        for k, v in comp.info.items(): flat.info[k] = v
        for pname, port in comp.ports.items():
            if pname not in flat.ports: flat.add_port(name=pname, port=port)
        comp = flat
    except Exception as e:
        stats["flatten_error"] = repr(e)
    return {"component": comp, "stats": stats, "trunks": trunks, "labels": label_records, "pins": [pp.__dict__ for pp in pins_g]}
