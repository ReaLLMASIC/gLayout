"""Passive pin cells: PDK poly resistors (and later MIM capacitors) as textbook_sharing.assembly PinCells.

Resistor devices (one per PDK, chosen because each PDK's LVS deck and ngspice models support them):
  sky130  sky130_fd_pr__res_high_po_0p35   W fixed 0.35 um, Rs ~ 320 ohm/sq   layers poly(66/20)+poly_res(66/13)+rpm(86/20)+psdm(94/20)
  gf180   ppolyf_u                          Rs ~ 315 ohm/sq (p+ unsalicided)  layers poly2(30/0)+pplus(31/0)+sab(49/0)+res_mk(110/5)
  ihp130  rppd                              Rs 260 ohm/sq                    layers gatpoly(5/0)+psd(14/0)+salblock(28/0)+polyres(128/0)+extblock(111/0)
The body is a single straight poly strip of width w and length l (between the two contact heads); the heads carry
contact arrays and a metal-1 pad, lifted with via1 to a met2 pin on the top edge.  Series segments (m) are not used.
"""
from __future__ import annotations
import math
from .pincell import PinCell, Pin
from glayout.sharing.rules import snap, snap_up

RES = {
    "sky130": {"model": "sky130_fd_pr__res_high_po_0p35", "w_fixed": 0.35, "rsh": 319.8, "poly": (66, 20), "markers": [(66, 13), (86, 20), (94, 20)],
               "marker_enc": {"(66, 13)": 0.0, "(86, 20)": 0.2, "(94, 20)": 0.125}, "head_sep": 0.0, "cont": (66, 44), "cont_w": 0.17, "cont_sp": 0.17, "poly_enc_cont": 0.08,
               "met1": (67, 20), "m1_enc_cont": 0.08, "via1": (67, 44), "via1_w": 0.17, "m1_enc_via1": 0.0, "met2": (68, 20), "m2_enc_via1": 0.06, "m2_w": 0.14, "terminals": 3, "min_l": 0.5, "slot_contact": 0.19, "sab_to_cont": 0.0},
    "gf180": {"model": "ppolyf_u", "w_fixed": None, "rsh": 315.0, "poly": (30, 0), "markers": [(31, 0), (49, 0), (110, 5)],
              "marker_enc": {"(31, 0)": 0.3, "(49, 0)": 0.28, "(110, 5)": 0.0}, "head_sep": 0.0, "cont": (33, 0), "cont_w": 0.22, "cont_sp": 0.28, "poly_enc_cont": 0.07,
              "met1": (34, 0), "m1_enc_cont": 0.12, "via1": (35, 0), "via1_w": 0.26, "m1_enc_via1": 0.12, "met2": (36, 0), "m2_enc_via1": 0.12, "m2_w": 0.28, "terminals": 3, "min_l": 1.0, "sab_to_cont": 0.28},
    "ihp130": {"model": "rppd", "w_fixed": None, "rsh": 260.0, "poly": (5, 0), "markers": [(14, 0), (28, 0), (128, 0), (111, 0)],
               "marker_enc": {"(14, 0)": 0.18, "(28, 0)": 0.2, "(128, 0)": 0.0, "(111, 0)": 0.31}, "head_sep": 0.0, "cont": (6, 0), "cont_w": 0.16, "cont_sp": 0.18, "poly_enc_cont": 0.07,
               "met1": (8, 0), "m1_enc_cont": 0.05, "via1": (19, 0), "via1_w": 0.19, "m1_enc_via1": 0.05, "met2": (10, 0), "m2_enc_via1": 0.05, "m2_w": 0.2, "terminals": 2, "min_l": 0.5, "sab_to_cont": 0.2},
}


# R(l) = a*l + b fitted from two schematic simulations per PDK at the width given (calibrate_res.py, data/res_calibration.json)
CALIB = {"sky130": {"w": 0.35, "a": 1104.2757, "b": 623.2853}, "gf180": {"w": 1.0, "a": 368.7439, "b": 126.0623}, "ihp130": {"w": 1.0, "a": 257.1089, "b": 74.5953}}


