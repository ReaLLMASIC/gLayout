"""Aggregate model sessions (<runs>/models/<model_tag>/<task>/r<rep>/).
Per session: proposals made (each counts, incl. rejected and repeated), first proposal legal (passed parse + legality),
EDA verifications actually run (non-duplicate evaluated proposals), statuses, best feasible (auto_passed) area after
k = 1, 2, 4, 8 proposals, its ratio to the task's reference (independent) area and to the best feasible candidate of the
selection catalogue of the same task when that task was evaluated ("best of the evaluated set"), wall time.
Aggregates per model tag: session-level rates, topology-balanced means, and per-task paired comparisons.
usage: python -m textbook_sharing.analysis.models --out <results>/analysis/llm_summary.json [--tags a,b]"""
import json, glob, argparse, statistics, collections
from pathlib import Path
from textbook_sharing import paths
KS = (1, 2, 4, 8)


def session_rows(sd):
    sd = Path(sd); reps = []
    for f in sorted(sd.glob("p*_report.json"), key=lambda p: int(p.name[1:].split("_")[0])):
        reps.append(json.load(open(f)))
    sess = json.load(open(sd / "session.json")) if (sd / "session.json").exists() else {}
    done = json.load(open(sd / "session_done.json")) if (sd / "session_done.json").exists() else {}
    return sess, done, reps


def ref_area(task_id):
    cid, pdk, size = task_id.split("_", 2)
    f = paths.GRID_RUNS / cid / pdk / size / "independent/result.json"
    r = json.load(open(f)) if f.exists() else {}
    return r.get("area_um2") if r.get("primary_status") == "auto_passed" else None


def best_evaluated(task_id):
    td = paths.SELECTION_RUNS / task_id
    if not (td / "catalogue.json").exists(): return None, None
    cat = json.load(open(td / "catalogue.json")); vals = []; done = 0
    for c in cat["entries"]:
        rp = td / c / "result.json"
        if rp.exists():
            done += 1; r = json.load(open(rp))
            if r.get("primary_status") == "auto_passed" and r.get("area_um2"): vals.append(r["area_um2"])
    return (min(vals) if vals else None), done == len(cat["entries"])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--tags", default=None); a = ap.parse_args()
    tags = a.tags.split(",") if a.tags else sorted(p.name for p in (paths.MODEL_RUNS).iterdir() if p.is_dir())
    sessions = []
    for tag in tags:
        for sd in sorted(glob.glob(str(paths.MODEL_RUNS / tag / "*" / "r*"))):
            sess, done, reps = session_rows(sd)
            if not reps: continue
            task = Path(sd).parent.name; ra = ref_area(task); be, be_complete = best_evaluated(task)
            first_legal = reps[0]["status"] == "evaluated"
            evaluated = [r for r in reps if r["status"] == "evaluated"]
            fresh = [r for r in evaluated if not r.get("duplicate_of")]
            st = collections.Counter((r["run"]["primary_status"] if r["status"] == "evaluated" else "rejected_program") for r in reps)
            best = {}
            for k in KS:
                feas = [r["run"]["area_um2"] for r in reps[:k] if r["status"] == "evaluated" and r["run"]["primary_status"] == "auto_passed" and r["run"].get("area_um2")]
                b = min(feas) if feas else None
                best[str(k)] = {"best_area": b, "vs_reference": (b / ra - 1) if (b and ra) else None, "vs_best_evaluated": (b / be - 1) if (b and be) else None}
            sessions.append({"tag": tag, "task": task, "topology": task.split("_")[0], "rep": Path(sd).name, "n_proposals": len(reps), "first_legal": first_legal,
                             "n_rejected": sum(1 for r in reps if r["status"] != "evaluated"), "n_duplicates": sum(1 for r in evaluated if r.get("duplicate_of")),
                             "eda_verifications": len(fresh), "statuses": dict(st),
                             "drc_lvs_clean": sum(1 for r in evaluated if (r["run"].get("verify") or {}).get("drc") == "passed" and (r["run"].get("verify") or {}).get("lvs") == "passed"),
                             "auto_passed": sum(1 for r in evaluated if r["run"]["primary_status"] == "auto_passed"),
                             "best": best, "reference_area": ra, "best_evaluated_area": be, "best_evaluated_complete": be_complete,
                             "evaluator_s": round(sum(r.get("evaluator_s", 0) for r in reps), 1),
                             "model_s": round(sum(c.get("seconds", 0) for c in (done.get("calls") or [])), 1) if done else None,
                             "usage": [c.get("usage") for c in (done.get("calls") or [])] if done else None,
                             "isolation_breach": done.get("isolation_breach_any") if done else None, "interface": sess.get("interface", "sharing")})
    summ = {}
    for tag in tags:
        ss = [s for s in sessions if s["tag"] == tag]
        if not ss: continue
        evald = sum(s["n_proposals"] - s["n_rejected"] for s in ss)
        d = {"sessions": len(ss), "tasks": len({s["task"] for s in ss}), "proposals": sum(s["n_proposals"] for s in ss),
             "eda_verifications": sum(s["eda_verifications"] for s in ss), "first_legal_rate": statistics.mean(s["first_legal"] for s in ss),
             "rejected_rate": sum(s["n_rejected"] for s in ss) / max(1, sum(s["n_proposals"] for s in ss)),
             "drc_lvs_clean_rate_of_evaluated": sum(s["drc_lvs_clean"] for s in ss) / max(1, evald),
             "auto_passed_rate_of_evaluated": sum(s["auto_passed"] for s in ss) / max(1, evald), "by_k": {}}
        for k in KS:
            found = [s["best"][str(k)]["best_area"] is not None for s in ss]
            vr = {}; vb = {}
            for s in ss:
                x = s["best"][str(k)]
                if x["vs_reference"] is not None: vr.setdefault(s["topology"], []).append(x["vs_reference"])
                if x["vs_best_evaluated"] is not None: vb.setdefault(s["topology"], []).append(x["vs_best_evaluated"])
            bal = lambda dd: statistics.mean(statistics.mean(v) for v in dd.values()) if dd else None
            d["by_k"][str(k)] = {"found_rate": statistics.mean(found), "vs_reference_balanced": bal(vr), "vs_best_evaluated_balanced": bal(vb),
                                 "n_vs_best_evaluated": sum(len(v) for v in vb.values())}
        summ[tag] = d
    json.dump({"summary": summ, "sessions": sessions}, open(a.out, "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
