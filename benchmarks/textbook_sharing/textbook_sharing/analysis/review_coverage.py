"""Visual-review coverage of the reported layouts.

Effective verdict of a layout: the reviewer's verdict, where a 'suspicious' or 'fail' verdict counts as passed only when
it was resolved by objective checks (visual_resolution.outcome == 'resolved_ok').  Verdicts are taken over the
cell-name-independent geometry group, so a verdict reused from an identical layout counts.
Checked sets: every main-grid layout; the reported set (the best passing proposal of every model session, the best
passing plan and the named-mode plans of every selection task); the PVT targets; optional extra run folders.
usage: python -m textbook_sharing.analysis.review_coverage [--extra <file with run folders>] --out <results>/analysis/review_coverage.json"""
import json, glob, argparse, collections
from pathlib import Path
from textbook_sharing.review.visual_review import groups, ROOTS
from textbook_sharing import paths


def eff(rec):
    v = rec["visual"]["verdict"]
    if v in ("suspicious", "fail"):
        o = rec.get("visual_resolution", {}).get("outcome")
        return "pass" if o == "resolved_ok" else ("confirmed_issue" if o else "unresolved_" + v)
    return v


def reported_set():
    """Run folders of the layouts that are reported: best passing proposal per model session, best passing plan and
    named-mode plans per selection task."""
    out = []
    for sd in glob.glob(str(paths.MODEL_RUNS / "*" / "*" / "r*")):
        best = None
        for f in glob.glob(sd + "/p*_report.json"):
            r = json.load(open(f))
            if r.get("status") == "evaluated" and not r.get("duplicate_of") and r["run"]["primary_status"] == "auto_passed" and r["run"].get("area_um2"):
                k = int(Path(f).name[1:].split("_")[0])
                if best is None or r["run"]["area_um2"] < best[0]: best = (r["run"]["area_um2"], f"{sd}/p{k}_run")
        if best: out.append(best[1])
    for cat_f in glob.glob(str(paths.SELECTION_RUNS / "*" / "catalogue.json")):
        td = Path(cat_f).parent; cat = json.load(open(cat_f)); feas = []
        for cid, e in cat["entries"].items():
            rp = td / cid / "result.json"
            if not rp.exists(): continue
            r = json.load(open(rp))
            if any(l.startswith("named:") for l in e.get("labels", [])): out.append(str(td / cid))
            if r.get("primary_status") == "auto_passed" and r.get("area_um2"): feas.append((r["area_um2"], str(td / cid)))
        if feas: out.append(min(feas)[1])
    return sorted({str(Path(x).resolve()) for x in out})


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--extra", default=None); ap.add_argument("--out", default=str(paths.ANALYSIS / "review_coverage.json")); a = ap.parse_args()
    g = groups(ROOTS); by_dir = {}
    for k, recs in g.items():
        es = {eff(r) for _, r in recs}
        ge = "pass" if "pass" in es and not (es & {"confirmed_issue", "unresolved_suspicious", "unresolved_fail"}) else sorted(es)[0]
        for rp, r in recs:
            by_dir[str(Path(rp).parent.parent.parent.resolve())] = (ge, eff(r))
    grid_root = str(paths.GRID_RUNS.resolve()) + "/"
    sets = {"main_grid": sorted(d for d in by_dir if d.startswith(grid_root)), "reported": reported_set()}
    pv = paths.ANALYSIS / "pvt.json"
    if pv.exists():
        sets["pvt_targets"] = sorted({str(paths.resolve(t[2]).parent.resolve()) for t in json.load(open(pv))["targets"]})
    if a.extra:
        sets["extra"] = sorted({str(paths.resolve(l.strip()).resolve()) for l in open(a.extra) if l.strip()})
    out = {}
    for name, dirs in sets.items():
        c = collections.Counter(); bad = []
        for d in dirs:
            ge = by_dir.get(d, ("no_record", None))[0]; c[ge] += 1
            if ge != "pass": bad.append([paths.rel(d), ge])
        out[name] = {"n": len(dirs), "group_effective": dict(c), "not_pass": bad[:50]}
    out["all_records_effective"] = dict(collections.Counter(v[1] for v in by_dir.values()))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps({k: (v if k == "all_records_effective" else {"n": v["n"], "eff": v["group_effective"]}) for k, v in out.items()}, indent=1))


if __name__ == "__main__":
    main()
