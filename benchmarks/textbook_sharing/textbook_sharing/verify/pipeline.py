"""Verification pipeline for one layout: DRC -> LVS -> sizing -> PEX -> physical -> render -> review record.

verify_layout(pdk, gds, top, target_lvs_spice, target_devices, ports, out_dir, ...) returns a result dict with
  stages: {drc, drc_magic, lvs, sizing, pex, physical, render}
  primary_status: first failing stage in the fixed order, or 'review_pending' / 'passed'
  fail_reasons: all failing stages
Simulation/spec stages are added by the case runner (they need the testbench).
"""
from __future__ import annotations
import json, time
from pathlib import Path
from .drc import drc_klayout, drc_magic
from .lvs import lvs, sha
from .sizing import sizing_check
from .pex_sim import pex
from .physical import physical_checks
from .record import render_views, make_record
from ..netlist import PDK_MODELS
from .. import paths

ORDER = ["build", "drc", "lvs", "constraints", "pex", "simulation", "spec", "physical_review"]


def verify_layout(pdk, gds, top, target_lvs_spice, target_devices, ports, out_dir, expected_fingers=None, zoom=None, context=None,
                  run_magic_drc=True, run_pex=True, sub_net="VSS"):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    res = {"pdk": pdk, "gds": paths.rel(gds), "top": top, "gds_sha256": sha(gds), "target_sha256": sha(target_lvs_spice), "stages": {}, "fail_reasons": [], "timestamps": {"start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}
    T = res.setdefault("timing_s", {}); _t = [time.time()]
    def lap(k):
        now = time.time(); T[k] = round(T.get(k, 0.0) + now - _t[0], 2); _t[0] = now
    # DRC
    d = drc_klayout(pdk, gds, out_dir / "drc", top=top); res["stages"]["drc"] = d; lap("drc")
    if d["status"] != "passed": res["fail_reasons"].append("drc_failed")
    if run_magic_drc:
        res["stages"]["drc_magic"] = drc_magic(pdk, str(Path(gds).resolve()), top, out_dir / "drc_magic"); lap("drc_magic")
    # LVS
    l = lvs(pdk, str(Path(gds).resolve()), top, str(Path(target_lvs_spice).resolve()), out_dir / "lvs", sub_net=sub_net); res["stages"]["lvs"] = l; lap("lvs")
    if l["status"] != "passed": res["fail_reasons"].append("lvs_failed")
    # sizing from the extracted netlist (magic lvs spice or klayout .cir)
    ex_text = None
    if pdk == "gf180":
        cir = next((out_dir / "lvs" / "klayout_lvs").glob("*.cir"), None) if (out_dir / "lvs" / "klayout_lvs").exists() else None
        ex_text = cir.read_text() if cir else None
    else:
        sp = l.get("extract", {}).get("spice")
        ex_text = Path(sp).read_text() if sp and Path(sp).exists() else None
    if ex_text:
        s = sizing_check(target_devices, ex_text, {k: PDK_MODELS[pdk][k] for k in ("nfet", "pfet")}, ports)
    else:
        s = {"status": "constraints_failed", "error": "no extracted netlist"}
    res["stages"]["constraints"] = s; lap("sizing_check")
    if s["status"] != "passed": res["fail_reasons"].append("constraints_failed")
    # PEX
    if run_pex:
        p = pex(pdk, str(Path(gds).resolve()), top, out_dir / "pex"); res["stages"]["pex"] = p; lap("pex")
        if p["status"] != "passed": res["fail_reasons"].append("pex_failed")
    # physical first tier
    try:
        ph = physical_checks(pdk, gds, top, ports, expected_fingers=expected_fingers)
    except Exception as e:
        ph = {"status": "physical_review_failed", "error": repr(e), "checks": {}, "findings": [repr(e)]}
    res["stages"]["physical"] = ph; lap("geometry_checks")
    if ph["status"] != "passed": res["fail_reasons"].append("physical_review_failed")
    # render + review record
    (out_dir / "review").mkdir(parents=True, exist_ok=True)
    rv = render_views(gds, out_dir / "review" / top, pdk, zoom=zoom, cell=top)
    res["stages"]["render"] = {k: v for k, v in rv.items() if k != "legend"}; lap("render")
    rec = make_record(gds, pdk, res["target_sha256"], ph, {k: v for k, v in res["stages"].items() if k in ("drc", "drc_magic", "lvs", "constraints", "pex")}, rv, context=context)
    (out_dir / "review").mkdir(parents=True, exist_ok=True)
    json.dump(rec, open(out_dir / "review" / "review_record.json", "w"), indent=1)
    res["review_record"] = paths.rel(out_dir / "review" / "review_record.json"); res["review_id"] = rec["review_id"]
    # primary status
    prim = None
    for st in ORDER:
        if st + "_failed" in res["fail_reasons"] or (st == "physical_review" and "physical_review_failed" in res["fail_reasons"]):
            prim = st + "_failed"; break
    res["primary_status"] = prim or "review_pending"
    res["area_um2"] = ph.get("area_um2"); res["bbox_um"] = ph.get("bbox_um")
    res["timestamps"]["end"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); res["wall_s"] = round(time.time() - t0, 2)
    json.dump(res, open(out_dir / "result.json", "w"), indent=1, default=str)
    return res
