"""Freeze the prospective C01 collection; the main benchmark remains draft.

Run on the physical execution host after the updated isolated capsule smoke.
No old development evidence is changed or admitted by this command.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.measurement import validate_contract
from src.training import frozen_train_registry


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def freeze(preparation, calibration, collection_id):
    prep = json.loads(preparation.read_text())
    smoke = json.loads(calibration.read_text())
    physical = smoke["physical_result"]
    if (smoke["status"] != "EVALUATED" or not physical["assessment"]["S2"]
            or not physical["analysis_complete"] or not physical.get("point_evaluation_complete")):
        raise ValueError("An actual isolated complete-point smoke of the final evaluator is required")
    if len(prep["configurations"]) != 9 or len(prep["editable_paths"]) != 2:
        raise ValueError("This collection freezes the declared two-module nine-point C01 domain")
    registry_path = ROOT / "data/splits/registry.json"
    registry = json.loads(registry_path.read_text())
    if registry.get("status") != "draft":
        raise ValueError("Preserve an earlier freeze; a subsequent collection needs an explicit new revision")
    output = ROOT / "runtime/train_collections" / collection_id
    if output.exists():
        raise ValueError("Collection already exists; preserve its original prospective freeze")
    output.mkdir(parents=True)
    source, trusted = output / "source_pack", output / "trusted"
    shutil.copytree(prep["source_pack"], source)
    shutil.copytree(prep["trusted_bundle"], trusted)
    for path in trusted.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    trusted.chmod(0o755)
    configurations = []
    for point in prep["configurations"]:
        short = point["configuration_id"]
        name = "train_c01_" + short
        contract = point["contract"]
        contract.update(configuration_id=name, scope="frozen_prospective_train_collection_C01_v1")
        validate_contract(contract)
        parameters = {**point["parameters"], "configuration_id": name}
        old_contract = trusted / "contracts" / (short + ".json")
        old_reference = trusted / "references" / (short + ".spice")
        old_contract.unlink()
        save(trusted / "contracts" / (name + ".json"), contract)
        old_reference.rename(trusted / "references" / (name + ".spice"))
        configurations.append({"configuration_id": name, "parent_lineage": prep["parent_lineage"],
            "split": "train", "role": "train_development", "domain_role": point["role"],
            "reference_id": point["reference_id"], "parameters": parameters, "contract": contract})
    trusted_files = {str(path.relative_to(trusted)): path.read_text() for path in sorted(trusted.rglob("*")) if path.is_file()}
    for point in configurations:
        point["trusted_evaluator_files"] = trusted_files
    assignment = next(row for row in registry["lineages"] if row["lineage_id"] == prep["parent_lineage"])
    assignment.update(editable_paths=prep["editable_paths"], editable_paths_status="frozen_collection_v1_complete_modules",
        frozen_source_pack=str(source), frozen_source_files=sorted(set(prep["source_files"])-set(prep["editable_paths"])),
        source_scope_note="Complete layout.py and enumeration.py are editable; every other exact source-pack file is frozen. Libraries/binaries do not enter the model context.")
    assignment.pop("frozen_common_api_paths", None)
    registry.update(status="frozen", freeze_scope="source_assignments_and_C01_train_collection_v1",
        frozen_at_utc=datetime.now(timezone.utc).isoformat(), configurations=configurations,
        main_benchmark_protocol_status="draft", formal_data_ready=False)
    frozen_train_registry(registry)
    labels = {**prep["label_rule_draft"], "status": "frozen", "version": "C01_area_v1",
              "coverage_absolute_tolerance": 0.0,
              "family_quality_aggregation": "arithmetic_mean_of_same_unit_per_configuration_worst_corner_objectives"}
    initial_state = {"initial_state_id": "c01_original_compiler_collection_v1", "parent_lineage": prep["parent_lineage"],
        "origin": "natural", "ancestry": {"source_revision": prep["source_revision"], "kind": "unmodified_public_compiler"},
        "base_source": {name: (source/name).read_text() for name in prep["editable_paths"]}}
    (output / "initial_states.jsonl").write_text(json.dumps(initial_state, ensure_ascii=False) + "\n")
    save(output / "registry.json", registry)
    save(output / "label_rule.json", labels)
    manifest = {"status": "frozen", "role": "train_collection", "collection_id": collection_id,
        "frozen_at_utc": registry["frozen_at_utc"], "registry_path": str(output/"registry.json"),
        "label_rule_path": str(output/"label_rule.json"), "trusted_bundle": str(trusted), "source_pack": str(source),
        "initial_states_path": str(output/"initial_states.jsonl"), "output_root": str(ROOT/"runs/train_collection"/collection_id),
        "evidence_root": str(ROOT/"runs/train_collection"/collection_id),
        "source_smoke_evidence": smoke["run_directory"], "main_benchmark_protocol_status": "draft",
        "pdk_revision": "0fe599b2afb6708d281543108caf8310912f54af",
        "container_image": "hpretl/iic-osic-tools@sha256:7ef29be71a33b5b8994cde7f7476dfefd1af94f2922354242d1579346feec462",
        "magic_runtime": str(ROOT/"runtime/magic-8.3.685"),
        "sampling": {"variant": "T0", "mode": "train_collection", "seeds": [101, 241, 379, 503, 617, 743, 857, 971],
                     "temperature": .7, "top_p": .95, "max_new_tokens": 1024, "max_context_tokens": 8192, "timeout_seconds": 60},
        "physical": {"workers": 4, "cpus_per_job": 2, "generation_timeout_seconds": 240, "evaluator_timeout_seconds": 720},
        "budget": {"proposals_per_initial_state": 8, "configurations_per_candidate": 9,
                   "effective_example_pipeline_pilot_target": 1000, "initial_batch_initial_states": 1},
        "failure_policy": "Keep all attempts, duplicate/noop/invalid patches, candidate failures, infrastructure failures and measured costs; unknowns never become physical negatives.",
        "admission": "Prospective train-only evidence under frozen contracts; exact same source patch on all nine points. Old development data are not relabeled.",
        "context": "Full editable modules, compact complete circuit/domain contract and visible feedback; reject oversize without truncating source or contract."}
    save(output / "collection.json", manifest)
    shutil.copyfile(preparation, output / "preparation.json")
    # This digest is the explicit protocol snapshot identity required by the study.
    save(output / "freeze_identity.json", {name: hashlib.sha256((output/name).read_bytes()).hexdigest()
         for name in ("collection.json", "registry.json", "label_rule.json", "initial_states.jsonl")})
    save(registry_path, registry)
    for path in sorted(output.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    output.chmod(0o555)
    return {"collection": str(output/"collection.json"), "registry": str(registry_path),
            "configurations": len(configurations), "formal_training_examples": 0, "collection_launched": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--collection-id", default="c01_collection_v1")
    args = parser.parse_args()
    print(json.dumps(freeze(args.preparation, args.calibration, args.collection_id)))