def resistor_geometry(pdk_name: str, r_ohm: float, w: float | None = None, max_l: float = 60.0):
    """Choose (w, l) for the requested resistance from the calibrated model R = a*l + b (at the calibration width)."""
    t = RES[pdk_name]; c = CALIB[pdk_name]
    w = t["w_fixed"] or c["w"]
    l = snap_up(max(t["min_l"], (r_ohm - c["b"]) / c["a"]))
    return w, min(l, max_l)


def resistor_pincell(pdk, name: str, net_p: str, net_n: str, r_ohm: float, body_net: str = "VSS", w: float | None = None) -> PinCell:
    """Build the resistor as a flat set of rectangles in a Component. Body horizontal along x."""
    from glayout.backend import Component
    t = RES[pdk.name]; w, l = resistor_geometry(pdk.name, r_ohm, w)
    comp = Component(name)
    rects = []
    def add(layer, x0, y0, x1, y1):
        rects.append((tuple(layer), snap(x0), snap(y0), snap(x1), snap(y1)))
    # body between x=0 and x=l, y in [0,w]; heads beyond
    cw, csp = t["cont_w"], t["cont_sp"]
    head_len = snap_up(t.get("sab_to_cont", 0.2) + cw + t["poly_enc_cont"])        # salicide-block/marker edge to contact + enclosure
    ncont = max(1, int(math.floor((w - 2 * t["poly_enc_cont"] - cw) / (cw + csp) + 1e-9)) + 1)
    while ncont > 1 and ncont * cw + (ncont - 1) * csp > w - 2 * t["poly_enc_cont"] + 1e-9: ncont -= 1
    hcol = ncont * cw + (ncont - 1) * csp; y0c = snap((w - hcol) / 2)
    add(t["poly"], -head_len, 0, l + head_len, w)
    for key in t["markers"]:
        enc = t["marker_enc"][str(key)]
        if key == (94, 20) or key == (31, 0) or key == (14, 0):      # implant: covers heads too
            add(key, -head_len - enc, -enc, l + head_len + enc, w + enc)
        else:                                                       # resistor body markers (res id / salicide block): body only
            add(key, 0 - (enc if key in ((86, 20),) else 0), -enc, l + (enc if key in ((86, 20),) else 0), w + enc)
    pins = []
    m1w = snap_up(max(cw + 2 * t["m1_enc_cont"], t["via1_w"] + 2 * t["m1_enc_via1"]))
    pad = snap_up(max(t["m2_w"], t["via1_w"] + 2 * t["m2_enc_via1"]))
    slot = t.get("slot_contact")
    for side, net, xc in (("P", net_p, -(t.get("sab_to_cont", 0.2) + (slot or cw) / 2)), ("N", net_n, l + t.get("sab_to_cont", 0.2) + (slot or cw) / 2)):
        if slot:   # one contact slot spanning the full resistor width (sky130 licon.1b)
            add(t["cont"], xc - slot / 2, 0, xc + slot / 2, w)
            m1w = snap_up(max(slot + 2 * t["m1_enc_cont"], t["via1_w"] + 2 * t["m1_enc_via1"]))
            y0c = 0.0
        else:
            for c in range(ncont):
                yy = snap(y0c + c * (cw + csp))
                add(t["cont"], xc - cw / 2, yy, xc + cw / 2, yy + cw)
        ytop = snap(w + 0.3)
        add(t["met1"], xc - m1w / 2, y0c - t["m1_enc_cont"], xc + m1w / 2, ytop + m1w / 2)
        add(t["via1"], xc - t["via1_w"] / 2, ytop - t["via1_w"] / 2, xc + t["via1_w"] / 2, ytop + t["via1_w"] / 2)
        add(t["met2"], xc - pad / 2, ytop - pad / 2, xc + pad / 2, ytop + pad / 2)
        pname = f"r{side}"
        comp.add_port(name=pname, center=(snap(xc), snap(ytop + pad / 2)), width=pad, orientation=90, layer=t["met2"])
        pins.append(Pin(pname, net, snap(xc), snap(ytop + pad / 2), "top", pad, t["met2"], [f"{name}:{side}"]))
    if pdk.name == "sky130":
        # NPC (95/20) must enclose the resistor body (rpm.5, 0.095) and the poly head contacts (0.10); one rectangle over the whole poly
        add((95, 20), -head_len - 0.1, -0.1, l + head_len + 0.1, w + 0.1)
    for (layer, x0, y0, x1, y1) in rects:
        comp.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=layer)
    xs0 = min(r[1] for r in rects); ys0 = min(r[2] for r in rects); xs1 = max(r[3] for r in rects); ys1 = max(r[4] for r in rects)
    comp.info["pin_meta"] = {p.name: {"side": "top", "x": p.x, "y": p.y, "width": p.width, "net": p.net, "terminals": p.terminals} for p in pins}
    return PinCell(name, comp, pins, "passive", (xs0, ys0, xs1, ys1), active_bbox=None, body_net=body_net, info={"device": "resistor", "model": t["model"], "w": w, "l": l, "r_ohm_nominal": r_ohm, "rsh": t["rsh"]})


