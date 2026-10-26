"""Freeze qualified train-only circuit domains without modifying earlier freezes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.collect_training import load
from src.measurement import validate_contract
from src.training import frozen_train_registry


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def freeze(preparation, kind):
    declared = json.loads(preparation.read_text())
    rule = kind == "rules"
    capsule_path = Path(declared["capsule_preparation"])
    capsule = json.loads(capsule_path.read_text())
    cid = declared["circuit_id"]
    if cid not in (["C01", "C05", "C08"] if rule else ["C05", "C08"]):
        raise ValueError("This revision covers only the declared qualified train circuits")
    base_path = ROOT / "runtime/train_collections/c01_collection_v1/collection.json"
    base = json.loads(base_path.read_text())
    registry = json.loads(Path(base["registry_path"]).read_text())
    if cid == "C01":
        capsule = {**capsule, "source_pack": base["source_pack"], "trusted_bundle": base["trusted_bundle"],
            "label_rule_draft": json.loads(Path(base["label_rule_path"]).read_text()),
            "configurations": [{**point, "role": point["domain_role"]} for point in registry["configurations"]]}
    if base["status"] != "frozen":
        raise ValueError("The original train assignment and source capsule must already be frozen")
    states = [json.loads(line) for line in Path(declared["initial_states_path"]).read_text().splitlines() if line.strip()]
    if len(states) != (1 if rule else 3) or len(capsule["configurations"]) != 9:
        raise ValueError("Expected the declared complete states and nine configurations")
    if Path(capsule["source_pack"]).resolve() != Path(base["source_pack"]).resolve():
        raise ValueError("This train revision reuses the same byte-exact public compiler capsule")
    calibration = None
    if cid != "C01":
        calibration = json.loads((ROOT / "results/derived" / (cid.lower() + "_collection_draft_matrix_calibration.json")).read_text())
        if not (calibration["status"] == "EVALUATED" and calibration["assessment"]["S2"]
                and calibration["point_evaluation_complete"] and calibration["context_fits"]
                and calibration["source_complete"] and calibration["input_tokens"] + 3072 <= 8192):
            raise ValueError("The final complete domain packet and physical wrapper must actually pass calibration")
    collection_id = declared["collection_id"] if rule else cid.lower() + "_collection_v1"
    output = ROOT / "runtime/train_collections" / collection_id
    output.mkdir()
    trusted = output / "trusted"
    shutil.copytree(capsule["trusted_bundle"], trusted)
    for path in trusted.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    trusted.chmod(0o755)
    points = []
    for item in capsule["configurations"]:
        short = item["configuration_id"]
        prefix = "train_" + cid.lower() + "_"
        name = short if short.startswith(prefix) else prefix + short
        contract = json.loads(json.dumps(item["contract"]))
        contract.update(configuration_id=name, scope="frozen_prospective_train_collection_" + collection_id)
        validate_contract(contract)
        parameters = {**item["parameters"], "configuration_id": name}
        (trusted / "contracts" / (short + ".json")).unlink()
        save(trusted / "contracts" / (name + ".json"), contract)
        (trusted / "references" / (short + ".spice")).rename(trusted / "references" / (name + ".spice"))
        points.append({"configuration_id": name, "parent_lineage": capsule["parent_lineage"],
            "split": "train", "role": "train_development", "domain_role": item["role"],
            "reference_id": item["reference_id"], "parameters": parameters, "contract": contract})
    trusted_files = {str(path.relative_to(trusted)): path.read_text() for path in sorted(trusted.rglob("*")) if path.is_file()}
    for point in points:
        point["trusted_evaluator_files"] = trusted_files
    registry.update(configurations=points, freeze_scope="unchanged_source_assignments_and_" + collection_id,
        frozen_at_utc=datetime.now(timezone.utc).isoformat(), main_benchmark_protocol_status="draft")
    frozen_train_registry(registry)
    labels = {**capsule["label_rule_draft"], "status": "frozen", "version": collection_id + "_area_v1",
        "coverage_absolute_tolerance": 0.0,
        "family_quality_aggregation": "arithmetic_mean_of_same_unit_per_configuration_worst_corner_objectives"}
    task_id = points[0]["contract"]["task_id"]
    for state in states:
        if list(state["base_source"]) != ["textbook_sharing/layout.py"] or state["origin"] != "natural":
            raise ValueError("Only the complete declared natural layout module is editable")
        state["task_id"] = task_id
    initial = output / "initial_states.jsonl"
    initial.write_text("".join(json.dumps(state, ensure_ascii=False) + "\n" for state in states))
    if states[0]["base_source"]["textbook_sharing/layout.py"] != (Path(base["source_pack"]) / "textbook_sharing/layout.py").read_text():
        raise ValueError("Fresh gold controls must be obtained from the unmodified original first")
    if rule:
        shutil.copyfile(declared["rule_proposer_path"], output / "rule_proposer.py")
        sampling = {"mode": "train_collection_rules", "backend": "frozen_rule_proposer",
            "rule_ids": declared["rule_ids"], "rule_proposer_path": str(output / "rule_proposer.py"),
            "model": None, "seed": None, "max_new_tokens": 0, "max_context_tokens": 8192, "timeout_seconds": 5}
    else:
        sampling = {"variant": "T0", "mode": "train_collection_source", "proposal_format": "full_source_teacher",
            "seeds": [101, 241, 379, 503, 617, 743, 857, 971], "temperature": .7, "top_p": .95,
            "max_new_tokens": 3072, "max_context_tokens": 8192, "timeout_seconds": 240}
    save(output / "registry.json", registry)
    save(output / "label_rule.json", labels)
    save(output / "preparation.json", declared)
    save(output / "capsule_preparation.json", capsule)
    if calibration:
        save(output / "calibration.json", calibration)
    manifest = {**base, "collection_id": collection_id, "frozen_at_utc": registry["frozen_at_utc"],
        "registry_path": str(output / "registry.json"), "label_rule_path": str(output / "label_rule.json"),
        "trusted_bundle": str(trusted), "initial_states_path": str(initial),
        "output_root": str(ROOT / "runs/train_collection" / collection_id),
        "evidence_root": str(ROOT / "runs/train_collection" / collection_id), "sampling": sampling,
        "physical": {**base["physical"], "workers": 1},
        "budget": {**base["budget"], "initial_batch_initial_states": len(states)},
        "source_smoke_evidence": calibration["run_directory"] if calibration else base["source_smoke_evidence"],
        "admission": "Fresh nine-point baseline per state and fresh proposals under this frozen contract. Old development outcomes are excluded. One compiler lineage across all train topologies.",
        "source_scope": "Only layout.py is editable in these states; the original complete enumeration module remains byte-exact and frozen for each candidate.",
        "deduplication_scope": "Within state; separately report unique final AST programs across states, circuits and proposal sources.",
        "teacher_kind": "deterministic_rules" if rule else "T0", "old_outcomes_relabelled": False}
    save(output / "collection.json", manifest)
    names = ["collection.json", "registry.json", "label_rule.json", "initial_states.jsonl", "preparation.json", "capsule_preparation.json"]
    names += ["rule_proposer.py"] if rule else []
    names += ["calibration.json"] if calibration else []
    save(output / "freeze_identity.json", {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in names})
    load(output / "collection.json")
    for path in sorted(output.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    output.chmod(0o555)
    return {"collection": str(output / "collection.json"), "status": "frozen", "states": len(states), "points": len(points), "launched": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--kind", choices=["rules", "T0"], required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.preparation, args.kind)))
