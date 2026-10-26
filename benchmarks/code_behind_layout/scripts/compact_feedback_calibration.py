"""Bounded compact Miller timing/feedback calibration on one actual retained RC control.

First run the original three transient decks serially with their original120s
limit. Only if a deck remains incomplete, try the electrically identical node
alias at all three corners. No solver, physical element or stimulus changes.
"""
from datetime import datetime, timezone
import difflib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np

ROOT = Path("/work")
sys.path.insert(0, str(ROOT))
from src.spice_validation import validate_analysis

ORIGIN = ROOT / "runs/development/E1_matched/20261019T031011938615Z_eaa717ce/private/physical/executor_20261019T031040015399Z_059886fe"


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def main():
    out = Path.cwd()
    evidence = ORIGIN / "evidence"
    measurement = evidence / "post_rc_measurements"
    inventory = json.loads((evidence / "rc_inventory.json").read_text())
    ports = inventory["ports"]
    (out / "physical_rc.spice").write_bytes((evidence / "compact_miller_ota_pex.spice").read_bytes())
    normalized = json.loads((measurement / "normalized.json").read_text())
    if not normalized["corners"]["ff"]["complete"]:
        raise ValueError("The predeclared saved complete FF control is unavailable")
    contract = {"kind": "transient", "columns": 3, "start": 0, "end": 4e-6,
        "required_windows": [[1.8e-6, 1.99e-6]]}
    baseline = measurement / "ff_2.0pF/tran.dat"
    if not validate_analysis(baseline, measurement / "ff_2.0pF/tran.log", contract, 0)["complete"]:
        raise ValueError("Saved FF control fails the actual raw-waveform completeness gate")
    (out / "saved_complete_ff_tran.dat").write_bytes(baseline.read_bytes())
    decks = {}
    for corner in ["tt", "ss", "ff"]:
        original = (measurement / (corner+"_2.0pF/tran.spice")).read_text()
        include = [line for line in original.splitlines() if line.startswith(".include ")]
        if len(include) != 1:
            raise ValueError("Expected one retained physical RC include")
        transported = original.replace(include[0], ".include "+str(out / "physical_rc.spice"))
        lines, alias_lines, bindings, feedback = transported.splitlines(True), [], 0, 0
        for line in lines:
            fields = line.split()
            if fields and fields[0] == "XDUT":
                if fields[-1] != "compact_miller_ota_rc":
                    raise ValueError("RC control subcircuit binding changed")
                fields[1+ports.index("VN")] = fields[1+ports.index("VOUT")]
                line = " ".join(fields)+"\n"
                bindings += 1
            if fields == ["VFB", "out", "vn", "0"]:
                feedback += 1
                continue
            alias_lines.append(line.replace("v(vn)", "v(out)"))
        if bindings != 1 or feedback != 1:
            raise ValueError("The declared ideal feedback branch is not present exactly once")
        decks[corner] = {"original": transported, "alias": "".join(alias_lines)}
        for mode, text in decks[corner].items():
            work = out / mode / corner
            work.mkdir(parents=True)
            (work / ".spiceinit").write_bytes((measurement / (corner+"_2.0pF/.spiceinit")).read_bytes())
            (work / "tran.spice").write_text(text)
        (out / (corner+"_alias.patch")).write_text("".join(difflib.unified_diff(
            transported.splitlines(True), decks[corner]["alias"].splitlines(True), fromfile="original_transient", tofile="direct_feedback_alias")))
    record = {"scope": "development_exact_RC_numerical_and_scheduling_calibration_NOT_S2_NOT_FORMAL",
        "declared_at_utc": datetime.now(timezone.utc).isoformat(), "original_physical_acquisition": str(ORIGIN),
        "new_GDS_DRC_LVS_PEX_calls": 0, "per_analysis_wall_limit_s": 120, "maximum_analyses": 6,
        "corners": ["tt", "ss", "ff"], "order": "original serial3; alias serial3 only if any original incomplete",
        "solver_and_numeric_options_unchanged": True, "stimuli_load_physical_RC_and_reference_unchanged": True,
        "complete_FF_waveform_tolerance_V": 50e-6, "equivalence_rule": "Interpolate completed FF output traces on the saved complete FF time grid; max absolute output difference<=50uV",
        "shared_development_cgroup_wall_cost": True, "results": {}}
    write(out / "calibration_manifest.json", record)
    def compare(path):
        old = np.loadtxt(baseline, skiprows=1, ndmin=2)
        new = np.loadtxt(path, skiprows=1, ndmin=2)
        return float(np.max(np.abs(np.interp(old[:, 0], new[:, 0], new[:, 2])-old[:, 2])))
    def run(mode):
        record["results"][mode] = {}
        for corner in ["tt", "ss", "ff"]:
            work = out / mode / corner
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            started = time.monotonic()
            code, timed_out = None, False
            with (work / "console.log").open("w") as log:
                try:
                    process = subprocess.run(["ngspice", "-b", "-o", "tran.log", "tran.spice"], cwd=work,
                        stdout=log, stderr=subprocess.STDOUT, timeout=120)
                    code = process.returncode
                except subprocess.TimeoutExpired:
                    timed_out = True
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            validation = validate_analysis(work / "tran.dat", work / "tran.log", contract, code)
            item = {"returncode": code, "timeout": timed_out, "wall_seconds": time.monotonic()-started,
                "waited_child_user_CPU_seconds": after.ru_utime-before.ru_utime,
                "waited_child_system_CPU_seconds": after.ru_stime-before.ru_stime, "validation": validation}
            if corner == "ff" and validation["complete"]:
                item["max_output_difference_from_saved_FF_V"] = compare(work / "tran.dat")
                item["saved_FF_equivalence_passed"] = item["max_output_difference_from_saved_FF_V"] <= 50e-6
            record["results"][mode][corner] = item
            write(out / "calibration_result.json", record)
            print(json.dumps({"mode": mode, "corner": corner, "complete": validation["complete"], "wall_seconds": item["wall_seconds"]}), flush=True)
    run("original")
    if all(v["validation"]["complete"] for v in record["results"]["original"].values()):
        record["alias_executed"] = False
        record["conclusion"] = "ORIGINAL_SERIAL_DECKS_COMPLETE_SCHEDULING_BUDGET_CALIBRATION" if record["results"]["original"]["ff"]["saved_FF_equivalence_passed"] else "SERIAL_FF_DIFFERENCE_EXCEEDS_DECLARED_TOLERANCE_NO_ADOPTION"
    else:
        run("alias")
        record["alias_executed"] = True
        complete = all(v["validation"]["complete"] for v in record["results"]["alias"].values())
        equivalent = record["results"]["alias"]["ff"].get("saved_FF_equivalence_passed", False)
        record["conclusion"] = "DIRECT_FEEDBACK_ALIAS_COMPLETE_EQUIVALENT_PROSPECTIVE_CONTROL" if complete and equivalent else "UNRESOLVED_NUMERICAL_OR_WALL_BUDGET_NO_ADOPTION"
    write(out / "calibration_result.json", record)
    print(record["conclusion"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
