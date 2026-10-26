"""Bounded ideal Miller sizing diagnosis; no layout or formal labels.

The original15pF application, tight solver and independent transistor topology
stay fixed. A baseline OP exposes actual small-signal device parameters before
at most four new MIM/output-stage width combinations are declared and measured.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import resource
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.spice_validation import validate_analysis

BASE = ROOT / "runtime/e2_execution_preparation/20261019T0344Z_serial_costs/legacy_miller/s1/reference.spice"
DECKS = ROOT / "runs/phase0/phase0_20261019T030715097386Z_e2_sizing_prequalification/prelayout"


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n")


def simulate(out, reference, corner, *, ac):
    out.mkdir(parents=True, exist_ok=False)
    original = (DECKS / corner / "ac.spice").read_text()
    common = original.split(".control", 1)[0]
    common, count = re.subn(r"(?m)^\.include .*$", ".include "+str(reference), common)
    if count != 1 or not re.search(r"(?m)^CLOAD out 0 15(?:\.0)?p$", common):
        raise ValueError("The original fixed15pF ideal AC binding changed")
    tail = [".control", "op", "set wr_vecnames", "set wr_singlescale",
        "wrdata operating_point.dat v(out) v(vp) v(vn) v(bias1) v(bias2) i(vsupply)", "show all"]
    if ac:
        tail += ["ac dec 30 10 1G", "wrdata ac.dat real(v(out)) imag(v(out))"]
    tail += ["quit", ".endc", ".end", ""]
    (out / "analysis.spice").write_text(common+"\n".join(tail))
    (out / ".spiceinit").write_text("set ngbehavior=hsa\n")
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    code, error = None, None
    with (out / "console.log").open("w") as log:
        try:
            result = subprocess.run(["ngspice", "-b", "-o", "ngspice.log", "analysis.spice"],
                cwd=out, stdout=log, stderr=subprocess.STDOUT, timeout=240)
            code = result.returncode
        except subprocess.TimeoutExpired:
            error = "original_AC_240second_wall_timeout"
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    contracts = {"op": {"kind": "op", "columns": 7, "expected_rows": 1}}
    if ac:
        contracts["ac"] = {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 241, "scale": "log"}
    validation = {name: validate_analysis(out / ("operating_point.dat" if name == "op" else "ac.dat"),
        out / "ngspice.log", contract, returncode=code) for name, contract in contracts.items()}
    metrics = {}
    if validation["op"]["complete"]:
        row = np.atleast_2d(np.loadtxt(out / "operating_point.dat", skiprows=1))[-1]
        metrics.update(output_bias_V=float(row[1]), diffpair_bias_V=float(row[4]),
            cs_bias_V=float(row[5]), power_W=float(-1.8*row[6]))
    if ac and validation["ac"]["complete"]:
        data = np.atleast_2d(np.loadtxt(out / "ac.dat", skiprows=1))
        frequency, response = data[:, 0], data[:, 1]+1j*data[:, 2]
        gain = 20*np.log10(np.maximum(np.abs(response), 1e-300))
        phase = np.unwrap(np.angle(response))*180/np.pi
        crossing = np.flatnonzero((gain[:-1] >= 0) & (gain[1:] < 0))
        metrics.update(gain_at_10Hz_dB=float(gain[0]), gain_at_10Hz_real=float(response[0].real),
            descending_unity_crossings=len(crossing))
        if len(crossing):
            index = int(crossing[0]); t = -gain[index]/(gain[index+1]-gain[index])
            metrics.update(ugb_Hz=float(np.exp(np.log(frequency[index])+t*np.log(frequency[index+1]/frequency[index]))),
                phase_margin_deg=float(180+phase[index]+t*(phase[index+1]-phase[index])))
    complete = all(v["complete"] for v in validation.values())
    passed = complete and bool(metrics) and abs(metrics["output_bias_V"]-.9) < .01 and 0 < metrics["power_W"] <= .001
    if ac:
        passed = passed and metrics.get("gain_at_10Hz_dB", -1) >= 30 and metrics.get("gain_at_10Hz_real", 0) > 0 and metrics.get("ugb_Hz", 0) >= 1e6 and 60 <= metrics.get("phase_margin_deg", -1) <= 180
    record = {"corner": corner, "complete": complete, "required_OP_AC_predicate_passed": bool(passed),
        "metrics": metrics, "validation": validation, "returncode": code, "error": error,
        "wall_seconds": time.monotonic()-started,
        "actual_ngspice_CPU_seconds": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        "acquisition_scope": "one actual ideal OP/AC in an already allocated development2CPU cgroup; child CPU overlaps that cgroup total",
        "new_GDS_DRC_LVS_PEX_calls": 0, "S1_or_S2_established": False,
        "unmeasured_original_constraints": ["transient settled tracking", "DC sweep"]}
    write(out / "result.json", record)
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--phase", choices=["baseline", "grid"], required=True)
    a = p.parse_args()
    out = a.output.resolve()
    if a.phase == "baseline":
        out.mkdir(parents=True, exist_ok=False)
        reference = out / "baseline_reference.spice"
        reference.write_bytes(BASE.read_bytes())
        write(out / "baseline_binding.json", {"scope": "development_ideal_existing_N_OP_diagnosis",
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "original_gold": str(BASE),
            "application_load_F": 15e-12, "new_sizings": 0, "baseline_parameters": {
                "mim_cap_size": [30, 30], "mim_cap_rows": 3,
                "half_common_source_params": [7, 1, 10, 3]}, "no_layout_or_load_search": True})
        print(json.dumps(simulate(out / "baseline_tt", reference, "tt", ac=False)), flush=True)
    else:
        manifest = json.loads((out / "sizing_manifest.json").read_text())
        if len(manifest["new_sizings"]) > 4 or manifest["application_load_F"] != 15e-12:
            raise ValueError("The bounded fixed15pF diagnostic scope changed")
        results = []
        for size in manifest["new_sizings"]:
            row = {"id": size["id"], "parameters": size["parameters"], "corners": {}}
            for corner in ["tt", "ss", "ff"]:
                row["corners"][corner] = simulate(out / size["id"] / corner, Path(size["reference_file"]), corner, ac=True)
                results.append({"sizing_id": size["id"], **row["corners"][corner]})
                write(out / "progress.json", {"scope": manifest["scope"], "results": results,
                    "completed_ideal_corner_calls": len(results), "formal_measurements": 0})
                print(json.dumps({"sizing_id": size["id"], "corner": corner,
                    "complete": row["corners"][corner]["complete"], "metrics": row["corners"][corner]["metrics"]}), flush=True)


if __name__ == "__main__":
    main()
