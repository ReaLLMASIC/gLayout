#!/usr/bin/env python3
"""Pair actual development anchors with feasible complete-source witnesses.

No outcomes are inferred for unmeasured states or incomplete simulations. A
larger measured area alone is not a clean-but-poor qualification unless both
programs satisfy the same complete electrical anchor contract.
"""
import argparse
import json
import math
from pathlib import Path


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def classify(record, baseline, definition):
    if record is None:
        return {"classification": "NOT_MEASURED", "qualifies_shortfall": False}
    checked = record.get("checked", {})
    if checked.get("execution_integrity") != "valid" or checked.get("failure_class") in ("unknown", "infrastructure"):
        return {"classification": "UNKNOWN_OR_INCOMPLETE", "qualifies_shortfall": False}
    base = (baseline or {}).get("checked", {})
    if base.get("execution_integrity") != "valid" or base.get("S2") is not True:
        return {"classification": "NO_FEASIBLE_WITNESS", "qualifies_shortfall": False}
    if checked.get("S1") is False and checked.get("failure_class") == "candidate":
        return {"classification": "NON_INJECTED_LAYOUT_CORRECTNESS_SHORTFALL", "qualifies_shortfall": True}
    if checked.get("S2") is False and checked.get("failure_class") == "candidate" and checked.get("analysis_complete") is True:
        return {"classification": "NON_INJECTED_ELECTRICAL_SHORTFALL", "qualifies_shortfall": True}
    if checked.get("S2") is not True:
        return {"classification": "INCOMPLETE_SHORTFALL_EVIDENCE", "qualifies_shortfall": False}
    current, witness = record.get("objective"), (baseline or {}).get("objective")
    if not finite(current) or not finite(witness):
        return {"classification": "OBJECTIVE_UNMEASURED", "qualifies_shortfall": False}
    signed = current-witness if definition["direction"] == "min" else witness-current
    relative = signed/max(abs(current), 1e-30)
    better = signed > max(abs(current), abs(witness))*1e-9
    return {"classification": "CLEAN_BUT_POOR_LEGAL_LAYOUT" if better else "FEASIBLE_WITHOUT_BETTER_BASELINE_WITNESS",
        "qualifies_shortfall": better, "initial_objective": current, "witness_objective": witness,
        "relative_improvement_to_witness": relative, "at_least_one_percent_improvement": relative >= .01}


def summarize(preparation, evidence, output):
    raw = json.loads(evidence.read_text())
    records = {}
    for row in raw["records"]:
        if row.get("adopted") is True or "run_directory" in row:
            records[row["task_id"]] = row
    tasks = {path.parent.name: (path, json.loads(path.read_text())) for path in sorted((preparation/"private").glob("draft_E3_*/task.json"))}
    if len(tasks) != 24:
        raise ValueError("The declared inventory has exactly 24 states")
    rows = []
    for ident, (path, task) in tasks.items():
        baseline_id = "draft_E3_"+task["target"]+"_edit01"
        baseline_task = tasks[baseline_id][1]
        anchor, base_anchor = task["configurations"][0], baseline_task["configurations"][0]
        if (anchor["parameters"] != base_anchor["parameters"] or
            Path(anchor["reference_file"]).read_bytes() != Path(base_anchor["reference_file"]).read_bytes() or
            anchor["contract"]["specifications"] != base_anchor["contract"]["specifications"] or
            task["E1_binding"] != baseline_task["E1_binding"]):
            raise ValueError("A feasible witness belongs to a different N(z), bench or electrical contract")
        result = classify(records.get(ident), records.get(baseline_id), anchor["contract"]["objective"])
        if task["ancestry"]["injected_defect"]:
            result.update(qualifies_shortfall=False, classification="INJECTED_SOURCE_EXCLUDED_FROM_NATURAL_QUOTA")
        rows.append({"task_id": ident, "target": task["target"], "source_origin": task["ancestry"]["origin"],
            "witness_task_id": baseline_id, "witness_source": baseline_task["source_overrides"],
            "witness_evidence": records.get(baseline_id, {}).get("original_run", records.get(baseline_id, {}).get("run_directory")),
            "objective_definition": anchor["contract"]["objective"], **result})
    report = {"scope": "development_E3_actual_anchor_witness_analysis_not_formal", "preparation": str(preparation),
        "evidence": str(evidence), "declared_states": 24, "currently_measured_states": len(records),
        "qualifying_non_injected_shortfalls": sum(row["qualifies_shortfall"] for row in rows),
        "required_half_inventory_count": 12, "states": rows,
        "interpretation": "Authored legal layout variants and curated engineering streams retain their provenance; this does not claim uncurated production bugs or full25-point layout feasibility.",
        "new_physical_calls": 0, "new_model_calls": 0, "formal_trials": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps({key: value for key, value in report.items() if key != "states"}), flush=True)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__);p.add_argument("--preparation", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True);p.add_argument("--output", type=Path, required=True)
    a = p.parse_args();summarize(a.preparation, a.evidence, a.output)
