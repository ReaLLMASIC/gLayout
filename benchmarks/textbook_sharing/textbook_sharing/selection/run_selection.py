"""Plan-selection study: catalogue construction and full evaluation of every catalogue candidate.
Tasks: SELECTION_TOPOLOGIES x 3 PDKs x SELECTION_SIZES (72 requested); a task exists only if its case is qualified.
Per task directory <runs>/selection/<case_id>/:
  catalogue.json  (per-group candidate tables, ledger, entries = candidate id -> per-group plan ids, plans)
  estimates.json  (cost.py estimate of every entry; uses one baseline assembly of the independent plan)
  <cand_id>/result.json  (run_case.run with explicit plans)
usage: python -m textbook_sharing.selection.run_selection [--stage catalogue|evaluate|all] [--jobs 12] [--sizes ..] [--pdks ..] [--topologies ..]"""
from __future__ import annotations
import json, argparse, time
from pathlib import Path
from multiprocessing import Pool
from textbook_sharing.grid import SELECTION_TOPOLOGIES, SELECTION_SIZES, size_tag
from textbook_sharing import paths

OUT = paths.SELECTION_RUNS


def task_dirs(topologies=None, pdks=None, sizes=None):
    tasks = []; excluded = []
    for cid in (topologies or SELECTION_TOPOLOGIES):
        for pdk in (pdks or ["sky130", "gf180", "ihp130"]):
            for sw, sl in SELECTION_SIZES:
                tag = size_tag(sw, sl)
                if sizes and tag not in sizes: continue
                q = paths.CASES / cid / pdk / tag / "qualification.json"
                rec = {"task_id": f"{cid}_{pdk}_{tag}", "case_dir": paths.rel(q.parent)}
                if not q.exists():
                    # parameter-illegal or duplicate requests have no case directory: read the build record
                    rec["excluded"] = "no case directory (parameter-illegal or duplicate request)"; excluded.append(rec); continue
                r = json.load(open(q))
                if r["stage"] != "qualified":
                    rec["excluded"] = "schematic_not_qualified: " + "; ".join(r["qualification"]["reasons"][:3]); excluded.append(rec); continue
                tasks.append(rec)
    return tasks, excluded


def make_catalogue(task):
    from textbook_sharing.run_case import load_case_dir, pdk_obj
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.layout import device_specs, sharing_groups, build
    from textbook_sharing.selection.catalogue import build_catalogue
    from textbook_sharing.selection import cost
    from glayout.sharing import SharingPlan, rules_for
    td = OUT / task["task_id"]; td.mkdir(parents=True, exist_ok=True)
    if (td / "catalogue.json").exists() and (td / "estimates.json").exists():
        return task["task_id"], "kept"
    case, cj = load_case_dir(task["case_dir"]); circ = CIRCUITS[case.circuit_id]; pdk = pdk_obj(case.pdk)
    groups = sharing_groups(device_specs(circ, case.sizing))
    t0 = time.time(); cat = build_catalogue(pdk, groups, task["task_id"]); t_enum = time.time() - t0
    json.dump({**cat, "timing_s": {"enumeration_and_static_checks": round(t_enum, 3)}}, open(td / "catalogue.json", "w"), indent=1, default=str)
    # cost estimates: one baseline assembly (independent plan) + plan-only group formulas
    R = rules_for(pdk)
    t1 = time.time()
    base = build(pdk, circ, case.sizing, mode="independent", name=f"{case.case_id}_costbase".replace(".", "p"))
    t_base = time.time() - t1
    base_plans = [SharingPlan.from_json(ap["plan"]) for ap in base["applied_plans"]]
    base_dims = [cost.group_dims(R, g, p) for g, p in zip(groups, base_plans)]
    kinds = [r["kind"] for r in base["assembly_stats"]["row_dims"]]
    group_row = [kinds.index("n" if g[0].model_role == "nfet" else "p") for g in groups]
    est = {}; t2 = time.time()
    tables = cat["tables"]
    for cid_, e in cat["entries"].items():
        plans = [SharingPlan.from_json(tables[gi]["plans"][pid]) for gi, pid in enumerate(e["plan_ids"])]
        est[cid_] = cost.estimate(R, groups, plans, base_dims, base["assembly_stats"], group_row, base_plans=base_plans)
    t_est = time.time() - t2
    json.dump({"estimates": est, "baseline_area_um2": base["assembly_stats"]["area_um2"], "timing_s": {"baseline_geometry": round(t_base, 3), "estimates_total": round(t_est, 4)},
               "rule": "textbook_sharing.selection.cost v2 (group dims + channel nets)"}, open(td / "estimates.json", "w"), indent=1, default=str)
    return task["task_id"], "built"


def eval_job(args):
    task_id, case_dir, cand_id = args
    from textbook_sharing.run_case import run
    td = OUT / task_id; od = td / cand_id
    if (od / "result.json").exists():
        return json.load(open(od / "result.json")).get("primary_status")
    cat = json.load(open(td / "catalogue.json")); e = cat["entries"][cand_id]
    plans = {str(gi): cat["tables"][gi]["plans"][pid] for gi, pid in enumerate(e["plan_ids"])}
    cj = json.load(open(Path(case_dir) / "case.json"))
    nomp = paths.CASES / cj["circuit_id"] / cj["pdk"] / "sW1_sL1" / "case.json"
    nom = json.load(open(nomp))["sizing"] if nomp.exists() else None
    r = run(case_dir, od, plans=plans, label=cand_id, context={"experiment": "selection", "task": task_id, "candidate": cand_id}, nominal_sizing=nom)
    print(task_id, cand_id, r.get("primary_status"), r.get("area_um2"), flush=True)
    return r.get("primary_status")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--stage", default="all"); ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--sizes", default=None); ap.add_argument("--pdks", default=None); ap.add_argument("--topologies", default=None)
    a = ap.parse_args()
    tasks, excluded = task_dirs(a.topologies.split(",") if a.topologies else None, a.pdks.split(",") if a.pdks else None, a.sizes.split(",") if a.sizes else None)
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump({"tasks": tasks, "excluded": excluded}, open(OUT / f"tasks_{int(time.time())}.json", "w"), indent=1)
    print("tasks", len(tasks), "excluded", len(excluded), flush=True)
    if a.stage in ("catalogue", "all"):
        with Pool(min(a.jobs, 8)) as pool:
            for tid, st in pool.imap_unordered(make_catalogue, tasks): print("catalogue", tid, st, flush=True)
    if a.stage in ("evaluate", "all"):
        jobs = []
        for t in tasks:
            cat = json.load(open(OUT / t["task_id"] / "catalogue.json"))
            jobs += [(t["task_id"], t["case_dir"], c) for c in cat["entries"]]
        print("candidate evaluations", len(jobs), flush=True)
        with Pool(a.jobs, maxtasksperchild=4) as pool:
            st = pool.map(eval_job, jobs, chunksize=1)
        import collections; print(dict(collections.Counter(st)))


if __name__ == "__main__":
    main()
