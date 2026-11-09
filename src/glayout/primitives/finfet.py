"""FinFET device geometry behind the existing planar primitive interface.

Generic 'poly' ports are local gate interconnect (LIG); physical gates are
separate fixed-width stripes. Everything above fet.__gen_fingers_macro keeps
its original placement, finger routing, and public port names.
"""

from dataclasses import asdict
import math
from glayout.backend import Component
from glayout.spice import Netlist


def _rect(comp, layer, x0, y0, x1, y1):
    comp.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=layer)


def _ports(comp, prefix, bounds, layer):
    x0, y0, x1, y1 = bounds
    for side, center, orientation, width in (
        ("W", (x0, (y0 + y1) / 2), 180, y1 - y0),
        ("N", ((x0 + x1) / 2, y1), 90, x1 - x0),
        ("E", (x1, (y0 + y1) / 2), 0, y1 - y0),
        ("S", ((x0 + x1) / 2, y0), 270, x1 - x0),
    ):
        comp.add_port(
            name=prefix + side,
            center=center,
            orientation=orientation,
            width=width,
            layer=layer,
            port_type="electrical",
        )


def _sd_v0_centers(nf, yoff, fin_pitch=0.027):
    """Return vertical V0 cut centers along an S/D trench for nf fins."""
    n_v0 = max(1, (nf + 1) // 2)
    step = 2 * fin_pitch
    return [yoff + (k - (n_v0 - 1) / 2) * step for k in range(n_v0)]


def fingers(
    pdk, rmult, fingers, length, width, poly_height, sdlayer, inter_finger_topmet
):
    from glayout.primitives.via_gen import via_stack

    t = pdk.finfet
    flavor = pdk.get_finfet_flavor()
    if length is not None and not math.isclose(length, t.gate_length, abs_tol=1e-10):
        raise ValueError("unsupported FinFET gate length")
    nf = t.fin_count(width)
    height = nf * t.fin_pitch
    # Preserve the global fin/gate phase, including even finger/fin counts.
    xoff = t.gate_pitch / 2 if fingers % 2 == 0 else 0.0
    yoff = t.fin_pitch / 2 if nf % 2 == 0 else 0.0
    contact_size = max(t.sd_width, pdk.get_grule("met1")["min_width"])
    pitch = t.gate_pitch * max(
        1,
        math.ceil(
            (rmult * contact_size + pdk.get_grule("met1")["min_separation"])
            / t.gate_pitch
            - 1e-9
        ),
    )
    xs = [(i - fingers / 2) * pitch + xoff for i in range(fingers + 1)]
    gx = [(xs[i] + xs[i + 1]) / 2 for i in range(fingers)]
    # Quantize routing multiplier pitch to an odd gate-pitch multiple so
    # contact midpoints and gates remain on the same fixed gate lattice.
    if any(abs(x / t.gate_pitch - round(x / t.gate_pitch)) > 1e-7 for x in gx):
        pitch += t.gate_pitch
        xs = [(i - fingers / 2) * pitch + xoff for i in range(fingers + 1)]
        gx = [(xs[i] + xs[i + 1]) / 2 for i in range(fingers)]
    left, right = xs[0] - 0.012, xs[-1] + 0.012
    bottom, top = -height / 2 + yoff, height / 2 + yoff
    c = Component()
    _rect(c, pdk.get_glayer("active_diff"), left, bottom, right, top)
    _ports(c, "diff_", (left, bottom, right, top), pdk.get_glayer("active_diff"))
    gate_bottom = bottom - t.gate_extension
    gate_top = top + t.active_gate_extension
    gate_contact_y = gate_bottom + 0.014
    for i, x in enumerate(gx):
        _rect(
            c,
            t.gate_layer,
            x - t.gate_length / 2,
            gate_bottom,
            x + t.gate_length / 2,
            gate_top,
        )
        lig = (x - 0.011, gate_contact_y - 0.011, x + 0.011, gate_contact_y + 0.011)
        # Keep ports inside the landing so half-grid alignment retains overlap.
        overlap = 2 * t.manufacturing_grid
        _rect(
            c,
            pdk.get_glayer("poly"),
            lig[0] - overlap,
            lig[1] - overlap,
            lig[2] + overlap,
            lig[3] + overlap,
        )
        _ports(c, f"row0_col{i}_gate_", lig, pdk.get_glayer("poly"))
    fin_left = min(left, right - t.fin_min_length)
    for i in range(nf):
        y = (i - (nf - 1) / 2) * t.fin_pitch + yoff
        _rect(c, t.fin_layer, fin_left, y - t.fin_width / 2, right, y + t.fin_width / 2)
    select = (
        left - t.select_enclosure,
        gate_bottom - t.select_enclosure,
        right + t.select_enclosure,
        gate_top + t.select_enclosure,
    )
    _rect(c, pdk.get_glayer(sdlayer), *select)
    if flavor.marker is not None:
        _rect(c, pdk.get_glayer(flavor.marker), *select)
    if sdlayer == "p+s/d":
        enc = t.well_enclosure
        _rect(
            c,
            pdk.get_glayer("nwell"),
            select[0] - enc,
            select[1] - enc,
            select[2] + enc,
            select[3] + enc,
        )
    _ports(
        c,
        "plusdoped_",
        (
            left - t.select_enclosure,
            bottom - t.select_enclosure,
            right + t.select_enclosure,
            top + t.select_enclosure,
        ),
        pdk.get_glayer(sdlayer),
    )
    pad_y0 = min(bottom, yoff - 0.014)
    pad_y1 = max(top, yoff + 0.014)
    v0_ys = _sd_v0_centers(nf, yoff, t.fin_pitch)
    for i, x in enumerate(xs):
        _rect(c, pdk.get_glayer("sdt"), x - 0.012, bottom, x + 0.012, top)
        _rect(c, pdk.get_glayer("lisd"), x - 0.012, pad_y0, x + 0.012, pad_y1)
        for yv in v0_ys:
            _rect(
                c,
                pdk.get_glayer("mcon"),
                x - 0.009,
                yv - 0.009,
                x + 0.009,
                yv + 0.009,
            )
        pad = (
            x - contact_size / 2,
            pad_y0,
            x + contact_size / 2,
            pad_y1,
        )
        _rect(c, pdk.get_glayer("met1"), *pad)
        prefix = "leftsd_" if i == 0 else f"row0_col{i-1}_rightsd_"
        _ports(c, prefix + "bottom_met_", pad, pdk.get_glayer("met1"))
        _ports(c, prefix + "bottom_layer_", pad, pdk.get_glayer("met1"))
        _ports(c, prefix + "top_met_", pad, pdk.get_glayer("met1"))
    # A virtual device envelope preserves bbox-centering assumptions without
    # shifting physical fin/gate masks off their manufacturing lattices.
    envelope = t.well_enclosure if sdlayer == "p+s/d" else 0
    bx = (
        math.ceil((max(abs(select[0]), abs(select[2])) + envelope) / t.gate_pitch)
        * t.gate_pitch
    )
    by = (
        math.ceil((max(abs(select[1]), abs(select[3])) + envelope) / t.fin_pitch)
        * t.fin_pitch
    )
    _rect(c, (100, 0), -bx, -by, bx, by)
    c.info["finfet_technology"] = asdict(t)
    c.info["finfet"] = {
        "nfin": nf,
        "fingers": fingers,
        "multipliers": 1,
        "width": height,
        "length": t.gate_length,
        "vt": pdk.finfet_flavor,
        "model": pdk.models["pfet" if sdlayer == "p+s/d" else "nfet"],
    }
    t.validate(c)
    return c


def add_finfet_dummies(
    pdk,
    multiplier,
    fingers,
    width,
    sdlayer,
    dummyl,
    dummyr,
    dummy_routes=True,
    rmult=1,
):
    """Place compact 2xCPP FinFET dummy gates sharing the continuous fin/select/well row."""
    t = pdk.finfet
    flavor = pdk.get_finfet_flavor()
    nf = t.fin_count(width)
    height = nf * t.fin_pitch
    xoff = t.gate_pitch / 2 if fingers % 2 == 0 else 0.0
    yoff = t.fin_pitch / 2 if nf % 2 == 0 else 0.0
    contact_size = max(t.sd_width, pdk.get_grule("met1")["min_width"])
    pitch = t.gate_pitch * max(
        1,
        math.ceil(
            (rmult * contact_size + pdk.get_grule("met1")["min_separation"])
            / t.gate_pitch
            - 1e-9
        ),
    )
    xs = [(i - fingers / 2) * pitch + xoff for i in range(fingers + 1)]
    gx = [(xs[i] + xs[i + 1]) / 2 for i in range(fingers)]
    if any(abs(x / t.gate_pitch - round(x / t.gate_pitch)) > 1e-7 for x in gx):
        pitch += t.gate_pitch
        xs = [(i - fingers / 2) * pitch + xoff for i in range(fingers + 1)]
        gx = [(xs[i] + xs[i + 1]) / 2 for i in range(fingers)]

    bottom, top = -height / 2 + yoff, height / 2 + yoff
    gate_bottom = bottom - t.gate_extension
    gate_top = top + t.active_gate_extension
    gate_contact_y = gate_bottom + 0.014
    pad_y0 = min(bottom, yoff - 0.014)
    pad_y1 = max(top, yoff + 0.014)
    v0_ys = _sd_v0_centers(nf, yoff, t.fin_pitch)

    sides = []
    if dummyl:
        sides.append((-1, "dummy_L_", xs[0] - 1.5 * t.gate_pitch))
    if dummyr:
        sides.append((1, "dummy_R_", xs[-1] + 1.5 * t.gate_pitch))

    fin_min_x = xs[0] - 0.012
    fin_max_x = xs[-1] + 0.012
    for side, name, x_dum in sides:
        x_L = x_dum - 0.5 * t.gate_pitch
        x_R = x_dum + 0.5 * t.gate_pitch
        act_left, act_right = x_L - 0.012, x_R + 0.012
        fin_min_x = min(fin_min_x, act_left)
        fin_max_x = max(fin_max_x, act_right)

        _rect(multiplier, pdk.get_glayer("active_diff"), act_left, bottom, act_right, top)
        _ports(
            multiplier,
            name + "diff_",
            (act_left, bottom, act_right, top),
            pdk.get_glayer("active_diff"),
        )
        _rect(
            multiplier,
            t.gate_layer,
            x_dum - t.gate_length / 2,
            gate_bottom,
            x_dum + t.gate_length / 2,
            gate_top,
        )
        lig = (
            x_dum - 0.011,
            gate_contact_y - 0.011,
            x_dum + 0.011,
            gate_contact_y + 0.011,
        )
        overlap = 2 * t.manufacturing_grid
        _rect(
            multiplier,
            pdk.get_glayer("poly"),
            lig[0] - overlap,
            lig[1] - overlap,
            lig[2] + overlap,
            lig[3] + overlap,
        )
        _ports(multiplier, name + "row0_col0_gate_", lig, pdk.get_glayer("poly"))

        for idx, x_sd in enumerate((x_L, x_R)):
            _rect(multiplier, pdk.get_glayer("sdt"), x_sd - 0.012, bottom, x_sd + 0.012, top)
            _rect(
                multiplier,
                pdk.get_glayer("lisd"),
                x_sd - 0.012,
                pad_y0,
                x_sd + 0.012,
                pad_y1,
            )
            for yv in v0_ys:
                _rect(
                    multiplier,
                    pdk.get_glayer("mcon"),
                    x_sd - 0.009,
                    yv - 0.009,
                    x_sd + 0.009,
                    yv + 0.009,
                )
            sd_pad_y0 = gate_contact_y - 0.012 if dummy_routes else pad_y0
            pad = (x_sd - 0.012, sd_pad_y0, x_sd + 0.012, pad_y1)
            _rect(multiplier, pdk.get_glayer("met1"), *pad)
            sd_prefix = name + ("leftsd_" if idx == 0 else "row0_col0_rightsd_")
            _ports(multiplier, sd_prefix + "bottom_met_", pad, pdk.get_glayer("met1"))
            _ports(multiplier, sd_prefix + "bottom_layer_", pad, pdk.get_glayer("met1"))
            _ports(multiplier, sd_prefix + "top_met_", pad, pdk.get_glayer("met1"))

        if dummy_routes:
            _rect(
                multiplier,
                pdk.get_glayer("mcon"),
                x_dum - 0.009,
                gate_contact_y - 0.009,
                x_dum + 0.009,
                gate_contact_y + 0.009,
            )
            gsd_bar = (
                x_L - 0.012,
                gate_contact_y - 0.012,
                x_R + 0.012,
                gate_contact_y + 0.012,
            )
            _rect(multiplier, pdk.get_glayer("met1"), *gsd_bar)
            _ports(
                multiplier,
                name + "gsdcon_top_met_",
                gsd_bar,
                pdk.get_glayer("met1"),
            )
            _ports(
                multiplier,
                name + "gsdcon_bottom_met_",
                gsd_bar,
                pdk.get_glayer("met1"),
            )

        dum_select = (
            act_left - t.select_enclosure,
            bottom - t.select_enclosure,
            act_right + t.select_enclosure,
            top + t.select_enclosure,
        )
        _ports(multiplier, name + "plusdoped_", dum_select, pdk.get_glayer(sdlayer))

    # Extend continuous fins, select, Vt marker, and well across the entire row.
    fin_left = min(fin_min_x, fin_max_x - t.fin_min_length)
    for i in range(nf):
        y = (i - (nf - 1) / 2) * t.fin_pitch + yoff
        _rect(
            multiplier,
            t.fin_layer,
            fin_left,
            y - t.fin_width / 2,
            fin_max_x,
            y + t.fin_width / 2,
        )
    row_select = (
        fin_min_x - t.select_enclosure,
        gate_bottom - t.select_enclosure,
        fin_max_x + t.select_enclosure,
        gate_top + t.select_enclosure,
    )
    _rect(multiplier, pdk.get_glayer(sdlayer), *row_select)
    if flavor.marker is not None:
        _rect(multiplier, pdk.get_glayer(flavor.marker), *row_select)
    if sdlayer == "p+s/d":
        enc = t.well_enclosure
        _rect(
            multiplier,
            pdk.get_glayer("nwell"),
            row_select[0] - enc,
            row_select[1] - enc,
            row_select[2] + enc,
            row_select[3] + enc,
        )
    for side in ("W", "N", "E", "S"):
        multiplier.ports.pop("plusdoped_" + side, None)
    _ports(
        multiplier,
        "plusdoped_",
        (
            fin_min_x - t.select_enclosure,
            bottom - t.select_enclosure,
            fin_max_x + t.select_enclosure,
            top + t.select_enclosure,
        ),
        pdk.get_glayer(sdlayer),
    )
    envelope = t.well_enclosure if sdlayer == "p+s/d" else 0
    bx = (
        math.ceil((max(abs(row_select[0]), abs(row_select[2])) + envelope) / t.gate_pitch)
        * t.gate_pitch
    )
    by = (
        math.ceil((max(abs(row_select[1]), abs(row_select[3])) + envelope) / t.fin_pitch)
        * t.fin_pitch
    )
    _rect(multiplier, (100, 0), -bx, -by, bx, by)


def finfet_tapring(
    pdk,
    enclosed_rectangle=(2.0, 4.0),
    sdlayer="p+s/d",
    horizontal_glayer="met2",
    vertical_glayer="met1",
    sides=(True, True, True, True),
):
    """Fast, compact FinFET substrate/well tie ring without per-via reference overhead."""
    pdk.has_required_glayers(
        [sdlayer, "active_tap", "mcon", horizontal_glayer, vertical_glayer]
    )
    pdk.activate()
    if "met" not in horizontal_glayer or "met" not in vertical_glayer:
        raise ValueError("both horizontal and vertical glayers should be metals")
    wx, wy = pdk.snap_to_2xgrid(enclosed_rectangle, return_type="float")
    min_gap_tap = pdk.get_grule("active_tap")["min_separation"]
    if wx < min_gap_tap:
        raise ValueError("ptapring must be larger than " + str(min_gap_tap))
    tap_w = max(
        0.028,
        pdk.get_grule("active_tap")["min_width"],
        pdk.get_grule(horizontal_glayer)["min_width"],
        pdk.get_grule(vertical_glayer)["min_width"],
    )
    tap_w = pdk.snap_to_2xgrid(tap_w)
    hx, hy = wx / 2, wy / 2
    ox, oy = hx + tap_w, hy + tap_w
    c = Component()

    pp_enc = pdk.get_grule("active_tap", sdlayer)["min_enclosure"]
    if sdlayer == "n+s/d":
        nwell_enc = pdk.get_grule("nwell", "active_tap")["min_enclosure"]
        _rect(
            c,
            pdk.get_glayer("nwell"),
            -ox - nwell_enc,
            -oy - nwell_enc,
            ox + nwell_enc,
            oy + nwell_enc,
        )

    def _add_bar(prefix, bounds, top_glayer, is_horizontal):
        x0, y0, x1, y1 = bounds
        _rect(c, pdk.get_glayer("active_tap"), x0, y0, x1, y1)
        _rect(c, pdk.get_glayer("met1"), x0, y0, x1, y1)
        if top_glayer != "met1":
            _rect(c, pdk.get_glayer(top_glayer), x0, y0, x1, y1)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            span = (x1 - x0) if is_horizontal else (y1 - y0)
            n_cuts = max(1, min(5, int((span - 0.010) // 0.054) + 1))
            for k in range(n_cuts):
                off = (k - (n_cuts - 1) / 2) * 0.054
                vx = cx + off if is_horizontal else cx
                vy = cy if is_horizontal else cy + off
                _rect(
                    c,
                    pdk.get_glayer("via1"),
                    vx - 0.009,
                    vy - 0.009,
                    vx + 0.009,
                    vy + 0.009,
                )
        _ports(c, prefix + "top_met_", bounds, pdk.get_glayer(top_glayer))
        _ports(c, prefix + "bottom_met_", bounds, pdk.get_glayer("met1"))
        _ports(c, prefix + "bottom_layer_", bounds, pdk.get_glayer("active_tap"))

    if sides[1]:  # N
        _add_bar("N_", (-hx, hy, hx, oy), horizontal_glayer, True)
    if sides[2]:  # E
        _add_bar("E_", (hx, -hy, ox, hy), vertical_glayer, False)
    if sides[3]:  # S
        _add_bar("S_", (-hx, -oy, hx, -hy), horizontal_glayer, True)
    if sides[0]:  # W
        _add_bar("W_", (-ox, -hy, -hx, hy), vertical_glayer, False)

    corners = [
        (sides[1] and sides[0], "tl_", (-ox, hy, -hx, oy)),
        (sides[1] and sides[2], "tr_", (hx, hy, ox, oy)),
        (sides[3] and sides[0], "bl_", (-ox, -oy, -hx, -hy)),
        (sides[3] and sides[2], "br_", (hx, -oy, ox, -hy)),
    ]
    for active_corner, prefix, cbounds in corners:
        if not active_corner:
            continue
        x0, y0, x1, y1 = cbounds
        _rect(c, pdk.get_glayer("active_tap"), x0, y0, x1, y1)
        _rect(c, pdk.get_glayer("met1"), x0, y0, x1, y1)
        _rect(c, pdk.get_glayer(horizontal_glayer), x0, y0, x1, y1)
        _rect(c, pdk.get_glayer(vertical_glayer), x0, y0, x1, y1)
        if horizontal_glayer != vertical_glayer:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            _rect(
                c,
                pdk.get_glayer("via1"),
                cx - 0.009,
                cy - 0.009,
                cx + 0.009,
                cy + 0.009,
            )
        _ports(c, prefix + "top_met_", cbounds, pdk.get_glayer(horizontal_glayer))
        _ports(c, prefix + "bottom_met_", cbounds, pdk.get_glayer(vertical_glayer))
    return c


def finfet(
    pdk,
    device="nfet",
    width=0.081,
    nfin=None,
    length=None,
    fingers=1,
    multipliers=1,
    with_dummy=True,
    sd_route_topmet="met2",
    gate_route_topmet="met2",
    vt=None,
    **kwargs,
):
    from glayout.primitives.fet import nmos, pmos

    fn = nmos if device == "nfet" else pmos if device == "pfet" else None
    if fn is None:
        raise ValueError("device must be nfet or pfet")
    return fn(
        pdk,
        width=width,
        nfin=nfin,
        length=length,
        fingers=fingers,
        multipliers=multipliers,
        with_dummy=with_dummy,
        sd_route_topmet=sd_route_topmet,
        gate_route_topmet=gate_route_topmet,
        vt=vt,
        **kwargs,
    )


def finfet_netlist(
    pdk,
    device,
    nfin,
    fingers,
    multipliers,
    with_dummy=False,
    dummies_tied_to_bulk=False,
):
    pdk.get_finfet_flavor()
    model = pdk.models[device]
    dummy = (with_dummy, with_dummy) if isinstance(with_dummy, bool) else with_dummy
    lines = [".subckt {circuit_name} {nodes}"]
    lines += [
        f"M{i} D G S B {model} l={pdk.finfet.gate_length}u nfin={nfin}"
        for i in range(fingers * multipliers)
    ]
    dummy_node = "B" if dummies_tied_to_bulk else "DUM"
    lines += [
        f"MD{i} {dummy_node} {dummy_node} {dummy_node} B {model} l={pdk.finfet.gate_length}u nfin={nfin}"
        for i in range(sum(dummy) * multipliers)
    ]
    lines += [".ends {circuit_name}"]
    return Netlist(
        circuit_name=("NFET" if device == "nfet" else "PFET")
        + ("" if pdk.finfet_flavor == "rvt" else "_" + pdk.finfet_flavor.upper()),
        nodes=["D", "G", "S", "B", "DUM"],
        source_netlist="\n".join(lines),
        parameters={
            "nfin": nfin,
            "length": pdk.finfet.gate_length,
            "width": nfin * pdk.finfet.fin_pitch,
        },
    )
