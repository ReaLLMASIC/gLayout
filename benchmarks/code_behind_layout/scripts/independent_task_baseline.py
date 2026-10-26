"""Qualify the prepared independent domains with the same isolated GDS gateway."""
import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.component_task_baseline import Baseline
from src.measurement import validate_contract

AC = {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 241, "scale": "log"}
WINDOWS = [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]
DEFINITIONS = {
    "cascode_mirror": {"script": "independent_characterization.py", "function": "corner_run", "opcols": 6,
        "dc": {"kind": "dc", "columns": 5, "start": .05, "end": 1.75, "points": 35, "scale": "linear"}, "trancols": 4,
        "bindings": {"GND": "0", "IREF": "ref", "IOUT": "out", "IBIAS": "bias"},
        "metrics": {"absolute_current_error": ["nominal_relative_current_error", "1", True], "output_resistance": ["output_resistance_ohm", "ohm", False]}},
    "source_follower": {"script": "independent_characterization.py", "function": "corner_run", "opcols": 5,
        "dc": {"kind": "dc", "columns": 5, "start": .9, "end": 1.5, "points": 13, "scale": "linear"}, "trancols": 4,
        "bindings": {"GND": "0", "VDD": "vdd", "VIN": "vin", "VOUT": "out", "IBIAS": "bias"},
        "metrics": {"voltage_gain": ["gain_10Hz_V_per_V", "1", False], "output_impedance": ["output_impedance_10Hz_ohm", "ohm", False], "power": ["power_W", "W", False]}},
    "stacked_switch": {"script": "stacked_switch_probe.py", "function": "measure", "opcols": 4, "trancols": 3,
        "metrics": {"off_leakage": ["maximum_off_leakage_A", "A", False], "settled_tracking_error": ["maximum_loaded_settled_error_V", "V", False], "loaded_gain": ["loaded_dc_gain", "1", False]}},
    "common_source_stage": {"script": "common_source_probe.py", "function": "measure", "opcols": 6, "trancols": 5,
        "dc": {"kind": "dc", "columns": 6, "start": -.01, "end": .01, "points": 21, "scale": "linear"},
        "metrics": {"absolute_gain": ["inverting_gain_10Hz", "1", True], "power": ["DUT_power_W", "W", False], "bandwidth": ["bandwidth_3db_Hz", "Hz", False]}},
    "resistive_diff": {"script": "resistive_diff_probe.py", "function": "measure", "opcols": 9, "trancols": 7,
        "dc": {"kind": "dc", "columns": 9, "start": -.01, "end": .01, "points": 21, "scale": "linear"},
        "metrics": {"differential_gain": ["gain_10Hz", "1", False], "power": ["supply_power_including_reference_W", "W", False], "absolute_imbalance": ["output_imbalance_V", "V", True], "bandwidth": ["bandwidth_3db_Hz", "Hz", False]}}}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def contracts(name):
    definition = DEFINITIONS[name]
    rows = {"op": {"kind": "op", "columns": definition["opcols"], "expected_rows": 1}, "ac": dict(AC)}
    if name == "stacked_switch":
        rows["ac"]["points"] = 161
        rows["on"] = {"kind": "dc", "columns": 3, "start": .05, "end": 1.75, "points": 35, "scale": "linear"}
        rows["off"] = {"kind": "dc", "columns": 3, "start": .2, "end": 1.4, "points": 13, "scale": "linear"}
    else:
        rows["dc"] = definition["dc"]
    if name == "source_follower":
        rows["zout"] = dict(AC)
    rows["transient" if definition["function"] == "corner_run" else "tran"] = {
        "kind": "transient", "columns": definition["trancols"], "start": 0, "end": 4e-6, "required_windows": WINDOWS}
    return rows


