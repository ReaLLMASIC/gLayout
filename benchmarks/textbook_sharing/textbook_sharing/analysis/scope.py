"""Scope audit of the comparisons (no new runs; reads the existing results).
1. Task sets: designed selection grid (6 topologies x 3 PDKs x 4 sizes), what drops out and why, the selection set,
   the model-session set and the interface-comparison set.
2. Same-task comparison on the model-session tasks: every selection method after n verifications and every model
   after n proposals, measured against (a) the best feasible candidate of the task's sampled catalogue and (b) the best
   feasible layout known for the task (catalogue + every model proposal of every arm).  The catalogue is a sample of
   at most 64 plans, so a model can beat (a); (b) puts all methods on one reference.
3. Interface comparison: per arm, change vs the unshared reference and gap to the best known layout.
Topology-balanced means (mean over topologies of the mean over that topology's tasks; repetitions/seeds averaged
inside a task first).  usage: python -m textbook_sharing.analysis.scope --out <results>/analysis/scope_audit.json"""
import json, glob, argparse, statistics, collections
from pathlib import Path
from textbook_sharing import paths
SEL_TOPOS = ["C02", "C08", "C09", "C11", "C16", "C18"]; PDKS = ["sky130", "gf180", "ihp130"]
SEL_SIZES = ["sW1_sL1", "sW1_sL2", "sW2_sL1", "sW2_sL2"]
MAIN_TAGS = ["openai_gpt-6.1-sol", "anthropic_claude-sonnet"]; BASE_TAG = "openai_gpt-6.1-sol_baseiface"


