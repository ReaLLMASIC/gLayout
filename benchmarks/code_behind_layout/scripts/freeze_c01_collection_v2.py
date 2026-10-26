"""Freeze the declared full-source C01 collection without changing v1."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def freeze(preparation):
    prep = json.loads(preparation.read_text())
    base_path = Path(prep["base_collection_manifest"])
    base = json.loads(base_path.read_text())
    preflight_path = preparation.parent / "teacher_context_preflight.json"
    preflight = json.loads(preflight_path.read_text())
    if (prep["collection_id"] != "c01_collection_v2" or base["status"] != "frozen"
            or prep["sampling"]["mode"] != "train_collection_source"
            or not preflight["fits_complete_request"] or not preflight["fits_original_module_output"]
            or preflight["truncation"] or preflight["GPU_inferences"] != 0):
        raise ValueError("Freeze the declared prospectively checked full-source teacher only")
    states = [json.loads(line) for line in Path(prep["initial_states_path"]).read_text().splitlines() if line.strip()]
    if (len(states) != 3 or len({row["initial_state_id"] for row in states}) != 3
            or any(list(row["base_source"]) != ["textbook_sharing/layout.py"] for row in states)
            or len(prep["gold_controls"]) != 9):
        raise ValueError("Expected the declared three complete natural initial states and nine positive controls")
    output = ROOT / "runtime/train_collections/c01_collection_v2"
    output.mkdir()
    for name in ["registry.json", "label_rule.json"]:
        shutil.copyfile(base_path.parent / name, output / name)
    shutil.copyfile(preparation, output / "preparation.json")
    shutil.copyfile(preflight_path, output / "teacher_context_preflight.json")
    (output / "initial_states.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in states))
    manifest = {**base, **prep, "status": "frozen", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "registry_path": str(output / "registry.json"), "label_rule_path": str(output / "label_rule.json"),
        "initial_states_path": str(output / "initial_states.jsonl"),
        "output_root": str(ROOT / "runs/train_collection/c01_collection_v2"),
        "evidence_root": str(ROOT / "runs/train_collection/c01_collection_v2"),
        "context": "Complete layout module, frozen circuit/domain contract and actual fresh baseline feedback; no truncation.",
        "deduplication_scope": "Within initial state; separately report unique final programs across all states.",
        "admission": "Fresh train-only proposals and fresh nine-point baselines for all three initial states; v1 controls only establish evaluator validity. Prior development outcomes are not labels."}
    save(output / "collection.json", manifest)
    # The study explicitly requires immutable, identified protocol snapshots.
    save(output / "freeze_identity.json", {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in ["collection.json", "registry.json", "label_rule.json", "initial_states.jsonl", "preparation.json", "teacher_context_preflight.json"]})
    for path in output.iterdir():
        path.chmod(0o444)
    output.chmod(0o555)
    return {"collection": str(output / "collection.json"), "status": "frozen", "formal_collection_launched": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, required=True)
    print(json.dumps(freeze(parser.parse_args().preparation)))
