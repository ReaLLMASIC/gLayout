"""Audit actual identical-anchor development evidence, without new EDA labels.

Consumes only the prepared independent gold, saved original raw artifacts and
the already generated anchor. Candidate source is never imported. Old failed
attempts remain failed; compact uses its separate complete original2pF run.
"""
import argparse
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time

import gdstk

sys.path.insert(0, "/work")
from src.device_intent import compare_device_intent
from src.report_parsers import rc_netlist_inventory

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--generation-run", required=True)
args = parser.parse_args()
ROOT = Path("/work")
task_folder = Path(os.environ["PROBE_INPUT"])
task = json.loads((task_folder / "task.json").read_text())
kind = task_folder.name
origin = ROOT / "runs/phase0" / args.generation_run
out = origin / "anchor_cache_audit"
out.mkdir()
start, cpu = time.monotonic(), time.process_time()
BASE = {
    "five_t": "phase0_20261019T011132007923Z_e2_development_pilot",
    "compact_miller": "phase0_20261019T012240915060Z_e2_development_pilot",
    "fvf": "phase0_20261019T013422659988Z_e2_development_pilot",
    "legacy_miller": "phase0_20261019T014057607044Z_e2_development_pilot",
}
base = ROOT / "runs/phase0" / BASE[kind]
cell = task["cell_name"]
record = {"scope": "development_identical_anchor_cache_audit_not_fresh_physical_measurement", "task_id": task["task_id"],
    "source_generation_run": args.generation_run, "physical_acquisition_origin": str(base), "new_DRC_LVS_PEX_SPICE_calls": 0,
    "strict_intent_established": False, "analysis_complete": False, "anchor_development_feasible": False,
    "formal_task_admission": False, "full25_domain_baseline": "pending", "feasible_source_edit_witness": "pending"}


def save():
    record.update(software_audit_wall_seconds=time.monotonic()-start, software_audit_CPU_seconds=time.process_time()-cpu)
    (out / "audit.json").write_text(json.dumps(record, indent=2, allow_nan=False)+"\n")


def compare_geometry(first, second):
    def read(path):
        lib = gdstk.read_gds(str(path))
        top, = lib.top_level()
        top.flatten()
        groups = {}
        for p in top.get_polygons():
            groups.setdefault((p.layer, p.datatype), []).append(p)
        labels = sorted((p.text, tuple(p.origin), p.layer, p.texttype, p.rotation, p.magnification, p.x_reflection) for p in top.labels)
        return lib, groups, labels
    a, ag, al = read(first)
    b, bg, bl = read(second)
    if a.unit != b.unit:
        return False
    return al == bl and all(not gdstk.boolean(ag.get(layer, []), bg.get(layer, []), "xor",
        precision=min(a.precision, b.precision)/a.unit) for layer in set(ag)|set(bg))


try:
    generation = json.loads((origin / "generation.json").read_text())
    geometry = generation["anchor_geometry_equivalence"]
    if generation["task"] != task["task_id"] or not geometry["filled_geometry_equal"] or not geometry["all_labels_equal"]:
        raise ValueError("Actual anchor geometry/labels equivalence is not established")
    record["actual_anchor_geometry_and_labels_equal"] = compare_geometry(origin / "anchor.gds", base / (cell+".gds"))
    if not record["actual_anchor_geometry_and_labels_equal"]:
        raise ValueError("Anchor GDS differs from the saved physical control")
    original = json.loads((base / "candidate_result.json").read_text())
    raw_lvs = base / "lvs/lvs" / cell / (cell+"_lvsmag.spice")
    gold = task_folder / "references/anchor.spice"
    intent = compare_device_intent(raw_lvs.read_text(), gold.read_text())
    record.update(device_intent=intent, strict_intent_established=bool(intent["is_clean"]),
        actual_raw_LVS=str(raw_lvs), independent_flat_gold=str(gold))
    if not intent["is_clean"]:
        record["status"] = "INTENT_MISMATCH_REQUIRES_CONTROL_AUDIT_NOT_AGENT_FAILURE"
        save()
        raise SystemExit(2)
    if not original["DRC"]["completed"] or not original["DRC"]["is_clean"] or not original["LVS"]["is_clean"]:
        raise ValueError("Original actual complete DRC/unique LVS evidence is absent")
    record["positive_full_RC"] = rc_netlist_inventory((base / (cell+"_pex.spice")).read_text(), cell+"_rc", task["ports"])
    if not record["positive_full_RC"]["has_real_RC"]:
        raise ValueError("Actual original positive full RC is absent")
    measures = original["electrical"]
    electrical_origin = base / "electrical"
    if kind == "compact_miller":
        electrical_origin = ROOT / "runs/phase0/phase0_20261018T234515034473Z_custom_ota_miller_schematic"
        measures = json.loads((electrical_origin / "measurements.json").read_text())
        input_gds = ROOT / Path(measures["physical_input"]).relative_to("/work") / (cell+".gds")
        if not compare_geometry(origin / "anchor.gds", input_gds):
            raise ValueError("Complete compact2pF original simulation has different GDS/labels")
        def function(text):
            n = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "measure")
            return ast.get_source_segment(text, n)
        if function((electrical_origin / "custom_ota_miller_schematic.py").read_text()) != function((task_folder / "trusted_bench/original_retained_bench.py").read_text()):
            raise ValueError("Original complete compact simulation function differs from the exact task bench")
        measures = copy.deepcopy(measures)
        measures["results"] = {key: value for key, value in measures["results"].items() if key.endswith("_2pF")}
        record["compact_incomplete_E2_c00_preserved"] = True
        record["shared_original_cost_scope"] = "Complete original run includes both1pF and2pF; only2pF measurements are reused, and whole original CPU/wall is retained without invented proportional allocation."
    spec = importlib.util.spec_from_file_location("trusted_e2_summary", ROOT / "scripts/e2_development_pilot.py")
    sampler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sampler)
    complete, feasible, metrics = sampler.electrical_summary(measures, kind)
    record.update(analysis_complete=complete, anchor_development_feasible=feasible,
        worst_corner_metrics=metrics, electrical_acquisition_origin=str(electrical_origin),
        all_corner_measurements=measures, original_attempt_stage_wall_seconds=original["stage_wall_seconds"],
        original_attempt_total_resource_usage=json.loads((base / "resource_usage.json").read_text()),
        original_electrical_resource_usage=json.loads((electrical_origin / "resource_usage.json").read_text()) if (electrical_origin / "resource_usage.json").is_file() else None)
    record["status"] = "EXACT_ANCHOR_COMPLETE_FEASIBLE_CACHE_CONTROL" if complete and feasible else "EXACT_ANCHOR_COMPLETE_INFEASIBLE_NOT_ADMITTED_TASK" if complete else "INCOMPLETE_CONTROL_NOT_ADMITTED_TASK"
    save()
    print(json.dumps({k: v for k, v in record.items() if k not in ["all_corner_measurements", "device_intent"]}), flush=True)
except SystemExit:
    raise
except Exception as error:
    record.update(status="UNKNOWN_CONTROL_BINDING_NOT_AGENT_FAILURE", error=type(error).__name__+": "+str(error))
    save()
    raise
