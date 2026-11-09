"""PVT robustness of declared configurations (post-layout, extracted netlists unchanged; interconnect R/C at nominal).
Conditions (device corner, temperature, supply):  TT 27 C VDD | SS 27 C VDD | FF 27 C VDD | SS 85 C 0.9 VDD | FF -40 C 1.1 VDD.
Layouts per (topology, PDK) at the nominal size sW1_sL1 of the selection topologies: the formal reference (independent),
the named combined mode (main grid), and the best feasible candidate of the selection catalogue ("best of the evaluated
set").  Every layout is checked against the case's frozen NOMINAL specifications under every condition (no re-freezing);
this measures how often sharing adds or removes failures relative to the reference, not corner sign-off.
No Monte Carlo is run (no mismatch statistics are claimed).
usage: python -m textbook_sharing.analysis.pvt --jobs 16 --out <results>/analysis/pvt.json"""
from __future__ import annotations
import json, glob, copy, re, argparse, collections
from pathlib import Path
from multiprocessing import Pool
from textbook_sharing import paths
CONDITIONS = [("TT_27C_VDD", "tt", 27, 1.0), ("SS_27C_VDD", "ss", 27, 1.0), ("FF_27C_VDD", "ff", 27, 1.0),
              ("SS_85C_0.9VDD", "ss", 85, 0.9), ("FF_m40C_1.1VDD", "ff", -40, 1.1)]
SIZE = "sW1_sL1"


def targets():
    from textbook_sharing.grid import SELECTION_TOPOLOGIES
    out = []
    for cid in SELECTION_TOPOLOGIES:
        for pdk in ("sky130", "gf180", "ihp130"):
            g = paths.GRID_RUNS / cid / pdk / SIZE
            ind = g / "independent/result.json"
            if not ind.exists() or json.load(open(ind)).get("primary_status") != "auto_passed": continue
            out.append((f"{cid}_{pdk}", "reference", str(ind)))
            comb = g / "combined/result.json"
            if comb.exists() and json.load(open(comb)).get("primary_status") == "auto_passed": out.append((f"{cid}_{pdk}", "combined", str(comb)))
            td = paths.SELECTION_RUNS / f"{cid}_{pdk}_{SIZE}"
            feas = []
            for rp in glob.glob(str(td / "*/result.json")):
                r = json.load(open(rp))
                if r.get("primary_status") == "auto_passed" and r.get("area_um2"): feas.append((r["area_um2"], rp))
            if feas: out.append((f"{cid}_{pdk}", "best_evaluated", sorted(feas)[0][1]))
    return out


def job(args):
    key, role, rp, cond = args
    from textbook_sharing.run_case import load_case_dir
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.testbench import make_testbench
    from textbook_sharing.testbench import check_specs, derived
    from textbook_sharing.verify.pex_sim import simulate, read_measures
    name, corner, temp, vs = cond
    r = json.load(open(rp)); od = Path(rp).parent
    pexsp = next((od / "verify" / "pex").glob("*_pex.spice"))
    top = re.search(r"^\.subckt\s+(\S+)", pexsp.read_text(), re.M | re.I).group(1)
    case, cj = load_case_dir(r["case_dir"]); case = copy.deepcopy(case)
    case.supply = {k: (v * vs if k == "VDD" else v) for k, v in case.supply.items()}
    tb = make_testbench(CIRCUITS[case.circuit_id], top, str(pexsp), case, case.pdk)
    tb = f".temp {temp}\n" + tb
    out = paths.PVT_RUNS / key / role / name
    s = simulate(case.pdk, tb, out, name="tb", corner=corner)
    meas = derived(read_measures(Path(s["out"]).read_text(errors="replace"))) if Path(s["out"]).exists() else {}
    sp = check_specs(meas, case.specs)
    st = s["status"] if s["status"] != "passed" else sp["status"]
    return {"key": key, "role": role, "condition": name, "status": st, "measures": meas, "spec": sp.get("details"), "result": rp, "geometry_hash": r.get("geometry_hash"),
            "area_um2": r.get("area_um2")}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--jobs", type=int, default=16); ap.add_argument("--out", required=True); a = ap.parse_args()
    T = targets(); jobs = [(k, role, rp, c) for k, role, rp in T for c in CONDITIONS]
    print("layouts", len(T), "simulations", len(jobs), flush=True)
    with Pool(a.jobs) as pool: rows = pool.map(job, jobs, chunksize=1)
    by = collections.defaultdict(dict)
    for x in rows: by[(x["key"], x["condition"])][x["role"]] = x["status"] == "passed"
    comp = {}
    for role in ("combined", "best_evaluated"):
        c = collections.Counter()
        for (k, cond), d in by.items():
            if role not in d or "reference" not in d: continue
            ref, sh = d["reference"], d[role]
            c["co_pass" if ref and sh else "co_fail" if (not ref and not sh) else "sharing_added_failure" if ref else "sharing_removed_failure"] += 1
        comp[role] = dict(c)
    json.dump({"conditions": CONDITIONS, "targets": T, "rows": rows, "comparison_vs_reference": comp,
               "note": "interconnect R/C extracted at nominal; device corners only; frozen nominal specs; no Monte Carlo"}, open(a.out, "w"), indent=1, default=str)
    print(json.dumps(comp, indent=1))


if __name__ == "__main__":
    main()
