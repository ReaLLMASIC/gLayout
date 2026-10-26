#!/usr/bin/env python3
"""Bounded development anchor qualification for the draft editing inventory.

Reuse a prior engineering control only after exact geometry, labels, N(z),
electrical contract, evaluator bodies and pinned execution interface agree.
Then run the twelve component layout variants through the real full flow.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_task_prepare import save
from scripts.e3_generation_qualify import gate
from scripts.e3_physical_point import evaluate, trusted
from src.domain_runner import inspect_point, source_contents
from src.device_intent import compare_device_intent
from src.candidate_executor import IMAGE

COMPONENTS = ("mirror", "cascode_mirror", "source_follower", "stacked_switch", "common_source_stage", "resistive_diff")


def read(path):
    return json.loads(Path(path).read_text())


def exact_geometry(first, second, name):
    import gdstk
    def load(path):
        lib = gdstk.read_gds(path);top = next(cell for cell in lib.cells if cell.name == name)
        top.flatten();layers = {}
        for polygon in top.polygons:
            layers.setdefault((polygon.layer, polygon.datatype), []).append(polygon)
        labels = sorted((label.text, tuple(label.origin), label.layer, label.texttype) for label in top.labels)
        return lib, layers, labels
    a, left, labels_a = load(first);b, right, labels_b = load(second)
    changed = [list(layer) for layer in set(left)|set(right)
        if gdstk.boolean(left.get(layer, []), right.get(layer, []), "xor", precision=.001)]
    return {"same_units_and_precision": (a.unit,a.precision) == (b.unit,b.precision),
            "changed_layers": changed, "all_labels_equal": labels_a == labels_b,
            "equal": not changed and labels_a == labels_b and (a.unit,a.precision) == (b.unit,b.precision),
            "cell_names_excluded": True, "translation_removed": False}


def cache_control(task_path, generated, control, output):
    task = read(task_path);point = task["configurations"][0]
    private = Path(control["episode_directory"])/"private"
    old_task, state = read(private/"task.json"), read(private/"state.json")
    old_point = next(p for p in old_task["configurations"] if p["role"] == "anchor")
    old_record = state["points"][old_point["configuration_id"]]
    run = Path(old_record["run_directory"]);manifest = read(run/"manifest.json")
    record = {"task_id": task["task_id"], "original_episode": str(private.parent), "original_run": str(run),
        "generation_control": generated["result"]["run_directory"], "scope": "development_exact_artifact_cache_audit",
        "new_physical_calls": 0, "new_model_calls": 0, "adopted": False,
        "original_costs": state["costs_by_stage"], "original_phase_preserved": manifest["phase"]}
    output.mkdir(parents=True)
    if (run/"trusted/reference.spice").read_bytes() != Path(point["reference_file"]).read_bytes():
        record["reason"] = "Control independent N(z) differs; its rotated sized anchor cannot qualify this E3 initial anchor"
        save(output/"audit.json", record);return record
    for field in ("required_corners", "specifications", "analysis_contracts", "immutable_parameters", "numeric_options"):
        if old_point["contract"].get(field) != point["contract"].get(field):
            record["reason"] = "Electrical contract differs: "+field
            save(output/"audit.json", record);return record
    geometry = exact_geometry(Path(generated["result"]["run_directory"])/"accepted/candidate.gds", run/"accepted/candidate.gds", task["top_cell"])
    record["geometry"] = geometry
    if not geometry["equal"]:
        record["reason"] = "Actual GDS geometry/labels differ"
        save(output/"audit.json", record);return record
    current = output/"trusted_snapshot";trusted(task, point, current)
    originals = sorted(str(p.relative_to(run/"trusted")) for p in (run/"trusted").rglob("*") if p.is_file())
    for name in originals:
        if name in ("contract.json", "reference.spice"):
            continue
        other = current/("original_physical_evaluate.py" if name == "evaluate.py" else name)
        if not other.is_file() or other.read_bytes() != (run/"trusted"/name).read_bytes():
            record["reason"] = "Actual frozen evaluator/benchmark file differs: "+name
            save(output/"audit.json", record);return record
    candidate_argv = manifest["candidate"]["argv"]
    trusted_argv = manifest["trusted"]["argv"]
    if IMAGE not in candidate_argv or IMAGE not in trusted_argv or str(ROOT/"runtime/magic-8.3.685")+":/work/runtime/magic-8.3.685:ro" not in trusted_argv:
        record["reason"] = "Pinned image/Magic execution interface differs"
        save(output/"audit.json", record);return record
    if manifest["context"].get("pdk_revision") != "0fe599b2afb6708d281543108caf8310912f54af":
        raise ValueError("Prior control lacks the exact physical PDK revision")
    expected = source_contents(run/"source", manifest["source_files"], binary=True)
    checked = inspect_point({"run_directory": str(run)}, old_point, expected, read(run/"configuration.json"))
    graph = compare_device_intent((run/"evidence/extracted_lvs.spice").read_text(), (run/"trusted/reference.spice").read_text())
    if checked["S2"] is not True or checked["execution_integrity"] != "valid" or not graph["is_clean"]:
        raise ValueError("Prior raw reports do not establish exact complete physical S2")
    physical = read(run/"evidence/validation.json")
    area = generated["result"]["physical_result"]["area_um2"]
    definition = point["contract"]["objective"]
    if definition["metric"] == "area":
        quality = area
    else:
        rows = [physical["observation"]["corners"][corner]["metrics"]["ugb"] for corner in point["contract"]["required_corners"]]
        if any(row["unit"] != "Hz" for row in rows):
            raise ValueError("Prior complete OTA lacks actual UGB in Hz")
        quality = min(row["value"]/area for row in rows)
    record.update(adopted=True, reason="Exact actual geometry/labels, independent N(z), electrical contract, frozen evaluator/bench bytes and pinned execution interface agree",
        checked=checked, independent_terminal_graph_clean=True, area_um2=area, objective=quality,
        objective_definition=definition, original_UGB_from_complete_measurements=definition["metric"] == "ugb_per_area")
    save(output/"audit.json", record)
    return record


def run(preparation, generation_path, summaries, output):
    generation = read(generation_path)
    if generation["evaluated_states"] != 24 or not all(row["three_distinct_filled_geometries"] for row in generation["targets"]):
        raise ValueError("All 24 initial states must first cross the single-GDS/geometry boundary")
    generated = {row["task_id"]: row for row in generation["records"]}
    controls = {}
    for summary in summaries:
        for row in read(summary)["episodes"]:
            control_task = read(Path(row["episode_directory"])/"private/task.json")
            if row["final_anchor"]["complete"] and row["final_anchor"]["S2"]:
                controls[control_task["target"]] = row
    if len(controls) != 8:
        raise ValueError("Exactly eight actual target controls are required")
    output.mkdir(parents=True, exist_ok=False)
    records, jobs = [], []
    for task_path in sorted((preparation/"private").glob("draft_E3_*/task.json")):
        task = read(task_path)
        if task["task_id"].endswith("edit01"):
            audit = cache_control(task_path, generated[task["task_id"]], controls[task["target"]], output/"cache"/task["task_id"])
            records.append(audit)
            if not audit["adopted"]:
                jobs.insert(0, task_path)
        elif task["target"] in COMPONENTS:
            jobs.append(task_path)
    save(output/"dispatch_plan.json", {"scope": "development_E3_initial_anchor_qualification", "fixed_component_variant_jobs": 12,
        "baseline_reruns_required_by_actual_mismatch": len(jobs)-12, "jobs": [str(p) for p in jobs], "cache_audits": records})
    for index, task_path in enumerate(jobs):
        resources = gate()
        if shutil.disk_usage(ROOT).free < 4*1024**3:
            raise RuntimeError("Research disk below4GiB; no new point dispatched")
        task = read(task_path)
        result = evaluate(task_path, "anchor", output/"physical_points"/("%02d_" % index+task["task_id"]))
        result["resources"] = resources
        records.append(result)
        save(output/"progress.json", {"completed_new_physical_points": index+1, "declared_new_physical_points": len(jobs), "records": records})
        print(json.dumps({"completed": index+1, "task_id": task["task_id"], "checked": result["checked"], "objective": result["objective"]}), flush=True)
    report = {"scope": "development_E3_anchor_qualification_not_formal", "preparation": str(preparation),
        "status": "COMPLETE", "new_physical_points": len(jobs), "reused_exact_controls": sum(row.get("adopted", False) for row in records),
        "records": records, "formal_trials": 0, "model_calls": 0,
        "initial_domain_qualified": False, "note": "Only anchors; natural/clean-poor admission still needs the declared feasible witness comparison and E3 protocol freeze"}
    save(output/"summary.json", report);print(json.dumps({"summary": str(output/"summary.json"), "new_physical_points": len(jobs)}), flush=True)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__);p.add_argument("--preparation", type=Path, required=True)
    p.add_argument("--generation-summary", type=Path, required=True);p.add_argument("--mechanical-summary", type=Path, action="append", required=True)
    p.add_argument("--output", type=Path, required=True);a = p.parse_args()
    run(a.preparation, a.generation_summary, a.mechanical_summary, a.output)
