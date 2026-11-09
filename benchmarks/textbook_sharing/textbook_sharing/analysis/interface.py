"""Interface comparison (same model, same settings, same tasks): sharing interface (main-experiment sessions) vs the
base-gLayout capability interface (fet_row).  Also capability coverage: on each task, the best feasible candidate of the
selection catalogue among plans the base interface can express (no cross-device diffusion node, no shared gate
conductor) vs the overall best.
usage: python -m textbook_sharing.analysis.interface --out <results>/analysis/llm_interface.json"""
import json, glob, argparse, statistics
from pathlib import Path
from textbook_sharing import paths
ARMS = {"sharing": "openai_gpt-6.1-sol", "base": "openai_gpt-6.1-sol_baseiface"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
    from textbook_sharing.analysis.models import session_rows, ref_area, best_evaluated
    from textbook_sharing.selection.strategies import share_score
    tasks = sorted({Path(d).name for d in glob.glob(str(paths.MODEL_RUNS / ARMS["base"] / "*"))})
    rows = {}; summ = {}
    for arm, tag in ARMS.items():
        rs = []
        for t in tasks:
            for sd in sorted(glob.glob(str(paths.MODEL_RUNS / tag / t / "r*"))):
                sess, done, reps = session_rows(sd)
                if not reps: continue
                feas = [r["run"]["area_um2"] for r in reps if r["status"] == "evaluated" and r["run"]["primary_status"] == "auto_passed" and r["run"].get("area_um2")]
                b = min(feas) if feas else None; ra = ref_area(t); be, _ = best_evaluated(t)
                rs.append({"task": t, "rep": Path(sd).name, "proposals": len(reps), "first_legal": reps[0]["status"] == "evaluated",
                           "best": b, "vs_reference": (b / ra - 1) if b and ra else None, "vs_best_evaluated": (b / be - 1) if b and be else None})
        rows[arm] = rs
        ok = [r for r in rs if r["vs_best_evaluated"] is not None]
        summ[arm] = {"sessions": len(rs), "tasks": len({r["task"] for r in rs}), "first_legal_rate": statistics.mean(r["first_legal"] for r in rs) if rs else None,
                     "gap8": statistics.mean(r["vs_best_evaluated"] for r in ok) if ok else None,
                     "ref8": statistics.mean(r["vs_reference"] for r in ok if r["vs_reference"] is not None) if ok else None}
    cov = {}
    for t in tasks:
        td = paths.SELECTION_RUNS / t
        if not (td / "catalogue.json").exists(): continue
        cat = json.load(open(td / "catalogue.json")); allf = []; basef = []
        for c in cat["entries"]:
            rp = td / c / "result.json"
            if not rp.exists(): continue
            r = json.load(open(rp))
            if r.get("primary_status") == "auto_passed" and r.get("area_um2"):
                allf.append(r["area_um2"])
                if share_score(cat, c) == 0: basef.append(r["area_um2"])
        cov[t] = {"best_all": min(allf) if allf else None, "best_base_expressible": min(basef) if basef else None,
                  "base_gap": (min(basef) / min(allf) - 1) if allf and basef else None}
    gaps = [v["base_gap"] for v in cov.values() if v["base_gap"] is not None]
    summ["capability"] = {"tasks": len(cov), "mean_gap_of_best_base_expressible_candidate": statistics.mean(gaps) if gaps else None,
                          "note": "base-expressible = catalogue candidates with no cross-device diffusion join and no shared gate conductor"}
    json.dump({"summary": summ, "rows": rows, "coverage": cov, "tasks": tasks}, open(a.out, "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
