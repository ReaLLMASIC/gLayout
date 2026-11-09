"""Main grid: every qualified case x the four named modes (independent, diffusion_only, gate_only, combined).
usage: python -m textbook_sharing.run_grid [--out <runs>/grid] [--sizes sW1_sL1,sW1_sL1.5] [--circuits ..] [--pdks ..] [--jobs 12]
Resumable: a run whose result.json exists is skipped.  The development size points (used to freeze the cost rule and
the fixed mode order before anything else was measured) are sW1_sL1 and sW1_sL1.5; the other ten are held out."""
from __future__ import annotations
import json, argparse, glob
from pathlib import Path
from multiprocessing import Pool
from textbook_sharing import paths
MODES = ("independent", "diffusion_only", "gate_only", "combined")
DEV_SIZES = ("sW1_sL1", "sW1_sL1.5")


def qualified_cases(circuits=None, pdks=None, sizes=None):
    out = []
    for q in sorted(glob.glob(str(paths.CASES / "*/*/*/qualification.json"))):
        r = json.load(open(q))
        if r.get("stage") != "qualified": continue
        if circuits and r["circuit_id"] not in circuits: continue
        if pdks and r["pdk"] not in pdks: continue
        if sizes and r["size"] not in sizes: continue
        out.append(Path(q).parent)
    return out


def job(args):
    cdir, mode, out_root = args
    from textbook_sharing.run_case import run
    cj = json.load(open(Path(cdir) / "case.json"))
    od = Path(out_root) / cj["circuit_id"] / cj["pdk"] / cj["size"] / mode
    if (od / "result.json").exists():
        return json.load(open(od / "result.json")).get("primary_status")
    nom = json.load(open(paths.CASES / cj["circuit_id"] / cj["pdk"] / "sW1_sL1" / "case.json"))["sizing"] \
        if (paths.CASES / cj["circuit_id"] / cj["pdk"] / "sW1_sL1" / "case.json").exists() else cj["sizing"]
    r = run(cdir, od, mode=mode, label=mode, context={"experiment": "main_grid", "size": cj["size"], "mode": mode}, nominal_sizing=nom)
    print(cj["case_id"], mode, r.get("primary_status"), r.get("area_um2"), r.get("timing_s", {}).get("end_to_end"), flush=True)
    return r.get("primary_status")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=str(paths.GRID_RUNS)); ap.add_argument("--sizes", default=None)
    ap.add_argument("--circuits", default=None); ap.add_argument("--pdks", default=None); ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--modes", default=",".join(MODES))
    a = ap.parse_args()
    cases = qualified_cases(a.circuits.split(",") if a.circuits else None, a.pdks.split(",") if a.pdks else None, a.sizes.split(",") if a.sizes else None)
    jobs = [(str(c), m, a.out) for c in cases for m in a.modes.split(",")]
    print("cases", len(cases), "jobs", len(jobs), flush=True)
    with Pool(a.jobs, maxtasksperchild=4) as pool:
        st = pool.map(job, jobs, chunksize=1)
    import collections
    print(dict(collections.Counter(st)))


if __name__ == "__main__":
    main()
