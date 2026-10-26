"""Software replay of retained actual vendor waveforms; launches no SPICE."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

ROOT = Path("/work")
TASKS = ROOT / "runtime/task_preparation/otas_20261019T022816023029Z/private"
spec = importlib.util.spec_from_file_location("trusted_transport", ROOT / "scripts/ota_frozen_bench.py")
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
out = TASKS.parent / ("vendor_transport_replay_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
out.mkdir()
cases = [
    ("fvf", "phase0_20261019T012047189356Z_fvf_validate", "", 15., True),
    ("fvf", "phase0_20261019T013422659988Z_e2_development_pilot", "electrical", 10., False),
    ("legacy_miller", "phase0_20261019T014057607044Z_e2_development_pilot", "electrical", .5, False),
]
records = []
started, cpu = time.monotonic(), time.process_time()
for index, (kind, run_id, subdir, load, feasible) in enumerate(cases):
    task = json.loads((TASKS / kind / "task.json").read_text())
    point = task["configurations"][0]
    contract = copy.deepcopy(point["contract"])
    contract["bench_parameters"] = {"supply_V": 1.8, "temperature_C": 27, "common_mode_V": .9,
        "bias_currents_A": [1e-5, 1e-5], "load_F": load*1e-12}
    contract["analysis_contracts"] = {"tran": {"required_windows": [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]}}
    source = ROOT / "runs/phase0" / run_id / subdir
    original = json.loads((source / "measurements.json").read_text())
    case = out / f"case_{index}"
    case.mkdir()
    class ReplayProcess:
        returncode = 0
        def __init__(self, *args, cwd, **kwargs):
            work = Path(cwd)
            shutil.copytree(source / "post_rc", work / "post_rc")
            data = copy.deepcopy(original)
            for corner, row in data["results"]["post_rc"].items():
                for item in row["analysis_validation" if kind == "fvf" else "analysis_evidence"].values():
                    for key in ["data_path", "log_path"]:
                        item[key] = str(work / "post_rc" / corner / Path(item[key]).name)
            (work / "measurements.json").write_text(json.dumps(data)+"\n")
        def wait(self, **kwargs):
            return self.returncode
    with patch.object(transport.subprocess, "Popen", ReplayProcess):
        result = transport.run_vendor_post_rc(case, ROOT / "runs/phase0" / run_id / ("fvf7_pex.spice" if kind == "fvf" else "ota7_pex.spice"),
            "fvf7_rc" if kind == "fvf" else "ota7_rc", task["ports"], point["parameters"], contract,
            kind=kind, bench_snapshot=TASKS / kind / "trusted_bench/original_retained_bench.py",
            reference_path=TASKS / kind / "references/anchor.spice")
    assert result["all_analyses_complete"]
    assert all(row["original_development_constraints_passed"] for row in result["corners"].values()) == feasible
    for corner, row in result["corners"].items():
        assert row["metrics"]["ugb"] == {"value": original["results"]["post_rc"][corner]["metrics"]["ugb_Hz"], "unit": "Hz"}
        assert set(row["analyses"]) == {"op", "ac", "tran", "dc"}
        assert all(Path(a[key]).is_file() for a in row["analyses"].values() for key in ["data", "log"])
        assert all(Path(a[key]).is_relative_to(case) for a in row["analyses"].values() for key in ["data", "log"])
    records.append({"kind": kind, "actual_raw_origin": str(source), "load_pF": load,
        "expected_all_corner_feasible": feasible, "normalized_complete": True,
        "metric_units_values_and_artifact_paths_checked": True, "new_SPICE_processes": 0})
record = {"scope": "software_saved_actual_waveform_transport_replay_NOT_NEW_MEASUREMENT", "cases": records,
    "new_SPICE_processes": 0, "passed": True, "wall_seconds": time.monotonic()-started,
    "software_CPU_seconds": time.process_time()-cpu,
    "actual_subprocess_launch_validated": False, "first_actual_physical_point_smoke_required": True}
(out / "report.json").write_text(json.dumps(record, indent=2)+"\n")
(TASKS.parent / "public/vendor_transport_software_smoke.json").write_text(json.dumps(record, indent=2)+"\n")
print(json.dumps({"passed": True, "report": str(out / "report.json"), "new_SPICE_processes": 0}), flush=True)
