"""Rebuild the geometry of every recorded layout with this code (geometry only, no verification) and compare the
cell-name-independent geometry hash and the bounding box with the record.  This needs only Python and KLayout, so it is
a quick check that the recorded runs and the code in this repository describe the same layouts.
usage: python -m textbook_sharing.analysis.geometry_check [--roots grid,selection,models] [--jobs 16] --out <json>"""
import argparse, glob, json, tempfile, collections
from multiprocessing import Pool
from pathlib import Path
from textbook_sharing import paths


def records(roots):
    out = []
    for root in roots:
        for f in sorted(glob.glob(str(paths.RUNS / root / "**" / "result.json"), recursive=True)):
            if "/verify/" in f: continue
            r = json.load(open(f))
            if r.get("geometry_hash") and r.get("applied_plans"):
                out.append(f)
    return out


def check(job):
    i, f = job
    from textbook_sharing.layout import build
    from textbook_sharing.run_case import load_case_dir
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.pdk import pdk_obj
    from textbook_sharing.analysis.ledger import geometry_hash
    r = json.load(open(f)); case, _ = load_case_dir(r["case_dir"])
    plans = {str(p["group"]): p["plan"] for p in r["applied_plans"]}
    try:
        b = build(pdk_obj(case.pdk), CIRCUITS[case.circuit_id], case.sizing, name=f"chk{i}", plans=plans)
        with tempfile.TemporaryDirectory() as td:
            g = Path(td) / "chk.gds"; b["component"].write_gds(str(g)); h = geometry_hash(str(g))
        st = b["assembly_stats"]
        return {"record": paths.rel(Path(f).parent), "hash_match": h == r["geometry_hash"],
                "bbox_match": (round(st["width"], 4), round(st["height"], 4)) == (round(r["assembly_stats"]["width"], 4), round(r["assembly_stats"]["height"], 4)),
                "hash": h, "recorded_hash": r["geometry_hash"]}
    except Exception as e:
        return {"record": paths.rel(Path(f).parent), "error": repr(e)[:300]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--roots", default="grid,selection,models"); ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--out", required=True); a = ap.parse_args()
    fs = records(a.roots.split(","))
    res = []
    with Pool(a.jobs, maxtasksperchild=200) as pool:
        for x in pool.imap_unordered(check, enumerate(fs), chunksize=4):
            res.append(x)
            if len(res) % 200 == 0 or len(res) == len(fs):
                print(f"{len(res)}/{len(fs)} rebuilt, {sum(1 for y in res if not y.get('hash_match'))} not matching", flush=True)
    res.sort(key=lambda x: x["record"])
    by_root = collections.defaultdict(collections.Counter)
    for x in res:
        root = x["record"].split("/")[1]
        by_root[root]["records"] += 1
        by_root[root]["error" if "error" in x else ("hash_match" if x["hash_match"] else ("bbox_match_only" if x["bbox_match"] else "differs"))] += 1
    out = {"summary": {k: dict(v) for k, v in by_root.items()}, "not_matching": [x for x in res if not x.get("hash_match")]}
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps(out["summary"], indent=1))


if __name__ == "__main__":
    main()
