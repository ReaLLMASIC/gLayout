"""Eight fixed nondefault E2 independent physical controls, development only.

No sizing search: each point is the already declared schematic-control N(z).
The two research benches require explicit calibrated serial-corner templates.
Unknown controls pause the queue; completed electrical failures stay failures.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.candidate_executor import CandidateExecutor
from src.domain_runner import inspect_point, source_contents
from scripts.archive_e2_run import archive
from scripts.e2_execution import COPY, measured_cost, resource_gate, write
from scripts.e2_stage_prepare import build, cached


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--five-t-serial", type=Path, required=True)
    p.add_argument("--compact-serial", type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    a = p.parse_args()
    manifest = json.loads(a.manifest.read_text())
    if a.resume:
        state = json.loads((a.output / "state.json").read_text())
        if any(not row["point_evaluation_complete"] for row in state["points"]):
            raise ValueError("An unknown physical control requires separate diagnosis, not an automatic retry")
        for row in state["points"]:
            for stage in row["stage_executions"]:
                stage["raw_archive"] = archive(stage["run_directory"], retain_accepted_gds=stage["stage"] == "source_to_geometry")
        state["status"] = "RUNNING_AFTER_ARCHIVE_ONLY_RECOVERY_NO_PHYSICAL_RETRY"
    else:
        a.output.mkdir(parents=True, exist_ok=False)
        state = {"scope": "development_8_fixed_nondefault_E2_full_physical_controls_NOT_FORMAL",
        "source_manifest": str(a.manifest.resolve()), "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING", "planned": 8, "points": []}
    write(a.output / "state.json", state)
    executor = CandidateExecutor(ROOT / "runtime/GLdev", a.output / "physical", ROOT / "runtime/magic-8.3.685", timeout=5400)
    for pool in manifest["pools"]:
        if pool["sizing_id"] == "s1" or pool["pool_id"] in {row["pool_id"] for row in state["points"]}:
            continue
        family = pool["source_family"]
        point = json.loads(Path(pool["point"]).read_text())
        work = a.output / "inputs" / pool["pool_id"]
        trusted = work / "trusted"
        shutil.copytree(pool["full_trusted"], trusted)
        if family in ["five_t", "compact_miller"]:
            serial = a.five_t_serial if family == "five_t" else a.compact_serial
            binding = json.loads((serial / "binding.json").read_text())
            if binding["kind"] != family or not binding["measurement_function_source_identical"]:
                raise ValueError("Serial-corner calibration belongs to another immutable bench")
            shutil.copyfile(serial / "trusted_bench/original_retained_bench.py", trusted / "original_bench.py")
            write(work / "scheduling_binding.json", binding)
        else:
            # FVFs retain180s; the separately predeclared legacy15p/20us
            # control retained900s. Never silently inherit a shorter limit.
            point["contract"]["analysis_timeout_s"] = 900 if family == "legacy_miller" else 180
        shutil.copyfile(ROOT / "scripts/ota_frozen_bench.py", trusted / "ota_frozen_bench.py")
        write(trusted / "contract.json", point["contract"])
        write(work / "point.json", point)
        stages = []
        def execute(source, source_paths, stage_trusted, files, fidelity, stage):
            wait_started = time.monotonic()
            sample = resource_gate()
            queue_wall = time.monotonic()-wait_started
            result = executor.execute(source_dir=source, source_paths=source_paths, entrypoint="generator.py",
                representation="G2" if stage == "source_to_geometry" else "G0", configuration={"parameters": point["parameters"]},
                trusted_dir=stage_trusted, trusted_paths=files, fidelity=fidelity,
                phase="development_E2_nondefault_sizing_physical_control",
                context={"source_role": "trusted_evaluator_control", "pool_id": pool["pool_id"], "stage": stage,
                "configuration_id": point["configuration_id"], "reference_id": point["reference_id"],
                "source_manifest": str(a.manifest.resolve()), "parameters_were_fixed_before_schematic_and_physical_results": True},
                generation_timeout_seconds=600 if stage == "source_to_geometry" else 30,
                evaluator_timeout_seconds=90 if fidelity == "geometry" else 600 if fidelity == "pex" else 5400)
            stages.append({"stage": stage, "run_directory": result["run_directory"], "actual_cost": measured_cost(result["run_directory"]),
                "queue_wait_seconds": queue_wall, "dispatch_sample": sample})
            write(work / "stage_executions.json", stages)
            return result
        geometry_trusted = work / "geometry_trusted"
        files = build("geometry", geometry_trusted, top=pool["top_cell"])
        generation = execute(pool["source_dir"], pool["source_paths"], geometry_trusted, files, "geometry", "source_to_geometry")
        generated = Path(generation["run_directory"])
        source = work / "retained_gds_source"
        source.mkdir()
        (source / "generator.py").write_text(COPY)
        result = generation
        try:
            if not (generation.get("physical_result") or {}).get("requested_fidelity_complete"):
                raise ValueError("Canonical source-to-GDS/geometry control did not complete; inspect raw transport/generation logs")
            if source_contents(generated / "source", pool["source_paths"], binary=True) != source_contents(Path(pool["source_dir"]), pool["source_paths"], binary=True):
                raise ValueError("The generated control used different frozen source")
            shutil.copyfile(generated / "accepted/candidate.gds", source / "input.gds")
            pex_trusted = work / "pex_trusted"
            files = build("pex", pex_trusted, top=pool["top_cell"], point=point, full_trusted=trusted)
            physical = execute(source, ["generator.py", "input.gds"], pex_trusted, files, "pex", "actual_physical_PEX")
            result = physical
            record = physical.get("physical_result") or {}
            if record.get("requested_fidelity_complete") and record.get("assessment", {}).get("S1"):
                if family not in state.get("nominal_adapter_control_attempted", []):
                    nominal_trusted = work / "nominal_trusted"
                    files = cached(nominal_trusted, point=point, full_trusted=trusted, physical_run=physical["run_directory"], nominal=True)
                    nominal = execute(source, ["generator.py", "input.gds"], nominal_trusted, files, "pex_spice", "actual_nominal_TT_OP_AC_control")
                    state.setdefault("nominal_adapter_control_attempted", []).append(family)
                    observed = nominal.get("physical_result") or {}
                    if (not observed.get("requested_fidelity_complete") or observed.get("S2") is not False
                            or observed["nominal"]["new_SPICE_calls"] != 1 or observed["nominal"]["new_Tran_DC_SS_FF_SPICE_calls"] != 0):
                        raise ValueError("The new nominal-only trusted adapter control is incomplete; preserve as infrastructure/unknown")
                    state.setdefault("nominal_adapter_controls", {})[family] = {"run_directory": nominal["run_directory"],
                        "metrics": observed["nominal"]["metrics"], "complete": True, "S2_claimed": False,
                        "actual_new_SPICE_calls": 1, "calibrated_prediction": None}
                electrical_trusted = work / "electrical_trusted"
                files = cached(electrical_trusted, point=point, full_trusted=trusted, physical_run=physical["run_directory"])
                result = execute(source, ["generator.py", "input.gds"], electrical_trusted, files, "pex_spice", "full_electrical_on_retained_PEX")
            checked = inspect_point(result, point, source_contents(source, ["generator.py", "input.gds"], binary=True),
                {"parameters": point["parameters"]}, gold_control_check=False)
        except (OSError, KeyError, TypeError, ValueError) as error:
            checked = {"S0": False, "S1": False, "S2": False, "execution_integrity": "incomplete",
                "failure_class": "unknown", "reason": type(error).__name__+": "+str(error)}
        complete = checked["execution_integrity"] == "valid" and checked["failure_class"] in [None, "candidate"]
        row = {"pool_id": pool["pool_id"], **checked, "point_evaluation_complete": complete,
            "run_directory": result["run_directory"], "stage_executions": stages,
            "actual_source_to_GDS_origin": generation["run_directory"], "DRC_LVS_PEX_repeated_for_SPICE": False}
        state["points"].append(row)
        write(a.output / "state.json", state)
        try:
            for stage in stages:
                stage["raw_archive"] = archive(stage["run_directory"], retain_accepted_gds=stage["stage"] == "source_to_geometry")
        except (OSError, ValueError) as error:
            state.update(status="PAUSED_ARCHIVE_INFRASTRUCTURE_PHYSICAL_RESULTS_PRESERVED",
                archive_error=type(error).__name__+": "+str(error))
            write(a.output / "state.json", state)
            raise
        if not complete:
            state["status"] = "PAUSED_UNKNOWN_CONTROL_NOT_CANDIDATE_FAILURE"
        write(a.output / "state.json", state)
        print(json.dumps({"pool_id": row["pool_id"], "S1": row["S1"], "S2": row["S2"], "complete": complete,
            "run_directory": result["run_directory"]}), flush=True)
        if not complete:
            break
    if len(state["points"]) == 8:
        state["status"] = "ALL8_TERMINAL"
    write(a.output / "state.json", state)
    write(ROOT / "results/derived/e2_nondefault_sizing_physical_qualification.json", state)


if __name__ == "__main__":
    main()