def resistor_spice_line(pdk_name: str, name: str, p: str, n: str, body: str, w: float, l: float, lvs: bool = False) -> str:
    """Simulation form (X-subckt) or LVS form (gf180 deck reads resistors as R elements with the model name)."""
    t = RES[pdk_name]
    if pdk_name == "sky130":
        return f"XR{name} {p} {n} {body} {t['model']} l={l:g} mult=1"
    if pdk_name == "gf180":
        return (f"R{name} {p} {n} {body} {t['model']} L={l:g}u W={w:g}u" if lvs else f"XR{name} {p} {n} {body} {t['model']} r_width={w:g}u r_length={l:g}u")
    return f"XR{name} {p} {n} {t['model']} w={w:g}u l={l:g}u m=1"


# ----------------------------------------------------------------------------------------------------------------
# MIM capacitors.  Layer stacks (foundry layer numbers), plates and the via stack down to the generic met2 pin level.
#   sky130  cap_mim_m3_1 : bottom met3 (70/20), top capm (89/44), via3 (70/44) on capm to met4 (71/20);  generic: met4=met3, met5=met4
#   gf180   cap_mim_2f0fF (option B): bottom metal4 (46/0), top fusetop (75/0), via4 (41/0) to metal5 (81/0); markers cap_mk (117/5), mim_l_mk (117/10)
#   ihp130  cap_cmim     : bottom metal5 (67/0), mim (36/0), vmim (129/0) to topmetal1 (126/0)
# Capacitance densities (model): sky130 2.0 fF/um^2, gf180 2.0 fF/um^2, ihp 1.5 fF/um^2 (nominal; the model computes the value from w,l).
MIM = {
    # bot/top: bottom plate metal and MIM dielectric (top plate) layers; topvia: via on the top plate to topmet;
    # colvia: ordinary via from topmet down to the bottom-plate metal level used at the lead columns (IHP needs TopVia1,
    # not the MIM via); stack_down: (from, via, to, via_w, enc_from, enc_to) down to the generic met2 pin level.
    # lead_h: lead/pad height at the plate metal levels (SKY130 > 3 um so that the deck's "huge metal" spacing rule
    # m3.3/m4.5 does not fire on a narrow stub attached to the plate); lead_gap: clearance between the plate and the
    # top-plate lead column at the bottom-plate metal level (GF180 MIMTM.1: 1.2 um); pad_min: min pad side (metal area).
    "sky130": {"model": "sky130_fd_pr__cap_mim_m3_1", "cdens": 2.0e-15, "bot": (70, 20), "top": (89, 44), "topvia": (70, 44), "topmet": (71, 20), "markers": [],
               "bot_enc_top": 0.2, "top_enc_via": 0.14, "topvia_w": 0.2, "topvia_sp": 0.2, "topmet_enc_via": 0.065, "min_side": 1.0,
               "colvia": (70, 44), "colvia_w": 0.2, "colvia_enc_top": 0.065, "colvia_enc_bot": 0.09, "lead_h": 3.2, "lead_gap": 0.5, "pad_min": 0.65,
               "stack_down": [((70, 20), (69, 44), (69, 20), 0.2, 0.085, 0.085), ((69, 20), (68, 44), (68, 20), 0.15, 0.085, 0.085)], "pin_layer": (68, 20), "pin_w": 0.3},
    # gf180 sim model: legacy 2 fF/um^2 subcircuit cap_mim_2f0fF (the cap_mim_new section fails to parse in ngspice 44: "Syntax error: letter [$]"); lvs_model: KLayout runset class
    "gf180": {"model": "cap_mim_2f0fF", "lvs_model": "cap_mim_2f0_m4m5_noshield", "cdens": 2.0e-15, "bot": (46, 0), "top": (75, 0), "topvia": (41, 0), "topmet": (81, 0), "markers": [(117, 5), (117, 10)],
              "bot_enc_top": 0.6, "top_enc_via": 0.4, "topvia_w": 0.26, "topvia_sp": 0.5, "topmet_enc_via": 0.12, "min_side": 5.0,
              "colvia": (41, 0), "colvia_w": 0.26, "colvia_enc_top": 0.12, "colvia_enc_bot": 0.12, "lead_h": 1.0, "lead_gap": 1.3, "pad_min": 0.5,
              "stack_down": [((46, 0), (40, 0), (42, 0), 0.26, 0.12, 0.12), ((42, 0), (38, 0), (36, 0), 0.26, 0.12, 0.12)], "pin_layer": (36, 0), "pin_w": 0.5},
    "ihp130": {"model": "cap_cmim", "cdens": 1.5e-15, "bot": (67, 0), "top": (36, 0), "topvia": (129, 0), "topmet": (126, 0), "markers": [],
               "bot_enc_top": 0.6, "top_enc_via": 0.3, "topvia_w": 0.42, "topvia_sp": 0.42, "topmet_enc_via": 0.42, "min_side": 1.14,
               "colvia": (125, 0), "colvia_w": 0.42, "colvia_enc_top": 0.42, "colvia_enc_bot": 0.42, "lead_h": 1.7, "lead_gap": 0.5, "pad_min": 0.4,
               "stack_down": [((67, 0), (66, 0), (50, 0), 0.19, 0.065, 0.065), ((50, 0), (49, 0), (30, 0), 0.19, 0.065, 0.065), ((30, 0), (29, 0), (10, 0), 0.19, 0.065, 0.065)], "pin_layer": (10, 0), "pin_w": 0.3},
}


