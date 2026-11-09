"""Per-topology benchmark table: devices, sharing groups, plan space at the nominal size, request outcomes over the
36 size/PDK points, applicable sharing modes among the formal entries, and membership in the selection and model
studies.  No layout is generated: plan counts come from the static enumeration (legality + de-duplication only).
usage: python -m textbook_sharing.analysis.benchmark_table --out <results>/analysis/benchmark_table.json"""
import json, glob, argparse, collections, math
from pathlib import Path
from textbook_sharing import paths
MODES = ("independent", "diffusion_only", "gate_only", "combined")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.testbench import CATEGORY
    from textbook_sharing.run_case import load_case_dir, pdk_obj
    from textbook_sharing.layout import device_specs, sharing_groups
    from glayout.sharing import group_candidates
    L = json.load(open(paths.LEDGER)); formal = set(L["formal_entries"])
    diag = {d["case_id"]: d["reason"] for d in L["diagnostic"]}
    illegal = set()
    for f in glob.glob(str(paths.CASES / "*/*/*/case.json")):
        c = json.load(open(f))
        if c.get("status") == "parameter_illegal" or c.get("parameter_illegal"): illegal.add(c.get("case_id"))
    sel = {Path(d).parent.name for d in glob.glob(str(paths.SELECTION_RUNS / "*/catalogue.json"))}
    llm = {Path(d).name for d in glob.glob(str(paths.MODEL_RUNS / "openai_gpt-6.1-sol" / "*")) if Path(d).is_dir()}
    pdk = pdk_obj("sky130"); rows = []
    for cid in sorted(CIRCUITS):
        c = CIRCUITS[cid]; kinds = collections.Counter(d.kind for d in c.devices)
        case, _ = load_case_dir(str(paths.CASES / cid / "sky130" / "sW1_sL1"))
        groups = sharing_groups(device_specs(c, case.sizing)); per = []
        for g in groups:
            cnt = group_candidates(pdk, g)["counts"]
            per.append({"devices": [d.logical_id for d in g], "fingers": sum(d.nf for d in g), "unique_plans": cnt["unique"], "raw": cnt.get("raw", 256),
                        "static_illegal": cnt.get("static_illegal"), "equivalent_duplicate": cnt.get("equivalent_duplicate")})
        ids = [f"{cid}_{p}_{s}" for p in ("sky130", "gf180", "ihp130") for s in
               [f"sW{sw:g}_sL{sl:g}" for sw in (0.5, 1, 1.5, 2) for sl in (1, 1.5, 2)]]
        outcome = collections.Counter()
        for i in ids:
            if i in formal: outcome["formal"] += 1
            else: outcome[diag.get(i, "parameter_illegal")] += 1
        appl = collections.Counter()
        for i in ids:
            if i not in formal: continue
            _, pk, sz = i.split("_", 2)
            for m in MODES[1:]:
                f = paths.GRID_RUNS / cid / pk / sz / m / "result.json"
                if f.exists() and json.load(open(f)).get("primary_status") not in (None, "NA"): appl[m] += 1
        rows.append({"topology": cid, "name": c.name if hasattr(c, "name") else getattr(c, "family", ""), "category": CATEGORY[cid],
                     "mos": kinds.get("nfet", 0) + kinds.get("pfet", 0), "res": kinds.get("res", 0), "cap": kinds.get("cap", 0),
                     "groups_nominal_sky130": per, "plan_space_nominal_sky130": math.prod(g["unique_plans"] for g in per),
                     "requests": len(ids), "outcomes": dict(outcome),
                     "formal_by_pdk": {p: sum(1 for i in ids if i in formal and f"_{p}_" in i) for p in ("sky130", "gf180", "ihp130")},
                     "modes_applicable_in_formal": dict(appl), "selection_tasks": sum(1 for t in sel if t.startswith(cid + "_")),
                     "model_tasks": sum(1 for t in llm if t.startswith(cid + "_"))})
    tot = collections.Counter()
    for r in rows:
        for k, v in r["outcomes"].items(): tot[k] += v
    out = {"rows": rows, "totals": {"requests": sum(r["requests"] for r in rows), "outcomes": dict(tot),
                                    "topologies_with_formal_entries": sum(1 for r in rows if r["outcomes"].get("formal")),
                                    "selection_tasks": sum(r["selection_tasks"] for r in rows), "model_tasks": sum(r["model_tasks"] for r in rows)}}
    json.dump(out, open(a.out, "w"), indent=1)
    for r in rows:
        print(r["topology"], r["category"], r["mos"], r["res"], r["cap"], [g["unique_plans"] for g in r["groups_nominal_sky130"]], r["plan_space_nominal_sky130"],
              r["outcomes"], r["formal_by_pdk"], r["modes_applicable_in_formal"], r["selection_tasks"], r["model_tasks"])
    print(out["totals"])


if __name__ == "__main__":
    main()