def bal(vals):
    """vals: {task: [values]} -> topology-balanced mean."""
    by = collections.defaultdict(list)
    for t, v in vals.items():
        v = [x for x in v if x is not None]
        if v: by[t.split("_")[0]].append(statistics.mean(v))
    return statistics.mean(statistics.mean(v) for v in by.values()) if by else None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
    from textbook_sharing.selection.strategies import evaluate_task, FIXED_ORDER
    from textbook_sharing.analysis.models import ref_area, best_evaluated, session_rows
    L = json.load(open(paths.LEDGER))
    diag = {d["case_id"]: d for d in L["diagnostic"]}
    designed = [f"{c}_{p}_{s}" for c in SEL_TOPOS for p in PDKS for s in SEL_SIZES]
    sel = sorted(Path(d).parent.name for d in glob.glob(str(paths.SELECTION_RUNS / "*/catalogue.json")))
    dropped = {t: (diag.get(t, {}).get("reason", "not formal") + (": " + diag[t]["detail"] if t in diag and diag[t].get("detail") else "")) for t in designed if t not in sel}
    llm_tasks = sorted({Path(d).name for tag in MAIN_TAGS for d in glob.glob(str(paths.MODEL_RUNS / tag / "*")) if Path(d).is_dir()})
    if_tasks = sorted({Path(d).name for d in glob.glob(str(paths.MODEL_RUNS / BASE_TAG / "*")) if Path(d).is_dir()})
    sets = {"designed_selection": len(designed), "dropped": dropped, "selection": len(sel), "selection_topologies": sorted({t.split("_")[0] for t in sel}),
            "model_tasks": len(llm_tasks), "model_tasks_rule": "selection tasks at sW = 2 (sL 1 and 2)", "model_tasks_ok": all(t in sel and "_sW2_" in t for t in llm_tasks),
            "interface_tasks": len(if_tasks), "interface_tasks_rule": "model tasks at sW2_sL1", "interface_tasks_ok": all(t.endswith("sW2_sL1") and t in llm_tasks for t in if_tasks)}
    # ---- sessions: best feasible area after k proposals
    sess = collections.defaultdict(lambda: collections.defaultdict(list))   # tag -> task -> [ {k: area} ]
    for tag in MAIN_TAGS + [BASE_TAG]:
        for sd in sorted(glob.glob(str(paths.MODEL_RUNS / tag / "*" / "r*"))):
            _, _, reps = session_rows(sd)
            if not reps: continue
            best = {}; cur = None
            for i, r in enumerate(reps, 1):
                if r.get("status") == "evaluated" and r["run"]["primary_status"] == "auto_passed" and r["run"].get("area_um2"):
                    cur = r["run"]["area_um2"] if cur is None else min(cur, r["run"]["area_um2"])
                if i in (1, 2, 4, 8): best[i] = cur
            for k in (1, 2, 4, 8): best.setdefault(k, cur)
            sess[tag][Path(sd).parent.name].append(best)
    # ---- selection methods on the model tasks
    meth = {}
    for t in llm_tasks:
        rows = evaluate_task(paths.SELECTION_RUNS / t, fixed_order=FIXED_ORDER)
        for r in rows:
            for n in ("1", "2", "4", "8", "16"):
                meth.setdefault(r["method"], collections.defaultdict(lambda: collections.defaultdict(list)))[n][t].append(r["prefix"][n]["best_area"])
    best_cat = {t: best_evaluated(t)[0] for t in llm_tasks}
    best_known = {}
    for t in llm_tasks:
        cands = [best_cat[t]] + [b[8] for tag in sess for b in sess[tag].get(t, []) if b.get(8)]
        best_known[t] = min(c for c in cands if c)
    src = {t: ("catalogue" if abs(best_known[t] - best_cat[t]) < 1e-9 else "model proposal") for t in llm_tasks}
    who = {}
    for t in llm_tasks:
        if src[t] == "catalogue": continue
        who[t] = sorted({tag for tag in sess for b in sess[tag].get(t, []) if b.get(8) and abs(b[8] - best_known[t]) < 1e-9})
    def gaps(area_by_task, ref):
        return {t: [(x / ref[t] - 1) if x else None for x in v] for t, v in area_by_task.items()}
    same = {}
    for m, d in meth.items():
        same[m] = {f"{n} ver.": {"vs_catalogue_best": bal(gaps(d[n], best_cat)), "vs_best_known": bal(gaps(d[n], best_known))} for n in ("1", "2", "4", "8", "16")}
    for tag in MAIN_TAGS:
        same[tag] = {}
        for k in (1, 2, 4, 8):
            ab = {t: [b[k] for b in v] for t, v in sess[tag].items()}
            same[tag][f"{k} prop."] = {"vs_catalogue_best": bal(gaps(ab, best_cat)), "vs_best_known": bal(gaps(ab, best_known)),
                                       "sessions": sum(len(v) for v in ab.values())}
        g8 = [b[8] / best_cat[t] - 1 for t, v in sess[tag].items() for b in v if b[8]]
        same[tag]["sessions_below_catalogue_best"] = sum(g < -1e-9 for g in g8); same[tag]["sessions_equal"] = sum(abs(g) < 1e-9 for g in g8)
        same[tag]["sessions_above"] = sum(g > 1e-9 for g in g8)
    ref = {t: ref_area(t) for t in llm_tasks}
    same["unshared reference"] = {"vs_catalogue_best": bal({t: [ref[t] / best_cat[t] - 1] for t in llm_tasks}), "vs_best_known": bal({t: [ref[t] / best_known[t] - 1] for t in llm_tasks})}
    # ---- interface comparison (14 tasks)
    itf = {}
    for arm, tag in (("sharing interface", MAIN_TAGS[0]), ("base-gLayout interface", BASE_TAG)):
        ab = {t: [b[8] for b in sess[tag][t]] for t in if_tasks}
        itf[arm] = {"sessions": sum(len(v) for v in ab.values()), "vs_reference": bal({t: [(x / ref[t] - 1) if x else None for x in v] for t, v in ab.items()}),
                    "vs_catalogue_best": bal(gaps(ab, best_cat)), "vs_best_known": bal(gaps(ab, best_known)),
                    "sessions_equal_to_reference": sum(1 for t, v in ab.items() for x in v if x and abs(x / ref[t] - 1) < 1e-3)}
    itf["unshared reference"] = {"vs_catalogue_best": bal({t: [ref[t] / best_cat[t] - 1] for t in if_tasks}), "vs_best_known": bal({t: [ref[t] / best_known[t] - 1] for t in if_tasks})}
    out = {"task_sets": sets, "model_tasks": llm_tasks, "interface_tasks": if_tasks, "best_known_source": dict(collections.Counter(src.values())),
           "best_known_found_by": who,
           "best_known_by_task": {t: {"catalogue_best": best_cat[t], "best_known": best_known[t], "source": src[t], "reference": ref[t]} for t in llm_tasks},
           "same_task_comparison_model_tasks": same, "interface_comparison": itf,
           "note": "selection methods choose only among the <=64 sampled catalogue plans; models may propose any legal plan"}
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("task_sets", "best_known_source", "interface_comparison")}, indent=1))
    for m, d in same.items(): print(m, json.dumps(d))


if __name__ == "__main__":
    main()
