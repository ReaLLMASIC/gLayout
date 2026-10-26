"""Freeze the specified isolated GPT proposal branch before its first request."""
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
    flight_path = preparation.parent / "teacher_context_preflight.json"
    flight = json.loads(flight_path.read_text())
    sampling = prep["sampling"]
    if (prep["collection_id"] != "c01_gpt_teacher_v1" or base["status"] != "frozen"
            or sampling["mode"] != "train_collection_source_gpt"
            or sampling["model"] != "gpt-6.1-sol" or sampling["reasoning_effort"] != "high"
            or sampling["trials"] != list(range(1, 9)) or sampling["proposal_workers"] != 2
            or sampling["seed"] is not None or flight["truncated"]
            or flight["GPT_requests"] != 0 or flight["total_context_tokens"] > 8192):
        raise ValueError("Freeze only the declared fresh, tool-disabled, complete-source GPT branch")
    states = Path(prep["initial_states_path"]).read_text()
    if len([line for line in states.splitlines() if line.strip()]) != 3 or len(prep["gold_controls"]) != 9:
        raise ValueError("Expected three real initial states and nine declared evaluator controls")
    output = ROOT / "runtime/train_collections/c01_gpt_teacher_v1"
    output.mkdir()
    for name in ["registry.json", "label_rule.json"]:
        shutil.copyfile(base_path.parent / name, output / name)
    shutil.copyfile(preparation, output / "preparation.json")
    shutil.copyfile(flight_path, output / "teacher_context_preflight.json")
    (output / "initial_states.jsonl").write_text(states)
    manifest = {**base, **prep, "status": "frozen", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "registry_path": str(output / "registry.json"), "label_rule_path": str(output / "label_rule.json"),
        "initial_states_path": str(output / "initial_states.jsonl"),
        "output_root": str(ROOT / "runs/train_collection/c01_gpt_teacher_v1"),
        "evidence_root": str(ROOT / "runs/train_collection/c01_gpt_teacher_v1"),
        "admission": "Fresh independent GPT proposals and fresh nine-point baselines; same frozen physical contracts, source capsule and label rule as T0 v2. Native tools disabled, no manual source repair, all failed requests retained."}
    save(output / "collection.json", manifest)
    save(output / "freeze_identity.json", {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in ["collection.json", "registry.json", "label_rule.json", "initial_states.jsonl", "preparation.json", "teacher_context_preflight.json"]})
    for path in output.iterdir():
        path.chmod(0o444)
    output.chmod(0o555)
    return {"collection": str(output / "collection.json"), "status": "frozen", "GPT_requests": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, required=True)
    print(json.dumps(freeze(parser.parse_args().preparation)))
