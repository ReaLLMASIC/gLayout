"""One development-only legacy-Miller load-domain qualification after its E2 pool.

The fixed .5pF stream and all its failures remain unchanged. This single 15pF
application point reuses the baseline's actual full-rule DRC, independent LVS
and positive full-RC extraction; their original costs are referenced, not rerun.
"""
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    source = Path(os.environ["PROBE_INPUT"])
    out = Path.cwd()
    baseline = json.loads((source / "candidate_result.json").read_text())
    metadata = json.loads((source / "candidate_manifest.json").read_text())
    if baseline["source_family"] != "legacy_miller" or baseline["candidate_id"] != "c00":
        raise SystemExit("Only the fixed legacy baseline is admitted to this one load probe")
    if not baseline["full_flow_complete"]:
        raise SystemExit("The retained baseline must have a complete original full flow")
    pool = Path(metadata["plan_path"]).parent
    attempts = []
    for path in source.parent.glob("*_e2_development_pilot/candidate_result.json"):
        result = json.loads(path.read_text())
        if result.get("pool_id") == metadata["pool_id"]:
            attempts.append(result)
    if (len(attempts) != 16 or {r["stream_index"] for r in attempts} != set(range(16))
            or any(r["status"] == "STARTING" for r in attempts)):
        raise SystemExit("Finish the original fixed16 stream before this separate load probe")
    if any(r["all_corner_development_feasible"] for r in attempts):
        raise SystemExit("The authorized extra load probe is conditional on no verified feasible candidate")

    contract = {
        "scope": "development_domain_qualification_not_formal_not_training_not_E2_pool",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_attempt": str(source), "fixed_pool": str(pool),
        "fixed_sizing": metadata["fixed_sizing"],
        "source_gold_geometry_and_PEX_unchanged": True,
        "corners": ["tt", "ss", "ff"], "temperature_C": 27,
        "supply_V": 1.8, "common_mode_V": .9, "bias_currents_A": [1e-5, 1e-5],
        "load_F": 15e-12, "previous_load_F": .5e-12,
        "transient": {"end_s": 20e-6, "step_s": 5e-9,
            "input_low_V": .89, "input_high_V": .91,
            "delay_s": 5e-6, "rise_s": 10e-9, "fall_s": 10e-9,
            "width_s": 5e-6, "period_s": 10e-6,
            "settled_windows_s": [[8.5e-6, 9.9e-6], [13.5e-6, 14.9e-6]],
            "timeout_per_corner_s": 900,
            "window_reason": "Original .5pF worst UGB16.16MHz; an explicitly approximate pure-load scaling to15pF gives.54MHz, tau~.30us. The declared plateau samples start3.5us after each edge (~12 such tau). Actual AC and complete transient decide validity; this estimate does not certify stability or success."},
        "OP_AC_DC_and_numeric_options_unchanged": True,
        "constraints": metadata["contract"]["existing_development_feasibility"],
        "fixed_stream_terminal_counts": {status: sum(r["status"] == status for r in attempts)
            for status in sorted({r["status"] for r in attempts})},
        "physical_cost_reuse": {"actual_original_stage_wall_seconds": baseline["stage_wall_seconds"],
            "additional_generation_DRC_LVS_PEX_calls": 0,
            "interpretation": "Original physical acquisition is charged to its original E2 attempt and referenced here, never presented as a fresh zero-cost extraction."},
        "retry_or_load_search_allowed": False,
    }
    write(out / "domain_contract.json", contract)
    for name in ["ota7.spice", "ota7_pex.spice", "ota7.gds", "gold.spice",
                 "candidate_source.py", "validation.json"]:
        (out / name).write_bytes((source / name).read_bytes())
    original = (pool / "testbench_snapshot.py").read_text()
    replacements = [
        ('"transient_window_s":4e-6', '"transient_window_s":20e-6'),
        ('pulse(.89 .91 1u 10n 10n 1u 2u)', 'pulse(.89 .91 5u 10n 10n 5u 10u)'),
        ('tran 5n 4u', 'tran 5n 20u'),
        ('"end":4e-6', '"end":20e-6'),
        ('[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]', '[[8.5e-6,9.9e-6],[13.5e-6,14.9e-6]]'),
        ('high=(t>1.8e-6)&(t<1.99e-6);low=(t>2.8e-6)&(t<2.99e-6)',
         'high=(t>8.5e-6)&(t<9.9e-6);low=(t>13.5e-6)&(t<14.9e-6)'),
        ('timeout=240)', 'timeout=900 if name=="transient" else 240)'),
    ]
    adapted = original
    for before, after in replacements:
        if adapted.count(before) != 1:
            raise SystemExit("Frozen bench transport/window site changed: " + before)
        adapted = adapted.replace(before, after)
    (out / "testbench_frozen_original.py").write_text(original)
    bench = out / "testbench_load15_long_window.py"
    bench.write_text(adapted)
    (out / "testbench_load15_long_window.patch").write_text("".join(difflib.unified_diff(
        original.splitlines(keepends=True), adapted.splitlines(keepends=True),
        fromfile="frozen_E2_testbench.py", tofile=bench.name)))
    work = out / "electrical"
    work.mkdir()
    launcher = work / "run_bench.py"
    launcher.write_text("\n".join([
        "import os, sys, runpy",
        "sys.path[:0] = " + repr([str(pool / "frozen_src")]),
        "import src.report_parsers, src.spice_validation, src.physical_drc",
        "os.environ['PROBE_INPUT'] = " + repr(str(out)),
        "sys.argv = " + repr([str(bench), "--fidelity", "post_rc", "--load-pf", "15"]),
        "runpy.run_path(" + repr(str(bench)) + ", run_name='__main__')", ""]))
    start = time.monotonic()
    with (work / "bench_console.log").open("w") as log:
        simulation = subprocess.run([sys.executable, str(launcher)], cwd=work,
            stdout=log, stderr=subprocess.STDOUT, timeout=4320)
    record = {"scope": contract["scope"], "contract": contract,
        "bench_returncode": simulation.returncode, "simulation_wall_seconds": time.monotonic()-start,
        "all_analyses_complete": False, "all_corner_development_feasible": False}
    measurements = json.loads((work / "measurements.json").read_text())
    record["measurements"] = measurements
    corners = measurements["results"].get("post_rc", {})
    complete = bool(set(corners) == {"tt", "ss", "ff"} and measurements.get("flow_complete")
        and all(row.get("all_analyses_complete") for row in corners.values()))
    record["all_analyses_complete"] = complete
    metric_rows = {}
    for corner, row in corners.items():
        metrics = dict(row["metrics"])
        errors = [metrics.get("positive_step_final_error_V"), metrics.get("negative_step_final_error_V")]
        metrics["settled_tracking_error_V"] = max(abs(v) for v in errors) if all(v is not None for v in errors) else None
        metrics["development_feasible"] = bool(row["all_analyses_complete"]
            and metrics.get("gain_at_10Hz_dB", -1) >= 30
            and metrics.get("gain_at_10Hz_real", -1) > 0
            and metrics.get("ugb_Hz", -1) >= 1e6
            and 60 <= metrics.get("phase_margin_deg", -1) <= 180
            and abs(metrics.get("output_bias_V", -10)-.9) < .01
            and metrics["settled_tracking_error_V"] is not None and metrics["settled_tracking_error_V"] < .01
            and 0 < metrics.get("power_W", -1) <= .001)
        metric_rows[corner] = metrics
    record["metrics_by_corner"] = metric_rows
    record["all_corner_development_feasible"] = bool(complete and all(m["development_feasible"] for m in metric_rows.values()))
    record["status"] = ("COMPLETE_FEASIBLE" if record["all_corner_development_feasible"] else
        "COMPLETE_INFEASIBLE" if complete else "INCOMPLETE_SIMULATION")
    write(out / "domain_result.json", record)
    print(json.dumps({k: v for k, v in record.items() if k != "measurements"}), flush=True)
    return 0 if record["all_corner_development_feasible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
