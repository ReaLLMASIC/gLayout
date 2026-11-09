"""Build the requested case set (18 topologies x 3 PDKs x 12 size points = 648 requests).

For every request: derive sizes (grid.derive_sizing) -> parameter-illegal? -> duplicate signature? -> schematic
pre-simulation (mirrors: pass 1 finds the compliance voltage, the test point is frozen, pass 2 measures at it) ->
qualification + frozen spec (qualify.py) -> case directory data/cases/<C>/<pdk>/<sW.._sL..>/.
The nominal design point of every topology and PDK is read from data/nominal/<C>/<pdk>.json.  Every request (including
illegal ones) is recorded in <results>/case_build.json, which the count ledger reads.
No layout is built here.  usage: python -m textbook_sharing.build_cases [--circuits C01,..] [--pdks ..] [--jobs 12]
"""
from __future__ import annotations
import json, copy, time, argparse, hashlib
from pathlib import Path
from multiprocessing import Pool

from textbook_sharing.circuits import CIRCUITS, ORDER
from textbook_sharing.cases import CaseSpec, PDK_POINT
from textbook_sharing.nominal import nominal
from textbook_sharing.presim import presim
from textbook_sharing.testbench import CATEGORY, make_testbench
from textbook_sharing.netlist import emit_subckt
from textbook_sharing.grid import GRID, size_tag, derive_sizing, signature
TB_RULE = hashlib.sha256(open(Path(__file__).with_name("testbench.py"), "rb").read()).hexdigest()[:16]   # identity of the testbench generator
from textbook_sharing.qualify import floors_for, qualify_and_freeze, mirror_test_point
from textbook_sharing import overrides
from textbook_sharing import paths

OUT = paths.CASES
PDKS = ["sky130", "gf180", "ihp130"]


def nominal_point(cid, pdk):
    """Nominal design point (sizing, supply, bias, load, notes) of a topology and PDK."""
    return json.load(open(paths.NOMINAL / cid / f"{pdk}.json"))


def target_of(category, case, vdd):
    if category in ("single",): return None     # servo sets V_in = V_out; no separate target
    if category in ("ota", "twostage"): return case.load.get("vout_target", vdd / 2)
    if category == "buffer_ab": return case.load.get("vout_target", vdd / 2)
    return None


