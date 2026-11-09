"""First-pass design points and specification floors of every topology and PDK.

The floors (specs) returned here are the category floors that every schematic must meet before its specification is
frozen (see qualify.py).  The sizing, bias and load values were the starting points of a schematic pre-simulation loop;
the tuned nominal design points that the size grid is derived from are stored as data in data/nominal/<topology>/<pdk>.json.

Units: w, l in um; currents in A; voltages in V.  'uw' = unit finger width helper per PDK.
Design intent per PDK: VDD sky130 1.8 V (lv 1.8 V devices), gf180 3.3 V, ihp 1.2 V; bias 20 uA branches;
L = 2*Lmin for analog devices (mirrors use 4*Lmin for output resistance), input pairs wider.
"""
from __future__ import annotations
from .cases import CaseSpec, PDK_POINT
from textbook_sharing.assembly.passives import resistor_geometry, mim_geometry, MIM

LMIN = {"sky130": 0.15, "gf180": 0.28, "ihp130": 0.13}
UW = {"sky130": 0.5, "gf180": 0.5, "ihp130": 0.5}          # unit finger width of the first-pass points (above the contactable minimum)


def M(pdk, nf, lmult=2):
    return {"w": round(UW[pdk] * nf, 3), "l": round(LMIN[pdk] * lmult, 3), "nf": nf}


