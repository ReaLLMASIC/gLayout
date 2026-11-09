"""Freeze the fixed-mode order for the 'fixed_mode' strategy from DEVELOPMENT-size main-grid results only.
Declared rule (written before reading the results): for each sharing mode m, over the development cases where both m and
independent passed every automatic stage, take the mean of (A_m / A_independent - 1); order the modes by that mean
ascending (ties: higher pass rate first); 'independent' is always last.  Output: data/frozen/fixed_order.json
(never overwritten).  usage: python -m textbook_sharing.selection.fixed_order --sizes sW1_sL1,sW1_sL1.5"""
import json, glob, argparse, statistics
from pathlib import Path
from textbook_sharing import paths
MODES = ("diffusion_only", "gate_only", "combined")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sizes", required=True); a = ap.parse_args()
    sizes = a.sizes.split(","); out = paths.FROZEN / "fixed_order.json"
    if out.exists(): raise SystemExit(f"{out} exists; never overwritten")
    stat = {m: {"applicable": 0, "passed": 0, "rel": []} for m in MODES}
    for ind in sorted(glob.glob(str(paths.GRID_RUNS / "*/*/*/independent/result.json"))):
        if Path(ind).parts[-3] not in sizes: continue
        b = json.load(open(ind))
        for m in MODES:
            f = Path(ind).parent.parent / m / "result.json"
            if not f.exists(): continue
            r = json.load(open(f))
            if r.get("primary_status") == "NA": continue
            stat[m]["applicable"] += 1
            if r.get("primary_status") == "auto_passed": stat[m]["passed"] += 1
            if r.get("primary_status") == "auto_passed" and b.get("primary_status") == "auto_passed":
                stat[m]["rel"].append(r["area_um2"] / b["area_um2"] - 1)
    rows = {m: {"applicable": s["applicable"], "passed": s["passed"], "pass_rate": s["passed"] / s["applicable"] if s["applicable"] else 0,
                "n_paired": len(s["rel"]), "mean_rel_area": statistics.mean(s["rel"]) if s["rel"] else 0.0} for m, s in stat.items()}
    order = sorted(MODES, key=lambda m: (rows[m]["mean_rel_area"], -rows[m]["pass_rate"])) + ["independent"]
    rule = __doc__.split("  Output:")[0].strip()
    json.dump({"order": order, "per_mode": rows, "sizes": sizes, "rule": rule}, open(out, "w"), indent=1)
    print(json.dumps({"order": order, "per_mode": rows}, indent=1))


if __name__ == "__main__":
    main()