def mim_geometry(pdk_name: str, c_farad: float):
    t = MIM[pdk_name]; side = snap_up(max(t["min_side"], math.sqrt(c_farad / t["cdens"])))   # cdens is F per um^2 -> side in um
    return side, side


def mimcap_pincell(pdk, name: str, net_top: str, net_bot: str, c_farad: float) -> PinCell:
    """Square MIM capacitor.  The top plate is contacted by a sea of top-plate vias to the top metal, which leads to a
    column at the LEFT of the plate; the bottom plate leads to a column at the RIGHT.  Both columns stack down to the
    generic met2 pin level, where a short strip to the cell top makes the two pins (cT = top plate, cB = bottom plate)."""
    from glayout.backend import Component
    t = MIM[pdk.name]; w, l = mim_geometry(pdk.name, c_farad)
    comp = Component(name); rects = []
    def add(layer, x0, y0, x1, y1): rects.append((tuple(layer), snap(x0), snap(y0), snap(x1), snap(y1)))
    e = t["bot_enc_top"]; lead_h = t["lead_h"]; yc = snap(l / 2)
    add(t["bot"], -e, -e, w + e, l + e)                # bottom plate
    add(t["top"], 0, 0, w, l)                           # top plate (dielectric capacitor layer)
    for mk in t["markers"]: add(mk, -e, -e, w + e, l + e)
    # sea of vias on the top plate -> top metal
    vw, vs, ve = t["topvia_w"], t["topvia_sp"], t["top_enc_via"]
    n = max(1, int((w - 2 * ve + vs) // (vw + vs)))
    pitch = vw + vs; x0 = snap((w - (n * vw + (n - 1) * vs)) / 2)
    for i in range(n):
        for j in range(n):
            add(t["topvia"], x0 + i * pitch, x0 + j * pitch, x0 + i * pitch + vw, x0 + j * pitch + vw)
    tm = t["topmet_enc_via"]
    add(t["topmet"], x0 - tm, x0 - tm, w - x0 + tm, l - x0 + tm)
    # column positions
    cw = t["colvia_w"]; pad_bot = max(t["pad_min"], cw + 2 * t["colvia_enc_bot"]); pad_top = max(lead_h, cw + 2 * t["colvia_enc_top"])
    xL = snap(-(e + t["lead_gap"] + max(pad_bot, pad_top) / 2)); xR = snap(w + e + 0.3 + max(pad_bot, pad_top) / 2)
    # LEFT column (top plate): top-metal lead from the via sea to the column, pad, column via, bottom-metal pad, stack down
    add(t["topmet"], xL - pad_top / 2, yc - lead_h / 2, x0 - tm + 0.1, yc + lead_h / 2)
    add(t["topmet"], xL - pad_top / 2, yc - pad_top / 2, xL + pad_top / 2, yc + pad_top / 2)
    add(t["colvia"], xL - cw / 2, yc - cw / 2, xL + cw / 2, yc + cw / 2)
    add(t["bot"], xL - pad_bot / 2, yc - pad_bot / 2, xL + pad_bot / 2, yc + pad_bot / 2)
    # RIGHT column (bottom plate): bottom-metal lead attached to the plate, pad, stack down
    add(t["bot"], w + e - 0.1, yc - lead_h / 2, xR + pad_bot / 2, yc + lead_h / 2)
    add(t["bot"], xR - pad_bot / 2, yc - max(pad_bot, lead_h) / 2, xR + pad_bot / 2, yc + max(pad_bot, lead_h) / 2)
    def stack(xc):
        for (frm, via, to, vw2, ef, et) in t["stack_down"]:
            pf = max(t["pad_min"], vw2 + 2 * ef); pt = max(t["pad_min"], vw2 + 2 * et)
            add(frm, xc - pf / 2, yc - pf / 2, xc + pf / 2, yc + pf / 2)
            add(via, xc - vw2 / 2, yc - vw2 / 2, xc + vw2 / 2, yc + vw2 / 2)
            add(to, xc - pt / 2, yc - pt / 2, xc + pt / 2, yc + pt / 2)
    stack(xL); stack(xR)
    pins = []
    pw = t["pin_w"]; ytop = snap(l + e + 0.6)
    for pname, xc, net in (("cT", xL, net_top), ("cB", xR, net_bot)):
        add(t["pin_layer"], xc - pw / 2, yc, xc + pw / 2, ytop)
        comp.add_port(name=pname, center=(snap(xc), ytop), width=pw, orientation=90, layer=t["pin_layer"])
        pins.append(Pin(pname, net, snap(xc), ytop, "top", pw, t["pin_layer"], [f"{name}:{pname}"]))
    for (layer, x0_, y0_, x1_, y1_) in rects:
        comp.add_polygon([(x0_, y0_), (x1_, y0_), (x1_, y1_), (x0_, y1_)], layer=layer)
    xs0 = min(r[1] for r in rects); ys0 = min(r[2] for r in rects); xs1 = max(r[3] for r in rects); ys1 = max(r[4] for r in rects)
    comp.info["pin_meta"] = {p.name: {"side": "top", "x": p.x, "y": p.y, "width": p.width, "net": p.net, "terminals": p.terminals} for p in pins}
    return PinCell(name, comp, pins, "passive", (xs0, ys0, xs1, ys1), active_bbox=None, body_net=None, info={"device": "mimcap", "model": t["model"], "w": w, "l": l, "c_nominal": c_farad})


def mimcap_spice_line(pdk_name: str, name: str, top: str, bot: str, w: float, l: float, lvs: bool = False) -> str:
    t = MIM[pdk_name]
    if pdk_name == "sky130":
        return f"XC{name} {top} {bot} {t['model']} w={w:g} l={l:g}"
    if pdk_name == "gf180":
        # KLayout's gf180 runset extracts MIM caps as device class cap_mim_2f0_m4m5_noshield compared on A and P, which its
        # schematic reader (SubcircuitModelsReader in custom_classes.lvs) derives from W and L of a 'C' element
        return (f"C{name} {top} {bot} {t['lvs_model']} W={w:g}u L={l:g}u" if lvs else f"XC{name} {top} {bot} {t['model']} c_width={w:g}u c_length={l:g}u")
    return f"XC{name} {top} {bot} {t['model']} w={w:g}u l={l:g}u"