def build_one(job):
    cid, pdk = job
    circ = CIRCUITS[cid]; cat = CATEGORY[cid]; vdd = PDK_POINT[pdk]["vdd"]
    c0 = nominal_point(cid, pdk); nom = nominal(cid, pdk)
    base_sizing, base_bias, base_load, ov_notes = overrides.apply(cid, pdk, c0["sizing"], c0["bias"], c0["load"])
    floors = floors_for(cid, nom.specs, vdd)
    results = []; seen = {}
    for sw, sl in GRID:
        tag = size_tag(sw, sl)
        rec = {"case_id": f"{cid}_{pdk}_{tag}", "circuit_id": cid, "pdk": pdk, "size": tag, "sW": sw, "sL": sl, "category": cat}
        sizing, drec = derive_sizing(base_sizing, pdk, sw, sl)
        rec["derivation"] = drec
        if sizing is None:
            rec["stage"] = "parameter_illegal"; results.append(rec); continue
        sig = signature(circ, pdk, sizing); rec["signature"] = sig
        if sig in seen:
            rec["stage"] = "duplicate"; rec["duplicate_of"] = seen[sig]; results.append(rec); continue
        seen[sig] = rec["case_id"]
        d = OUT / cid / pdk / tag
        if (d / "qualification.json").exists() and (d / "manifest.json").exists():
            old = json.load(open(d / "qualification.json"))           # resume: this request was completed earlier
            if old.get("signature") == sig and old.get("testbench_rule") == TB_RULE:
                results.append(old); continue
        case = CaseSpec(rec["case_id"], cid, pdk, tag, sizing, dict(c0["supply"]), copy.deepcopy(base_bias), copy.deepcopy(base_load), {}, list(c0.get("notes", [])) + ov_notes)
        d = OUT / cid / pdk / tag; d.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        if cat == "mirror":
            case.load["vout_test"] = case.load.get("vout_nom", vdd / 2)
            p1 = presim(pdk, circ, case, d / "presim_pass1", dut_name=rec["case_id"])
            vt = mirror_test_point(p1["measures"].get("vmin"), vdd)
            rec["mirror_pass1"] = {"vmin": p1["measures"].get("vmin"), "status": p1["sim"]["status"], "vout_test": vt}
            if vt is None:
                q = {"qualified": False, "reasons": [f"compliance voltage not found in the schematic sweep (vmin={p1['measures'].get('vmin')})"], "spec": {}}
                pre = p1
            else:
                case.load["vout_test"] = vt
                pre = presim(pdk, circ, case, d / "presim", dut_name=rec["case_id"])
                q = qualify_and_freeze(cat, floors, pre["measures"], pre["sim"]["status"], vdd)
        else:
            pre = presim(pdk, circ, case, d / "presim", dut_name=rec["case_id"])
            q = qualify_and_freeze(cat, floors, pre["measures"], pre["sim"]["status"], vdd, target_of(cat, case, vdd))
        case.specs = q["spec"]
        rec.update({"stage": "qualified" if q["qualified"] else "schematic_not_qualified", "qualification": q, "presim_status": pre["sim"]["status"],
                    "presim_errors": pre["sim"].get("errors", [])[:3], "schematic_measures": pre["measures"], "presim_s": round(time.time() - t0, 1)})
        # case files (evaluator side)
        name = rec["case_id"]
        cj = {"case_id": name, "circuit_id": cid, "pdk": pdk, "size": tag, "sW": sw, "sL": sl, "dut_name": name, "ports": circ.ports,
              "sizing": sizing, "supply": case.supply, "bias": case.bias, "load": case.load, "category": cat, "notes": case.notes,
              "derivation": drec, "signature": sig, "testbench_rule": TB_RULE,
              "test_auxiliaries": overrides.test_auxiliaries(cid, case), "core_devices": [x.name for x in circ.devices]}
        json.dump(cj, open(d / "case.json", "w"), indent=1)
        json.dump(case.specs, open(d / "specs.json", "w"), indent=1)
        json.dump({k: v for k, v in rec.items() if k not in ("schematic_measures",)} | {"schematic_measures": pre["measures"]}, open(d / "qualification.json", "w"), indent=1, default=str)
        (d / "target.spice").write_text(emit_subckt(pdk, circ, sizing, name, per_finger=False))
        (d / "target_lvs.spice").write_text(emit_subckt(pdk, circ, sizing, name, per_finger=True, lvs=True))
        (d / "testbench.spice").write_text(make_testbench(circ, name, "DUT_INCLUDE_PATH", case, pdk))
        manifest = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(d.iterdir()) if f.is_file() and f.name != "manifest.json"}
        json.dump(manifest, open(d / "manifest.json", "w"), indent=1)
        results.append(rec)
    return results


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--circuits", default=",".join(ORDER)); ap.add_argument("--pdks", default=",".join(PDKS))
    ap.add_argument("--jobs", type=int, default=12)
    a = ap.parse_args()
    jobs = [(c, p) for c in a.circuits.split(",") for p in a.pdks.split(",")]
    with Pool(a.jobs) as pool:
        allres = [r for rs in pool.map(build_one, jobs) for r in rs]
    OUT.mkdir(parents=True, exist_ok=True)
    out = paths.RESULTS / "case_build.json"; out.parent.mkdir(parents=True, exist_ok=True)
    merged = {r["case_id"]: r for r in (json.load(open(out)) if out.exists() else [])}
    merged.update({r["case_id"]: r for r in allres})          # a partial rebuild replaces only its own requests
    json.dump(sorted(merged.values(), key=lambda r: r["case_id"]), open(out, "w"), indent=1, default=str)
    import collections
    c = collections.Counter(r["stage"] for r in allres)
    print("requests", len(allres), dict(c))
    for r in allres:
        if r["stage"] == "schematic_not_qualified": print("  NQ", r["case_id"], r["qualification"]["reasons"][:3])


if __name__ == "__main__":
    main()