class IndependentBaseline(Baseline):
    def summary(self):
        result = super().summary()
        result["source_generation_charged_separately_in"] = self.task["generation_origin"]
        return result

    @classmethod
    def create(cls, preparation, kind):
        source_dir = Path(preparation).resolve() / "private" / kind
        task = json.loads((source_dir / "task.json").read_text())
        if task["formal_admission"] or len(task["configurations"]) != 25:
            raise ValueError("Expected the prepared development domain")
        matches = []
        for path in sorted((ROOT / "runs/phase0").glob("*independent_task_preflight/pilot_manifest.json")):
            manifest = json.loads(path.read_text())
            result = path.parent / "generation.json"
            if manifest.get("input_directory") == str(source_dir) and result.is_file():
                matches.append((path.parent, json.loads(result.read_text())))
        if not matches:
            raise ValueError("No actual generation attempt exists for this source domain")
        origin, generation = matches[-1]
        by_id = {row["configuration_id"]: row for row in generation["rows"] if row["generation_passed"]}
        if set(by_id) != {row["configuration_id"] for row in task["configurations"]}:
            raise ValueError("All twenty-five distinct source-generated GDS inputs are required")
        directory = ROOT / "runs/development/independent_baselines" / (kind + "_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ_") + uuid.uuid4().hex[:8])
        directory.mkdir(parents=True, mode=0o700)
        private = directory / "private"
        private.mkdir()
        (directory / "public").mkdir()
        inputs, references, trusted = [private / name for name in ["inputs", "references", "trusted_common"]]
        for path in [inputs, references, trusted, trusted / "src"]:
            path.mkdir()
        shutil.copyfile(ROOT / "scripts/independent_task_evaluator.py", trusted / "evaluate.py")
        (trusted / "src/__init__.py").write_text("")
        for name in ["physical_drc.py", "report_parsers.py", "measurement.py", "spice_validation.py", "corpus_metrics.py"]:
            shutil.copyfile(ROOT / "src" / name, trusted / "src" / name)
        definition = DEFINITIONS[kind]
        script = ROOT / "scripts" / definition["script"]
        text = script.read_text()
        function = next(node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef) and node.name == definition["function"])
        body = ast.get_source_segment(text, function)
        imports = "import json,time,subprocess,threading\nfrom pathlib import Path\nimport numpy as np\nfrom src.spice_validation import validate_analysis\nfrom src.corpus_metrics import frequency_3db\n"
        (trusted / "bench.py").write_text(imports + "PORTS=" + repr(task["ports"]) + "\n" + body + "\n")
        shutil.copyfile(script, private / "original_verified_bench_script.py")
        save(trusted / "meta.json", {"circuit": kind, "ports": task["ports"], "bench_function": definition["function"],
            "bench_source": definition["script"], "bench_reuse": "Exact AST source segment of the verified function body; stimulation, numerics and formulas unchanged",
            "bindings": definition.get("bindings", {}), "metric_bindings": {key: {"source": values[0], "unit": values[1], "absolute": values[2]} for key, values in definition["metrics"].items()}})
        task.update(preparation_origin=str(Path(preparation).resolve()), generation_origin=str(origin),
                    pdk_revision="0fe599b2afb6708d281543108caf8310912f54af")
        for point in task["configurations"]:
            ident = point["configuration_id"]
            original = Path(by_id[ident]["gds"])
            actual = ROOT / original.relative_to("/work")
            shutil.copyfile(actual, inputs / (ident + ".gds"))
            reference = references / (ident + ".spice")
            shutil.copyfile(point["reference_file"], reference)
            point.update(generation_gds_origin=str(actual), reference_file=str(reference))
            point["contract"].update(analysis_contracts=contracts(kind), immutable_parameters=point["parameters"])
            validate_contract(point["contract"])
        save(private / "task.json", task)
        save(private / "state.json", {"phase": "development_independent_domain_baseline", "status": "CREATED", "points": {},
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "formal_trials": 0, "training_examples": 0})
        return cls(directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--kind", choices=list(DEFINITIONS))
    parser.add_argument("--mode", choices=["anchor", "remaining", "all"], default="anchor")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not args.resume and (not args.preparation or not args.kind):
        parser.error("--resume or both --preparation and --kind are required")
    run = IndependentBaseline(args.resume) if args.resume else IndependentBaseline.create(args.preparation, args.kind)
    if args.mode == "all":
        run.run("anchor", args.workers)
        if run.state["status"] != "PAUSED_UNKNOWN_OR_INFRASTRUCTURE":
            run.run("remaining", args.workers)
    else:
        run.run(args.mode, args.workers)
