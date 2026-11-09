"""Declared matching constraints of the 18 topologies and their geometric check.

Only what a case declares is checked.  Declared per matched set:
  ratio (hard): the total-width ratio of the devices equals the nominal ratio of the case definition (the sizing check
     of the extracted netlist verifies absolute widths; here the plan's finger counts x unit width are compared);
  orientation_balance (reported): per device, |#SD - #DS| fingers (0 = current flows both ways equally);
  centroid_offset (reported): distance in finger pitches between the finger-position centroids of the devices when they
     sit in the same group/row ('n/a: different groups' otherwise).
No case declares common-centroid as a requirement, so centroid and orientation are reported, never pass/fail.
These are geometry checks of the drawn plan; they are not silicon mismatch measurements."""
from __future__ import annotations

MATCHED = {
    "C01": [("M1", "M2")],
    "C02": [("M2", "M4"), ("M1", "M3")],
    "C03": [("M1", "M2")],
    "C13": [("M3", "M5"), ("M2", "M4")],
    "C14": [("M1", "M2")],
    "C07": [("M1", "M2"), ("M3", "M4")],
    "C08": [("M1", "M2"), ("M4", "M5")],
    "C09": [("M1", "M2"), ("M3", "M4"), ("M5", "M6"), ("M7", "M8")],
    "C10": [("M1", "M2"), ("M3", "M4"), ("M5", "M6"), ("M7", "M8"), ("M9", "M10")],
    "C11": [("M3", "M4"), ("M5", "M6"), ("M1", "M2")],
    "C16": [("M1", "M2"), ("R1", "R2")],
    "C17": [("M1", "M2"), ("R1", "R2"), ("R3", "R4")],
    "C18": [("M3", "M5"), ("M4", "M6")],
}


def check(cid, sizing_nominal, sizing_case, applied_plans):
    """applied_plans: list of {'devices': [...], 'plan': canonical plan json} from the builder."""
    out = []; hard_ok = True
    where = {}
    for gi, ap in enumerate(applied_plans):
        pl = ap["plan"]
        for pos, (dev, k) in enumerate(pl["finger_order"]):
            where.setdefault(dev, {"group": gi, "pos": [], "orient": []})
            where[dev]["pos"].append(pos); where[dev]["orient"].append(pl["orientations"][pos])
    for a, b in MATCHED.get(cid, []):
        rec = {"pair": [a, b]}
        sa, sb = sizing_case.get(a, {}), sizing_case.get(b, {}); na, nb = sizing_nominal.get(a, {}), sizing_nominal.get(b, {})
        if "w" in sa and "w" in sb and "w" in na and "w" in nb and "nf" in sa:
            r_case = sa["w"] / sb["w"]; r_nom = na["w"] / nb["w"]
            rec["ratio"] = {"case": round(r_case, 6), "nominal": round(r_nom, 6), "ok": abs(r_case / r_nom - 1) < 1e-6}
            hard_ok = hard_ok and rec["ratio"]["ok"]
        elif "r" in sa:
            rec["ratio"] = {"case": round(sa["r"] / sb["r"], 6), "nominal": round(na["r"] / nb["r"], 6), "ok": abs((sa["r"] / sb["r"]) / (na["r"] / nb["r"]) - 1) < 1e-6}
            hard_ok = hard_ok and rec["ratio"]["ok"]
        if a in where and b in where:
            wa, wb = where[a], where[b]
            rec["orientation_balance"] = {a: abs(wa["orient"].count("SD") - wa["orient"].count("DS")), b: abs(wb["orient"].count("SD") - wb["orient"].count("DS"))}
            if wa["group"] == wb["group"]:
                ca = sum(wa["pos"]) / len(wa["pos"]); cb = sum(wb["pos"]) / len(wb["pos"])
                rec["centroid_offset_pitches"] = round(abs(ca - cb), 3)
            else:
                rec["centroid_offset_pitches"] = "n/a: different groups"
        out.append(rec)
    return {"status": "passed" if hard_ok else "constraints_failed", "declared_pairs": out, "rule": "textbook_sharing.matching v1"}
