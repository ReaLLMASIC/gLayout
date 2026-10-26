#!/usr/bin/env python3
"""Actual isolated anchor generation for 24 draft editing initial states.

This establishes single-GDS export and geometric distinctness only. It does
not run DRC/LVS/PEX/SPICE or admit a natural/clean-but-poor research task.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.candidate_executor import CandidateExecutor
from scripts.e3_task_prepare import capsule, save

EVALUATOR = '''import argparse,json,pathlib
import gdstk
p=argparse.ArgumentParser();p.add_argument("--gds");p.add_argument("--output");p.add_argument("--fidelity");a=p.parse_args()
configuration=json.loads(pathlib.Path("/configuration.json").read_text())
library=gdstk.read_gds(a.gds);matches=[c for c in library.cells if c.name==configuration["top_cell"]]
if len(matches)!=1:raise ValueError("Contract named top is not unique")
top=matches[0];box=top.bounding_box()
if box is None:raise ValueError("Empty geometry")
scale=library.unit/1e-6
record={"scope":"geometry_only_no_S1_S2", "actual_top":top.name,"units_m":library.unit,"precision_m":library.precision,
 "bbox_um":[[float(v)*scale for v in row] for row in box],
 "area_um2":float((box[1][0]-box[0][0])*(box[1][1]-box[0][1]))*scale**2,
 "recursive_polygon_count":len(top.get_polygons()),"DRC_run":False,"LVS_run":False,"SPICE_run":False}
pathlib.Path(a.output,"validation.json").write_text(json.dumps(record,indent=2)+"\\n")
'''


def gate(timeout=600):
    import psutil
    began = time.monotonic()
    while True:
        busy = psutil.cpu_percent(interval=1)*(psutil.cpu_count() or 1)/100
        used = (psutil.virtual_memory().total-psutil.virtual_memory().available)/1024**3
        if busy+2 <= 24 and used <= 190:
            return {"busy_cores_before_launch": busy, "RAM_used_GiB": used,
                    "gate_wait_wall_seconds": time.monotonic()-began}
        if time.monotonic()-began > timeout:
            raise TimeoutError("Resource gate remained closed; no candidate dispatched")
        time.sleep(15)


def same_geometry(first, second, top_name):
    import gdstk
    def layers(path):
        lib = gdstk.read_gds(path)
        top = next(cell for cell in lib.cells if cell.name == top_name)
        top.flatten();box = top.bounding_box()
        result = {}
        for polygon in top.polygons:
            polygon.translate(-box[0][0],-box[0][1])
            result.setdefault((polygon.layer, polygon.datatype), []).append(polygon)
        return result
    left, right = layers(first), layers(second)
    return not any(gdstk.boolean(left.get(layer, []), right.get(layer, []), "xor", precision=.001)
                   for layer in set(left)|set(right))


def run(preparation, output):
    output.mkdir(parents=True, exist_ok=False)
    trusted = output/"geometry_evaluator";trusted.mkdir()
    (trusted/"evaluate.py").write_text(EVALUATOR)
    tasks = sorted((preparation/"private").glob("draft_E3_*/task.json"))
    if len(tasks) != 24:
        raise ValueError("Expected exactly 24 complete draft initial states")
    records = []
    started = time.monotonic()
    for task_path in tasks:
        task = json.loads(task_path.read_text());work = output/task["task_id"];work.mkdir()
        resources = gate()
        source = work/"source_capsule";binding = capsule(task_path, source)
        physical = work/"physical";physical.mkdir()
        result = CandidateExecutor(ROOT/"runtime/GLdev", physical, ROOT/"runtime/magic-8.3.685", timeout=180).execute(
            source_dir=source, source_paths=binding["source_files"], entrypoint=binding["entrypoint"], representation="G2",
            configuration={"parameters": task["configurations"][0]["parameters"], "top_cell": task["top_cell"]},
            trusted_dir=trusted, trusted_paths=["evaluate.py"], fidelity="geometry",
            phase="development_E3_initial_generation_qualification",
            context={"source_role": "engineering_initial_state_control", "task_id": task["task_id"], "configuration_id": "anchor"},
            generation_timeout_seconds=180, evaluator_timeout_seconds=30)
        record = {"task_id": task["task_id"], "target": task["target"], "task": str(task_path),
                  "result": result, "resources": resources}
        records.append(record)
        save(output/"progress.json", {"completed": len(records), "declared": 24, "records": records})
        print(json.dumps({"completed": len(records), "task_id": task["task_id"], "status": result["status"]}), flush=True)
    distinct = []
    for target in sorted({record["target"] for record in records}):
        group = [record for record in records if record["target"] == target]
        success = all(record["result"]["status"] == "EVALUATED" for record in group)
        pair_rows = []
        if success:
            for index, first in enumerate(group):
                for second in group[index+1:]:
                    name = json.loads(Path(first["task"]).read_text())["top_cell"]
                    same = same_geometry(Path(first["result"]["run_directory"])/"accepted/candidate.gds",
                        Path(second["result"]["run_directory"])/"accepted/candidate.gds", name)
                    pair_rows.append({"first": first["task_id"], "second": second["task_id"], "same_filled_geometry": same})
        distinct.append({"target": target, "three_single_GDS_outputs": success,
                         "three_distinct_filled_geometries": success and not any(row["same_filled_geometry"] for row in pair_rows),
                         "comparison": "All layers Boolean XOR after common translation removal; names/labels excluded", "pairs": pair_rows})
    report = {"scope": "development_E3_complete_module_generation_only_not_S1_S2", "preparation": str(preparation),
        "status": "COMPLETE", "declared_states": 24, "evaluated_states": sum(r["result"]["status"] == "EVALUATED" for r in records),
        "targets": distinct, "records": records, "elapsed_wall_seconds": time.monotonic()-started,
        "model_calls": 0, "DRC_calls": 0, "LVS_calls": 0, "SPICE_calls": 0, "formal_trials": 0,
        "initial_electrical_feasibility_established": False, "natural_shortfall_admission_established": False}
    save(output/"summary.json", report)
    print(json.dumps({"summary": str(output/"summary.json"), "evaluated_states": report["evaluated_states"], "targets": distinct}), flush=True)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__);p.add_argument("--preparation", required=True, type=Path)
    p.add_argument("--output", type=Path)
    a = p.parse_args();out = a.output or ROOT/"runs/development/E3_generation_qualification"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run(a.preparation, out)
