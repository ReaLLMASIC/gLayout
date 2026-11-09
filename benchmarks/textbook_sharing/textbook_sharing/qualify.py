"""Schematic qualification and specification-freezing rule (fixed before any layout was built).

Input: the schematic pre-simulation of a derived case (PDK device models, PDK resistor/MIM models, disclosed test
auxiliaries).  Output: qualified / not qualified with reasons, and the frozen specification used for EVERY layout of
that case (all modes, all candidates, all methods).  No layout result is ever used here.

Category floors (absolute, per topology) are the floors in nominal.nominal() plus the class-AB floors in
FLOOR_OVERRIDES.  A schematic that misses a floor is NOT qualified (the specification is never
relaxed to the schematic value).

Frozen spec per metric (sim = schematic value):
  gain_lf (dB, min) ........ spec_min = max(floor, sim - 3 dB)
  ugf, f3db (Hz, min) ...... spec_min = max(floor, 0.6 * sim)
  gain_at_nom (V/V, min) ... spec_min = max(floor, sim - 0.05)
  out_swing (V, min) ....... spec_min = max(floor, 0.8 * sim)
  pm (deg, min) ............ spec_min = floor
  thd_pct, iq (max) ........ spec_max = floor
  vmin (V, max) ............ spec_max = min(floor, sim + 0.1 V)
  err (abs_max) ............ spec_abs_max = floor
Universal operating-point checks (qualification only):
  * simulator status passed, every floor metric present;
  * servo-based tests (single, ota, twostage, buffer_ab): |vout0 - target| <= 0.02 VDD (servo converged);
  * mirrors: compliance vmin found and test point vout_test = round((vmin + VDD)/2, 2 decimals) inside (vmin, VDD).
"""
from __future__ import annotations
import math

FLOOR_OVERRIDES = {
    # class-AB output stage (see testbench.tb_buffer_ab): linear output range and quiescent current
    # are the defining figures of an output stage; distortion is kept at a fixed output amplitude.
    # out_swing floor: the follower pair limits the linear output range to about VDD - |V_GS5| - |V_SG6| - V_dsat1 - V_dsat2
    # with body-effect-raised thresholds (bodies tied to the rails as in the source netlist); 0.25 VDD is the floor
    # (0.4 VDD would exceed that headroom bound at every supply; the floor was set before any layout existed).
    "C18": {"thd_pct": {"max": 3.0}, "iq": {"max": 300e-6}, "f3db": {"min": 5e6}, "out_swing": {"min_frac_vdd": 0.25}},
}
SERVO_CATEGORIES = ("single", "ota", "twostage", "buffer_ab")


def floors_for(cid, nominal_specs, vdd):
    fl = {}
    for m, sp in nominal_specs.items():
        if m.startswith("_") or not isinstance(sp, dict): continue
        fl[m] = dict(sp)
    for m, sp in FLOOR_OVERRIDES.get(cid, {}).items():
        sp = dict(sp)
        if "min_frac_vdd" in sp: sp = {"min": round(sp.pop("min_frac_vdd") * vdd, 4)}
        fl[m] = sp
    return fl


def _bad(v):
    return v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def qualify_and_freeze(category, floors, meas, sim_status, vdd, target=None):
    reasons = []; spec = {}
    if sim_status != "passed":
        reasons.append(f"schematic simulation status {sim_status}")
    if category in SERVO_CATEGORIES and target is not None:
        v0 = meas.get("vout0")
        if _bad(v0) or abs(v0 - target) > 0.02 * vdd:
            reasons.append(f"servo did not reach the output target: vout0={v0} target={target:g} (tol {0.02 * vdd:.3g} V)")
    for m, fl in floors.items():
        sim = meas.get(m)
        if _bad(sim):
            reasons.append(f"{m}: not measurable in the schematic"); continue
        if "min" in fl:
            if sim < fl["min"]: reasons.append(f"{m}={sim:.4g} below floor {fl['min']:g}")
            if m == "gain_lf": smin = max(fl["min"], sim - 3.0)
            elif m in ("ugf", "f3db"): smin = max(fl["min"], 0.6 * sim)
            elif m == "gain_at_nom": smin = max(fl["min"], sim - 0.05)
            elif m == "out_swing": smin = max(fl["min"], 0.8 * sim)
            else: smin = fl["min"]
            spec[m] = {"min": float(f"{smin:.4g}")}
        if "max" in fl:
            if sim > fl["max"]: reasons.append(f"{m}={sim:.4g} above floor {fl['max']:g}")
            smax = min(fl["max"], sim + 0.1) if m == "vmin" else fl["max"]
            spec[m] = {"max": float(f"{smax:.4g}")}
        if "abs_max" in fl:
            if abs(sim) > fl["abs_max"]: reasons.append(f"|{m}|={abs(sim):.4g} above floor {fl['abs_max']:g}")
            spec[m] = {"abs_max": fl["abs_max"]}
    spec["_frozen_from"] = {"schematic": {m: meas.get(m) for m in floors}, "floors": floors, "rule": "textbook_sharing.qualify v1"}
    return {"qualified": not reasons, "reasons": reasons, "spec": spec}


def mirror_test_point(vmin, vdd):
    if _bad(vmin) or vmin >= vdd - 0.02:
        return None
    return round((vmin + vdd) / 2, 2)
