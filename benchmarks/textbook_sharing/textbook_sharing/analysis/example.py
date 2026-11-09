"""The running example of the documentation: the five-transistor OTA (C08) in SKY130 at the nominal size, taken from the
unshared layout to the best catalogue plan one decision at a time.  All five layouts are candidates of the selection
catalogue of this case, so each was built and fully verified; this module only reads their records.
usage: python -m textbook_sharing.analysis.example --out <results>/analysis/running_example.json"""
import argparse, json
from textbook_sharing import paths

TASK = "C08_sky130_sW1_sL1"
STEPS = [("c1ebe43136e1", "unshared reference"),
         ("cc0a97e9039c", "group 0 shares its net23 diffusion nodes"),
         ("c051fabe4412", "group 1 also shares its VDD node (side case)"),
         ("cd7b91d3467f", "group 1 shares VDD and drives both gates (net22) with one strap"),
         ("c15f7f08c7b4", "that strap is turned toward the middle channel")]


def group_summary(plan, ev):
    return {"devices": plan["devices"],
            "shared_diffusion_nets": [n["net"] for n in ev["cross_device_shared_nodes"]],
            "gate_straps": [{"fingers": len(g[0]), "side": g[1], "pad_end": g[2]} for g in plan["plan"]["gate_groups"]],
            "shared_gate_conductors": [g["devices"] for g in ev["shared_gate_conductors"]],
            "active_islands": ev["active_islands"]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
    d = paths.SELECTION_RUNS / TASK
    cat = json.load(open(d / "catalogue.json"))["ledger"]
    case = json.load(open(paths.CASES / "C08/sky130/sW1_sL1/specs.json"))
    steps = []
    for cid, what in STEPS:
        r = json.load(open(d / cid / "result.json")); st = r["assembly_stats"]
        rv = json.load(open(d / cid / "verify/review/review_record.json"))
        steps.append({"candidate": cid, "decision": what, "status": r["primary_status"], "visual_review": rv["visual"]["verdict"],
                      "area_um2": r["area_um2"], "width_um": st["width"], "height_um": st["height"],
                      "rows": [{"kind": x["kind"], "width_um": x["width"], "height_um": x["height"]} for x in st["row_dims"]],
                      "channel_heights_um": st["channel_heights"],
                      "groups": [group_summary(p, e) for p, e in zip(r["applied_plans"], r["evidence"])],
                      "gain_db": r["postsim"]["measures"].get("gain_lf"), "ugf_hz": r["postsim"]["measures"].get("ugf")})
    ref = steps[0]["area_um2"]
    for s in steps:
        s["change_vs_unshared"] = round(s["area_um2"] / ref - 1, 5)
    comb = json.load(open(paths.GRID_RUNS / "C08/sky130/sW1_sL1/combined/result.json"))
    out = {"task": TASK, "steps": steps,
           "plan_space": {"plans_per_group": [g["unique"] for g in cat["per_group"]], "plans": cat["global_product_of_unique"],
                          "catalogue_size": cat["selected_for_evaluation"]},
           "named_mode_combined": {"area_um2": comb["area_um2"], "status": comb["primary_status"],
                                   "unshared_groups": [i for i, p in enumerate(comb["applied_plans"]) if p["plan"]["mode_label"] == "independent"],
                                   "change_vs_unshared": round(comb["area_um2"] / ref - 1, 5),
                                   "above_best": round(comb["area_um2"] / steps[-1]["area_um2"] - 1, 5)},
           "specs": {"gain_db_min": case["gain_lf"]["min"], "ugf_hz_min": case["ugf"]["min"]}}
    json.dump(out, open(a.out, "w"), indent=1)
    for s in steps:
        print(s["candidate"], s["area_um2"], s["width_um"], s["height_um"], f"{100 * s['change_vs_unshared']:+.1f} %", s["status"], s["visual_review"])


if __name__ == "__main__":
    main()
