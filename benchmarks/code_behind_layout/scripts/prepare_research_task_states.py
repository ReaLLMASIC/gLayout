"""Materialize five original and three actual historical natural task sources."""
import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
HISTORY = [
    ("cascode_mirror", "phase0_20261019T013235442458Z_independent_characterization", "natural_body_short"),
    ("cascode_mirror", "phase0_20261019T013538845555Z_independent_characterization", "natural_output_pin_open"),
    ("source_follower", "phase0_20261019T013159285117Z_independent_characterization", "natural_body_short")]


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def prepare(preparation):
    if not (ROOT / "runtime/GLdev").is_dir():
        raise ValueError("Private task domains remain on the execution host")
    out = ROOT / "runtime/task_preparation" / ("research_states_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    (out / "private").mkdir(parents=True, mode=0o700)
    (out / "public").mkdir()
    definitions = [(kind, None, "natural_original_quality") for kind in
        ["cascode_mirror", "source_follower", "stacked_switch", "common_source_stage", "resistive_diff"]] + HISTORY
    index = []
    for kind, historical_run, label in definitions:
        parent = preparation / "private" / kind
        task = json.loads((parent / "task.json").read_text())
        ident = kind + "__" + label
        directory = out / "private" / ident
        directory.mkdir()
        source = directory / "source_pack"
        shutil.copytree(task["source_pack"], source)
        for path in source.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        source.chmod(0o755)
        target = task["editable_paths"][0]
        if historical_run:
            old = ROOT / "runs/phase0" / historical_run
            actual = old / (kind + ".py")
            shutil.copyfile(actual, source / target)
            reference_name = kind + "_reference.py"
            if (old / reference_name).read_bytes() != (ROOT / "src/generators" / reference_name).read_bytes():
                raise ValueError("Historical intended reference differs; examine this actual change before admission")
            shutil.copyfile(old / reference_name, directory / "historical_independent_reference.py")
            if (source / target).read_text() == (parent / "source_pack" / target).read_text():
                raise ValueError("A historical state must differ from the repaired source")
            origin = {"kind": "byte_exact_actual_executed_development_source", "run_directory": str(old),
                "source_file": str(actual), "historical_reference_unchanged": True,
                "new_fault_injection": False, "prior_outcomes_relabelled_formal": False}
        else:
            origin = {"kind": "unmodified_independently_authored_qualified_generator", "run_directory": task["default_qualification"],
                "quality_status": "Clean baseline under prospective area minimization; meaningful improvement witness remains to be established"}
        tree = ast.parse((source / target).read_text())
        build = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build")
        if len(build.args.args) < 2 or len(build.args.args) - len(build.args.defaults) > 2:
            raise ValueError("Preserve the complete original parameterized builder; no rewritten compatibility source")
        task.update(initial_state_id=ident, task_id="draft_" + ident, source_pack=str(source), origin="natural",
            source_ancestry=origin, initial_state_scope="complete unchanged original or actual historical module",
            source_snapshot={target: (source / target).read_text()}, formal_admission=False,
            fresh_anchor_status="pending", full_domain_baseline="pending", base_domain=str(parent))
        # References, sizing and contracts remain private, exact, and independent
        # of the historical source state. This is not a new circuit lineage.
        save(directory / "task.json", task)
        public = {key: value for key, value in task.items() if key not in ["configurations", "source_files"]}
        public.update(visible_configurations=task["configurations"][:9], hidden_configuration_count=16)
        save(out / "public" / (ident + ".json"), public)
        index.append({"initial_state_id": ident, "parent_lineage": task["parent_lineage"], "origin": "natural",
            "historical_run": historical_run, "new_physical_calls": 0, "formal_trials": 0})
    save(out / "summary.json", {"status": "DRAFT_NOT_FORMAL_TASK_FREEZE", "states": index,
        "source_lineages": 5, "initial_states": 8, "actual_historical_states": 3,
        "private_details_exportable": False, "formal_trials": 0})
    return {"preparation": str(out), "states": len(index), "status": "DRAFT", "new_physical_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().preparation)))
