#!/usr/bin/env python3
"""New draft metadata for stronger P; unchanged initial artifacts are adopted."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.e3_parameters import interface
from scripts.e3_task_prepare import save


def expand(original, output, generation_summary=None):
    original, output = original.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Never overwrite a draft parameter-domain version")
    shutil.copytree(original, output)
    first = json.loads(next((original/"private").glob("*/task.json")).read_text())
    e1_root = Path(first["E1_binding"]).parents[2]
    pdk_path = e1_root/"public/pdk.json"
    pdk = json.loads(pdk_path.read_text())
    adoption = []
    for filename in sorted((output/"private").glob("draft_E3_*/task.json")):
        task = json.loads(filename.read_text());old = json.loads((original/filename.relative_to(output)).read_text())
        def moved(value):
            return str(output/Path(value).relative_to(original))
        for field in ("source_overrides", "frozen_source_overrides"):
            task[field] = {key: moved(value) for key, value in task[field].items()}
        task["parameter_baseline"]["immutable_original_module"] = moved(task["parameter_baseline"]["immutable_original_module"])
        task["ancestry"]["initial_patch"] = moved(task["ancestry"]["initial_patch"])
        for key in ("original_generator", "patch"):
            task["export_transport"][key] = moved(task["export_transport"][key])
        domain = interface(task["target"], pdk)
        task["expanded_parameter_baseline"] = {**domain, "renderer": "src.e3_parameters.render",
            "immutable_original_module": task["parameter_baseline"]["immutable_original_module"],
            "frozen_PDK_rules": str(pdk_path), "primary_P_explanation": True,
            "declaration_reason": "Wider prospective grid over the same existing layout knobs; no new physical outcomes used to choose endpoints"}
        save(filename, task)
        view_path = output/"public"/task["task_id"]/"packet.json"
        view = json.loads(view_path.read_text())
        view["documents"]["parameter_baseline"] = {"version": domain["version"],
            "parameters": {key: {field: row[field] for field in ("min", "max", "step", "unit")} for key, row in domain["parameters"].items()},
            "current_values": task["parameter_controls"],
            "endpoint_policy": "Physical failures remain in the budget; no device dimensions or intended nets may change"}
        save(view_path, view)
        source_equal = all(Path(task["source_overrides"][key]).read_bytes() == Path(value).read_bytes() for key, value in old["source_overrides"].items())
        wrapper_equal = all(Path(task["frozen_source_overrides"][key]).read_bytes() == Path(value).read_bytes() for key, value in old["frozen_source_overrides"].items())
        if not source_equal or not wrapper_equal or task["configurations"] != old["configurations"]:
            raise ValueError("Metadata-only P expansion changed an initial source, wrapper, or N/contract domain")
        adoption.append({"task_id": task["task_id"], "source_bytes_unchanged": source_equal,
            "frozen_export_bytes_unchanged": wrapper_equal, "all25_reference_contract_bindings_unchanged": True})
    report = {"scope": "prospective_E3_expanded_parameter_grid_metadata_only", "old_preparation": str(original),
        "preparation": str(output), "adopted_initial_generation": str(generation_summary) if generation_summary else None,
        "adoption_reason": "Initial full source, export wrapper, and every reference/contract/configuration are unchanged; only P's prospective search space is wider",
        "tasks": adoption, "all_initial_artifacts_unchanged": len(adoption) == 24,
        "new_physical_calls": 0, "new_model_calls": 0, "formal_trials": 0}
    summary = json.loads((output/"summary.json").read_text())
    summary.update(preparation=str(output), expanded_parameter_baseline="prospective_expanded_layout_grid_v1",
        prior_parameter_metadata=str(original), initial_artifact_adoption=report)
    save(output/"summary.json", summary);save(output/"public/inventory.json", summary)
    save(output/"public/parameter_expansion.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "tasks"}), flush=True)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__);p.add_argument("--preparation", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True);p.add_argument("--generation-summary", type=Path)
    a = p.parse_args();expand(a.preparation, a.output, a.generation_summary)
