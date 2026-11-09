"""Aggregate the plan-selection experiment (offline replay on fully verified catalogues).
Per task and method: best feasible area after n verifications (n = 1, 2, 4, 8, 16), gap to the best feasible candidate
of the evaluated set ("best of the evaluated set", not a global optimum), found/not found, time.  Random = mean over 10
seeds.  Aggregates: (a) per-task paired comparison vs the cost ranking, (b) topology-balanced mean (mean over
topologies of the mean over that topology's tasks), (c) 95 % intervals by cluster bootstrap over topologies (B = 2000,
seed 20261011).  Tasks whose evaluated set has no feasible candidate are reported separately.
usage: python -m textbook_sharing.analysis.selection --out <results>/analysis/selection_summary.json"""
import json, glob, random, statistics, argparse, collections
from pathlib import Path
from textbook_sharing.selection.strategies import evaluate_task, PREFIXES, FIXED_ORDER
from textbook_sharing import paths

METHODS = ["baseline_independent", "fixed_mode", "share_most", "random", "neighbourhood", "cost_rank", "geometry_first"]


def per_task_rows(td):
    rows = evaluate_task(td, fixed_order=FIXED_ORDER)
    out = {}
    for m in METHODS:
        rs = [r for r in rows if r["method"] == m]
        if not rs: continue
        d = {}
        for n in PREFIXES:
            ps = [r["prefix"][str(n)] for r in rs]
            found = [p["best_area"] is not None for p in ps]
            gaps = [p["gap"] for p in ps if p["gap"] is not None]
            d[str(n)] = {"found_rate": sum(found) / len(found), "gap_mean_found": statistics.mean(gaps) if gaps else None,
                         "gap_or_inf": statistics.mean([p["gap"] if p["gap"] is not None else float("inf") for p in ps]),
                         "time_s": statistics.mean(p["time_s"] for p in ps)}
        out[m] = {"prefix": d, "precompute_s": statistics.mean(r["precompute_s"] for r in rs), "n_runs": len(rs),
                  "first_feasible_query": [r["first_feasible_query"] for r in rs]}
    r0 = rows[0]
    return {"task": Path(td).name, "n_evaluated": r0["n_evaluated"], "n_feasible": r0["n_feasible"], "best_evaluated": r0["best_evaluated"], "methods": out}


def topo(task):
    return task.split("_")[0]


def balanced(vals_by_task, tasks):
    by = collections.defaultdict(list)
    for t in tasks:
        v = vals_by_task.get(t)
        if v is not None: by[topo(t)].append(v)
    means = [statistics.mean(v) for v in by.values() if v]
    return statistics.mean(means) if means else None, by


def boot(vals_by_task, tasks, B=2000, seed=20261011):
    _, by = balanced(vals_by_task, tasks); keys = sorted(by); r = random.Random(seed); est = []
    for _ in range(B):
        samp = [r.choice(keys) for _ in keys]
        est.append(statistics.mean(statistics.mean(by[k]) for k in samp))
    est.sort(); return [est[int(0.025 * B)], est[int(0.975 * B) - 1]]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
    tds = sorted(d for d in glob.glob(str(paths.SELECTION_RUNS / "*")) if (Path(d) / "catalogue.json").exists())
    tasks = []; incomplete = []
    for td in tds:
        cat = json.load(open(Path(td) / "catalogue.json"))
        done = sum(1 for c in cat["entries"] if (Path(td) / c / "result.json").exists())
        if done < len(cat["entries"]): incomplete.append({"task": Path(td).name, "done": done, "n": len(cat["entries"])}); continue
        tasks.append(per_task_rows(td))
    feas = [t for t in tasks if t["n_feasible"] > 0]; nofeas = [t["task"] for t in tasks if t["n_feasible"] == 0]
    names = [t["task"] for t in feas]
    summ = {"n_tasks_complete": len(tasks), "n_tasks_with_feasible": len(feas), "tasks_without_feasible": nofeas, "incomplete": incomplete,
            "topologies": sorted({topo(t) for t in names}), "fixed_order": FIXED_ORDER, "by_method": {}}
    for m in METHODS:
        mm = {}
        for n in PREFIXES:
            fr = {t["task"]: t["methods"][m]["prefix"][str(n)]["found_rate"] for t in feas if m in t["methods"]}
            gp = {t["task"]: t["methods"][m]["prefix"][str(n)]["gap_mean_found"] for t in feas if m in t["methods"] and t["methods"][m]["prefix"][str(n)]["gap_mean_found"] is not None}
            tm = {t["task"]: t["methods"][m]["prefix"][str(n)]["time_s"] for t in feas if m in t["methods"]}
            zero = {t["task"]: 1.0 if (t["methods"][m]["prefix"][str(n)]["gap_mean_found"] is not None and t["methods"][m]["prefix"][str(n)]["gap_mean_found"] < 1e-9) else 0.0 for t in feas if m in t["methods"]}
            mm[str(n)] = {"found_rate_balanced": balanced(fr, names)[0], "found_rate_ci": boot(fr, names),
                          "gap_balanced_when_found": balanced(gp, names)[0], "gap_ci": boot(gp, list(gp)) if gp else None,
                          "hit_best_rate_balanced": balanced(zero, names)[0], "time_s_balanced": balanced(tm, names)[0], "n_tasks": len(fr)}
        summ["by_method"][m] = mm
    # paired comparison vs cost_rank at each budget: fraction of tasks where the method's best area is better / equal / worse
    pair = {}
    for m in METHODS:
        if m == "cost_rank": continue
        pm = {}
        for n in PREFIXES:
            w = e = l = 0
            for t in feas:
                a_ = t["methods"].get(m, {}).get("prefix", {}).get(str(n), {}).get("gap_or_inf"); b_ = t["methods"]["cost_rank"]["prefix"][str(n)]["gap_or_inf"]
                if a_ is None: continue
                if abs(a_ - b_) < 1e-9 or (a_ == b_): e += 1
                elif a_ < b_: w += 1
                else: l += 1
            pm[str(n)] = {"better": w, "equal": e, "worse": l}
        pair[m] = pm
    summ["paired_vs_cost_rank"] = pair
    json.dump({"summary": summ, "tasks": tasks}, open(a.out, "w"), indent=1)
    print(json.dumps({k: summ[k] for k in ("n_tasks_complete", "n_tasks_with_feasible", "tasks_without_feasible", "incomplete")}, indent=1)[:1500])
    for m in METHODS:
        print(m, {n: (round(v["found_rate_balanced"] or 0, 3), None if v["gap_balanced_when_found"] is None else round(v["gap_balanced_when_found"], 4), round(v["time_s_balanced"] or 0)) for n, v in summ["by_method"][m].items()})


if __name__ == "__main__":
    main()
