"""Selection catalogue of one task (= one qualified case of the selection subset); fixed before any evaluation.

Per sharing group g: all 256 raw axis tuples (glayout.sharing.enumeration) -> static legality -> equivalence
de-duplication -> p_g unique candidates.  Global combination space = prod(p_g) (an upper bound on globally legal
combinations: assembly can still reject a combination; such rejections are counted when evaluated).
Sampling (no area, no verification result, no method output is used):
  1. the four named modes (per group: the named plan of the mode, else the group's independent plan);
     identical global combinations are kept once;
  2. if prod(p_g) <= LIMIT: every combination (exhaustive); else strata = the vector of per-group (diffusion, gate)
     axis values; strata are visited round-robin in sorted order and inside a stratum a combination is drawn uniformly
     with random.Random(SEED + task hash); duplicates are skipped; stop at LIMIT candidates or when every stratum is
     exhausted (300 consecutive misses).
Candidate ids are content hashes of the per-group plan ids (no ordering information)."""
from __future__ import annotations
import hashlib, random, itertools
from math import prod

LIMIT = 64
SEED = 20261011


def cand_id(plan_ids):
    return "c" + hashlib.sha256("|".join(plan_ids).encode()).hexdigest()[:11]


def build_catalogue(pdk, groups, task_id):
    from glayout.sharing import group_candidates, named_plans, independent_plan
    tables = []
    for g in groups:
        c = group_candidates(pdk, g); nm = named_plans(pdk, g, c)
        uniq = [(row["plan_id"], row["tuple"]) for row in c["rows"] if row["status"] == "unique"]
        ind = independent_plan(g)
        tables.append({"devices": [d.logical_id for d in g], "counts": c["counts"], "unique": uniq,
                       "plans": {pid: c["unique"][pid][1].to_json() for pid, _ in uniq} | {ind.plan_id(): ind.to_json()},
                       "named": {k: (v.plan_id() if v else None) for k, v in nm.items()}, "independent": ind.plan_id(), "rows": c["rows"]})
    product = prod(len(t["unique"]) for t in tables)
    entries = {}; order = []
    def add(pids, label):
        cid = cand_id(pids)
        if cid in entries: entries[cid]["labels"].append(label); return False
        entries[cid] = {"plan_ids": list(pids), "labels": [label]}; order.append(cid); return True
    for mode in ("independent", "diffusion_only", "gate_only", "combined"):
        pids = [t["named"].get(mode) or t["independent"] for t in tables]
        add(pids, f"named:{mode}")
    if product <= LIMIT:
        for combo in itertools.product(*[[pid for pid, _ in t["unique"]] for t in tables]):
            add(combo, "exhaustive")
        sampling = "exhaustive (prod(p_g) <= limit)"
    else:
        rng = random.Random(SEED + int(hashlib.sha256(task_id.encode()).hexdigest()[:8], 16))
        bykey = []
        for t in tables:
            m = {}
            for pid, tup in t["unique"]: m.setdefault((tup["diffusion"], tup["gate"]), []).append(pid)
            bykey.append(m)
        strata = sorted(itertools.product(*[sorted(m.keys()) for m in bykey]))
        misses = 0; k = 0
        while len(entries) < LIMIT and misses < 300:
            st = strata[k % len(strata)]; k += 1
            combo = [rng.choice(bykey[gi][key]) for gi, key in enumerate(st)]
            if add(combo, "stratified_sample"): misses = 0
            else: misses += 1
        sampling = f"stratified seeded sample over {len(strata)} strata (seed {SEED}+task hash)"
    ledger = {"per_group": [{"devices": t["devices"], **t["counts"]} for t in tables], "raw_per_group": 256,
              "global_product_of_unique": product, "named_distinct": sum(1 for c in order if any(l.startswith("named:") for l in entries[c]["labels"])),
              "selected_for_evaluation": len(order), "sampling": sampling, "limit": LIMIT}
    return {"task_id": task_id, "tables": [{k: v for k, v in t.items() if k != "rows"} for t in tables], "group_rows": [t["rows"] for t in tables],
            "entries": entries, "ledger": ledger}