def nominal(cid, pdk):
    vdd = PDK_POINT[pdk]["vdd"]; ib = 20e-6
    vcm = {"sky130": 0.9, "gf180": 1.5, "ihp130": 0.6}[pdk]
    S = {}; bias = {}; load = {}; specs = {}
    lmir = 8 if pdk == "ihp130" else 4
    if cid == "C01":
        S = {"M1": M(pdk, 4, lmir), "M2": M(pdk, 4, lmir)}; bias = {"IB1": {"i": ib, "from": "VDD"}}; load = {"vout_nom": vdd / 2, "tol": 0.05}; bias["IREF"] = ib
        specs = {"err": {"abs_max": 0.05}, "vmin": {"max": 0.35 * vdd}}
    elif cid == "C02":
        S = {k: M(pdk, 4, lmir // 2) for k in ("M1", "M2", "M3", "M4")}; bias = {"IIN1": {"i": ib, "from": "VDD"}, "IREF": ib}; load = {"vout_nom": 0.65 * vdd, "tol": 0.03}
        specs = {"err": {"abs_max": 0.03}, "vmin": {"max": 0.6 * vdd}}
    elif cid == "C03":
        S = {k: M(pdk, 8, 16 if pdk == "ihp130" else 8) for k in ("M1", "M2", "M3")}; bias = {"IIN1": {"i": ib, "from": "VDD"}, "IREF": ib}; load = {"vout_nom": 0.65 * vdd, "tol": 0.10}
        specs = {"err": {"abs_max": 0.10}, "vmin": {"max": 0.65 * vdd}}
    elif cid == "C13":
        S = {"M1": M(pdk, 1, lmir // 2), "M2": M(pdk, 4, lmir // 2), "M3": M(pdk, 4, lmir // 2), "M4": M(pdk, 4, lmir // 2), "M5": M(pdk, 4, lmir // 2)}
        bias = {"IB1": {"i": ib, "from": "VDD"}, "IIN1": {"i": ib, "from": "VDD"}, "IREF": ib}; load = {"vout_nom": vdd / 2, "tol": 0.03}
        specs = {"err": {"abs_max": 0.03}, "vmin": {"max": 0.4 * vdd}}
    elif cid == "C14":
        S = {"M1": M(pdk, 4, lmir), "M2": M(pdk, 4, lmir), "M3": M(pdk, 2, lmir), "M4": M(pdk, 4, lmir)}
        bias = {"IIN1": {"i": ib, "from": "VDD"}, "IREF1": {"i": ib / 4, "from": "VDD"}, "IREF": ib}; load = {"vout_nom": 0.65 * vdd, "tol": 0.03}
        specs = {"err": {"abs_max": 0.03}, "vmin": {"max": 0.6 * vdd}}
    elif cid == "C04":
        S = {"M1": M(pdk, 8, 2), "M2": M(pdk, 4, 2)}; bias = {"VB1": {"replica": "M1", "current": ib}}; load = {"CL": 100e-15}
        specs = {"gain_lf": {"min": 20.0}, "f3db": {"min": 1e6}}
    elif cid == "C05":
        S = {"M1": M(pdk, 4, 2), "M2": M(pdk, 8, 2)}; bias = {"VB1": {"replica": "M1", "current": ib}}; load = {"vin_nom": 0.65 * vdd, "RL": 20e3, "CL": 1e-12}
        specs = {"gain_at_nom": {"min": 0.6}, "f3db": {"min": 10e6}}
    elif cid == "C06":
        S = {"M1": M(pdk, 8, 2), "M2": M(pdk, 8, 2), "M3": M(pdk, 4, 2), "M4": M(pdk, 4, 2)}
        bias = {"VB1": {"replica": "M4", "current": ib, "kind": "cascode"}, "VB2": {"replica": "M1", "current": ib, "kind": "cascode"}, "VB3": {"replica": "M2", "current": ib}}; load = {"CL": 100e-15}
        specs = {"gain_lf": {"min": 30.0}, "f3db": {"min": 1e5}}
    elif cid == "C12":
        S = {"M1": M(pdk, 4, 2), "M2": M(pdk, 8, 2)}; bias = {}; load = {"CL": 100e-15}
        specs = {"gain_lf": {"min": 15.0}, "f3db": {"min": 1e6}}
    elif cid == "C07":
        S = {"M1": M(pdk, 8, 2), "M2": M(pdk, 8, 2), "M3": M(pdk, 8, 2), "M4": M(pdk, 8, 2)}
        bias = {"VB1": {"replica": "M3", "current": ib}, "IB1": {"i": 2 * ib, "from": "VSS"}}; load = {"vcm": vcm, "CL": 100e-15, "vocm": vdd / 2}
        specs = {"gain_lf": {"min": 20.0}, "f3db": {"min": 1e5}}
    elif cid == "C08":
        lm = 3 if pdk == "ihp130" else 2
        S = {"M1": M(pdk, 8, lm), "M2": M(pdk, 8, lm), "M3": M(pdk, 8, lm), "M4": M(pdk, 4, lm), "M5": M(pdk, 4, lm)}
        bias = {"VB1": {"replica": "M3", "current": 2 * ib}}; load = {"vcm": vcm, "CL": 1e-12, "inv_input": "VIN2"}
        specs = {"gain_lf": {"min": 25.0}, "ugf": {"min": 5e6}}
    elif cid == "C09":
        lm = 2
        nfp = 32 if pdk in ("sky130", "ihp130") else 8
        S = {k: M(pdk, 16 if pdk != "gf180" else 8, lm) for k in ("M1", "M2", "M3", "M4")}
        S.update({k: M(pdk, nfp, lm) for k in ("M5", "M6", "M7", "M8")})
        ib = 10e-6 if pdk in ("sky130", "ihp130") else ib
        # cascode gate = V_T + 2 V_ov (W/4-equivalent replica); input CM keeps the pair in saturation (found by a grid search on the schematic)
        bias = {"VB1": {"replica": "M3", "current": ib, "kind": "cascode"}, "IB1": {"i": 2 * ib, "from": "VSS"}}
        load = {"vcm": {"expr": "v(VB1) - gs(M3) + gs(M1) - 0.1", "currents": {"M3": ib, "M1": ib}}, "CL": 1e-12, "inv_input": "VIN2", "vout_target": 0.45 * vdd}
        specs = {"gain_lf": {"min": 35.0}, "ugf": {"min": 2e6}}
    elif cid == "C10":
        lm = 4 if pdk in ("sky130", "ihp130") else 2
        S = {k: M(pdk, 8, lm) for k in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10")}
        bias = {"VB1": {"replica": "M5", "current": ib, "kind": "cascode3"}, "VB2": {"replica": "M7", "current": ib, "kind": "cascode3"}, "VB3": {"replica": "M9", "current": ib}, "VB4": {"replica": "M3", "current": 2 * ib}, "IB1": {"i": 2 * ib, "from": "VDD"}}; load = {"vcm": vcm, "CL": 500e-15, "cmfb_gain": 20.0, "vocm": vdd / 2}
        specs = {"gain_lf": {"min": 35.0}, "ugf": {"min": 5e6}}
    elif cid == "C18":
        # wide output followers and a 1:1 diode stack keep V_gs,n + V_sg,p below VDD at low V_ov (textbook stage needs headroom)
        S = {"M1": M(pdk, 4, 2), "M2": M(pdk, 8, 2), "M3": M(pdk, 16, 2), "M4": M(pdk, 32, 2), "M5": M(pdk, 32, 2), "M6": M(pdk, 64, 2)}
        bias = {"VB1": {"replica": "M2", "current": ib}}
        load = {"RL": 20e3, "CL": 5e-12, "vamp": 0.02, "vout_target": 0.5 * vdd, "vin_center": 0.3 * vdd, "servo_slope": 200.0, "options": ".option method=gear reltol=1e-3"}
        specs = {"thd_pct": {"max": 3.0}, "iq": {"max": 300e-6}, "f3db": {"min": 5e6}}
    elif cid == "C15":
        rl = {"sky130": 20e3, "gf180": 40e3, "ihp130": 12e3}[pdk]
        S = {"M1": M(pdk, 4, 2), "R1": {"r": rl, "body": "VSS"}}; bias = {}; load = {"CL": 100e-15}
        specs = {"gain_lf": {"min": 8.0}, "f3db": {"min": 1e6}}
    elif cid == "C16":
        rl = {"sky130": 20e3, "gf180": 40e3, "ihp130": 12e3}[pdk]
        S = {"M1": M(pdk, 8, 2), "M2": M(pdk, 8, 2), "R1": {"r": rl, "body": "VSS"}, "R2": {"r": rl, "body": "VSS"}}
        bias = {"IB1": {"i": 2 * ib, "from": "VSS"}}; load = {"vcm": vcm, "CL": 100e-15}
        specs = {"gain_lf": {"min": 8.0}, "f3db": {"min": 1e6}}
    elif cid == "C17":
        rl = {"sky130": 20e3, "gf180": 40e3, "ihp130": 15e3}[pdk]; rs = 2e3 if pdk != "ihp130" else 1e3
        S = {"M1": M(pdk, 8, 2), "M2": M(pdk, 8, 2), "M3": M(pdk, 8, 2), "R1": {"r": rl, "body": "VSS"}, "R2": {"r": rl, "body": "VSS"}, "R3": {"r": rs, "body": "VSS"}, "R4": {"r": rs, "body": "VSS"}}
        bias = {"VB1": {"replica": "M3", "current": 2 * ib}}; load = {"vcm": vcm, "CL": 100e-15}
        specs = {"gain_lf": {"min": 6.0}, "f3db": {"min": 1e6}}
    elif cid == "C11":
        # two-stage Miller OTA (PMOS input pair, NMOS mirror load, NMOS CS second stage with PMOS current source,
        # RC Miller compensation).  IB1 is a current sink into the diode M1; M2/M7 mirror it (2x).  VIN1 is the inverting input.
        lm = 2
        S = {"M1": M(pdk, 4, lm), "M2": M(pdk, 8, lm), "M3": M(pdk, 8, lm), "M4": M(pdk, 8, lm), "M5": M(pdk, 4, lm), "M6": M(pdk, 4, lm),
             "M7": M(pdk, 8, lm), "M8": M(pdk, 8, lm), "R1": {"r": 3000.0, "body": "VSS"}, "C1": {"c": 1e-12}}
        bias = {"IB1": {"i": ib, "from": "VSS"}}
        load = {"vcm": 0.4 * vdd, "CL": 1e-12, "inv_input": "VIN1", "vout_target": 0.5 * vdd}
        specs = {"gain_lf": {"min": 40.0}, "ugf": {"min": 2e6}, "pm": {"min": 45.0}}
    else:
        raise KeyError(cid)
    for k, v in S.items():
        if "r" in v and "w" not in v:
            w, l = resistor_geometry(pdk, v["r"]); v["w"] = w; v["l"] = l
        if "c" in v and "w" not in v:
            w, l = mim_geometry(pdk, v["c"]); v["w"] = w; v["l"] = l; v["model"] = MIM[pdk]["model"]
    return CaseSpec(f"{cid}_{pdk}_nominal", cid, pdk, "nominal", S, {"VDD": vdd, "VSS": 0.0}, bias, load, specs, notes=["first-pass sizing"])
