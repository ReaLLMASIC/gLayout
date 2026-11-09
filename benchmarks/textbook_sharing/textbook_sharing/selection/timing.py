"""Controlled timing pass for the selection comparison.  The per-candidate wall times recorded during the evaluation were
measured on a shared, heavily loaded machine (median geometry generation 0.18 s, but 53 of 3404 records > 100 s caused by
stalls).  Here every candidate's geometry (and each task's cost-rule baseline) is rebuilt ONE AT A TIME in a single
process and timed; the load average is recorded.  The replay charges these geometry times, and for full verifications
the per-task median of the recorded end-to-end times (the same charge for every method).
usage: python -m textbook_sharing.selection.timing --out <results>/analysis/timing_controlled.json"""
import os, json, time, glob, argparse, statistics, tempfile
from multiprocessing import Pool
from pathlib import Path
from textbook_sharing import paths


def one_task(td):
    from textbook_sharing.run_case import load_case_dir, pdk_obj
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.layout import build, device_specs, sharing_groups
    from glayout.sharing import SharingPlan, rules_for
    from textbook_sharing.selection import cost
    td = Path(td); outf = paths.ANALYSIS / "timing_controlled_parts" / f"{td.name}.json"
    if outf.exists(): return td.name, "kept"
    cat = json.load(open(td / "catalogue.json"))
    anyres = next(td.glob("*/result.json")); case_dir = json.load(open(anyres))["case_dir"]
    case, cj = load_case_dir(case_dir); circ = CIRCUITS[case.circuit_id]; pdk = pdk_obj(case.pdk); R = rules_for(pdk)
    groups = sharing_groups(device_specs(circ, case.sizing)); tmp = Path(tempfile.mkdtemp())
    rec = {"geometry_s": {}, "load_start": os.getloadavg()}
    t0 = time.perf_counter(); base = build(pdk, circ, case.sizing, mode="independent", name=f"tb_{td.name}".replace(".", "p")); base["component"].write_gds(str(tmp / "b.gds"))
    rec["baseline_geometry_s"] = round(time.perf_counter() - t0, 4)
    bp = [SharingPlan.from_json(x["plan"]) for x in base["applied_plans"]]; bd = [cost.group_dims(R, g, p) for g, p in zip(groups, bp)]
    kinds = [r["kind"] for r in base["assembly_stats"]["row_dims"]]; grow = [kinds.index("n" if g[0].model_role == "nfet" else "p") for g in groups]
    t1 = time.perf_counter()
    for cid, e in cat["entries"].items():
        plans = [SharingPlan.from_json(cat["tables"][gi]["plans"][pid]) for gi, pid in enumerate(e["plan_ids"])]
        cost.estimate(R, groups, plans, bd, base["assembly_stats"], grow, base_plans=bp)
    rec["cost_estimates_total_s"] = round(time.perf_counter() - t1, 4)
    for n, (cid, e) in enumerate(cat["entries"].items()):
        plans = {str(gi): cat["tables"][gi]["plans"][pid] for gi, pid in enumerate(e["plan_ids"])}
        t2 = time.perf_counter()
        r = build(pdk, circ, case.sizing, name=f"t{n}_{cid}", plans=plans); r["component"].write_gds(str(tmp / "c.gds"))
        rec["geometry_s"][cid] = round(time.perf_counter() - t2, 4)
    e2e = [json.load(open(p)).get("timing_s", {}).get("end_to_end") for p in td.glob("*/result.json")]
    e2e = [x for x in e2e if x]
    rec["verification_median_s"] = statistics.median(e2e) if e2e else None
    rec["load_end"] = os.getloadavg()
    outf.parent.mkdir(parents=True, exist_ok=True); json.dump(rec, open(outf, "w"), indent=1)
    return td.name, round(sum(rec["geometry_s"].values()), 2)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--jobs", type=int, default=10); a = ap.parse_args()
    tds = [str(Path(t).parent) for t in sorted(glob.glob(str(paths.SELECTION_RUNS / "*/catalogue.json")))]
    with Pool(a.jobs, maxtasksperchild=1) as pool:
        for name, st in pool.imap_unordered(one_task, tds): print(name, st, flush=True)
    parts = {Path(f).stem: json.load(open(f)) for f in glob.glob(str(paths.ANALYSIS / "timing_controlled_parts/*.json"))}
    json.dump({"note": "each task in its own process, candidates built one at a time; up to --jobs tasks in parallel", "jobs": a.jobs, "tasks": parts},
              open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
