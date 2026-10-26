"""One real geometry-only and one real PEX-only isolated E2 control."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.candidate_executor import CandidateExecutor
from src.e1_benchmarks import build_trusted
from scripts.e2_stage_prepare import build
from scripts.materialize_e1_packets import ota_analysis_contracts


def main():
    out = ROOT / "runs/development/e2_stage_smoke" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir(parents=True, mode=0o700)
    template = ROOT / "runtime/task_preparation/otas_20261019T022816023029Z/private/five_t/task.json"
    task = json.loads(template.read_text())
    point = task["configurations"][0]
    point["contract"]["analysis_contracts"] = ota_analysis_contracts("five_t")
    origin = ROOT / "runs/phase0/phase0_20261019T011132007923Z_e2_development_pilot"
    source = out / "source"
    source.mkdir()
    (source / "generator.py").write_text("import argparse,shutil\np=argparse.ArgumentParser();p.add_argument('--configuration');p.add_argument('--output');a=p.parse_args()\nshutil.copyfile('/source/input.gds',a.output)\n")
    shutil.copyfile(origin / "five_t_ota.gds", source / "input.gds")
    full = out / "full_template"
    build_trusted({"target": "five_t", "top_cell": "five_t_ota", "source_template": str(template)}, point, full)
    executor = CandidateExecutor(ROOT / "runtime/GLdev", out / "physical", ROOT / "runtime/magic-8.3.685", timeout=240)
    results = {}
    for stage in ["geometry", "pex"]:
        trusted = out / (stage+"_trusted")
        paths = build(stage, trusted, top="five_t_ota", point=point if stage == "pex" else None,
            full_trusted=full if stage == "pex" else None)
        if stage == "geometry":
            assert not any(Path(p).suffix == ".spice" or p == "contract.json" for p in paths)
        else:
            assert not any(p in paths for p in ["original_bench.py", "analysis_function.py", "ota_frozen_bench.py", "bench.py"])
        result = executor.execute(source_dir=source, source_paths=["generator.py", "input.gds"], entrypoint="generator.py",
            representation="G0", configuration={"parameters": point["parameters"]}, trusted_dir=trusted, trusted_paths=paths,
            fidelity=stage, phase="development_E2_stage_smoke", context={"source_role": "trusted_evaluator_control",
                "configuration_id": "anchor", "reference_id": point["reference_id"], "source_generation_acquisition": str(origin),
                "source_generation_reused_not_remeasured": True}, generation_timeout_seconds=30, evaluator_timeout_seconds=240)
        run = Path(result["run_directory"])
        evidence = run / "evidence"
        record = result["physical_result"]
        assert result["status"] == "EVALUATED", result
        assert record["requested_fidelity"] == stage and record["requested_fidelity_complete"]
        if stage == "geometry":
            assert record["physical_tool_calls"] == {"DRC": 0, "LVS": 0, "PEX": 0, "SPICE": 0}
            assert not (evidence / "drc").exists() and not (evidence / "extracted_lvs.spice").exists()
        else:
            assert record["assessment"]["S1"] and not record["assessment"]["S2"]
            assert json.loads((evidence / "device_intent.json").read_text())["is_clean"]
            assert json.loads((evidence / "rc_inventory.json").read_text())["has_real_RC"]
            assert not (evidence / "post_rc_measurements").exists() and not list(evidence.rglob("*.dat"))
        assert record["physical_tool_calls"]["SPICE"] == 0
        results[stage] = {"run_directory": str(run), "requested_fidelity_complete": True,
            "S1": record.get("assessment", {}).get("S1", False), "new_SPICE_calls": 0}
    geometry_run = Path(results["geometry"]["run_directory"])
    layer = json.loads((ROOT / "results/derived/e2_development_mask_layer_binding.json").read_text())
    inputs = {"candidate_gds": str(geometry_run / "accepted/candidate.gds"),
        "excluded_layer_datatypes": layer["pin_and_label_layer_datatypes"]+layer["additional_nonmanufacturing_annotation"],
        "previous_masks": [{"candidate_id": "actual_original_default", "source_scope": "retained_development_geometry", "gds": str(origin / "five_t_ota.gds")}]}
    (out / "mask_inputs.json").write_text(json.dumps(inputs, indent=2)+"\n")
    with (out / "mask_comparison.log").open("w") as log:
        subprocess.run([str(ROOT / "runtime/GLdev/bin/python"), str(ROOT / "scripts/e2_mask_stage.py"),
            "--inputs", str(out / "mask_inputs.json"), "--output", str(out / "mask_result.json")], stdout=log, stderr=subprocess.STDOUT, check=True)
    mask = json.loads((out / "mask_result.json").read_text())
    assert mask["duplicate"]["candidate_id"] == "actual_original_default"
    report = {"scope": "actual_isolated_E2_geometry_and_PEX_control_NO_FORMAL_NO_SPICE", "passed": True,
        "stages": results, "exact_real_GDS_duplicate_detected": True, "mask_comparison_CPU_seconds": mask["software_CPU_seconds"],
        "original_source_generation_reuse": str(origin), "new_source_generation_calls": 0,
        "new_SPICE_calls": 0, "geometry_reference_mounted": False, "PEX_strict_intent_and_positive_RC": True}
    (out / "public_report.json").write_text(json.dumps(report, indent=2)+"\n")
    (ROOT / "results/derived/e2_stage_smoke.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"passed": True, "report": str(out / "public_report.json")}), flush=True)


if __name__ == "__main__":
    main()
