"""Prospective bounded ideal OP/AC control for the new telescopic OTA.

Preparation is local/stdlib-only. Actual simulation runs all four declared bias
controls once at tt/ss/ff, serially, and retains every deck/log/trace. It does
not build GDS, extract parasitics, or establish S1/S2. No old OTA is modified.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
# run_eda_probe copies this script into /work/runs/phase0/<run>. The same
# source also prepares the declaration from the ordinary host scripts folder.
if Path("/work/src").is_dir():
    ROOT = Path("/work")
sys.path.insert(0, str(ROOT))
from src.generators.telescopic_ota_reference import DEFAULT, PORTS, schematic
from src.spice_validation import validate_analysis


def write(path, record):
    path.write_text(json.dumps(record, indent=2, allow_nan=False)+"\n")


OP_VECTORS = ["v(out)", "v(vp)", "v(vn)", "v(bias)", "i(vsupply)", "i(vbn)", "i(vbp)",
    "v(xdut.tail)", "v(xdut.nl)", "v(xdut.nr)", "v(xdut.pl)", "v(xdut.pr)", "v(xdut.mirror)"]


def analysis_deck(manifest, control, corner):
    a = manifest["design"]["application"]
    lines = ["Independent telescopic cascode mirror OTA ideal OP/AC development control",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
        ".option scale=1e-6 klu", ".temp "+str(a["temperature_C"]),
        ".option reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
        ".include "+control["container_reference_file"],
        "VSUPPLY vdd 0 "+str(a["supply_V"]), "IREF vdd bias "+str(a["bias_reference_current_A"]),
        "VBN vbn 0 "+str(control["VBN_V"]), "VBP vbp 0 "+str(control["VBP_V"]),
        "VIN vp 0 dc "+str(a["common_mode_V"])+" ac 1", "LSERVO out vn 1G", "CAC vn 0 1G",
        "CLOAD out 0 "+str(a["load_F"]), "XDUT vdd 0 bias vbn vbp vp vn out telescopic_mirror_ota",
        ".save "+" ".join(OP_VECTORS), ".control", "op", "set wr_vecnames", "set wr_singlescale",
        "wrdata operating_point.dat "+" ".join(OP_VECTORS), "show all",
        "ac dec 30 10 1G", "wrdata ac.dat real(v(out)) imag(v(out))", "quit", ".endc", ".end", ""]
    return "\n".join(lines)


def prepare(out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / "configs/development/telescopic_ota_design.json").read_text())
    if config["new_GDS_DRC_LVS_PEX_SPICE_calls"] != 0:
        raise ValueError("The prospective source declaration must precede measurement")
    snapshot = out / "source_snapshot"
    snapshot.mkdir()
    for name in ["telescopic_ota.py", "telescopic_ota_reference.py", "terminal_access.py"]:
        shutil.copyfile(ROOT / "src/generators" / name, snapshot / name)
    shutil.copyfile(Path(__file__), out / "frozen_characterization.py")
    manifest = {"scope": "development_new_telescopic_OTA_ideal_control_NOT_FORMAL_NOT_TRAIN",
        "status": "PREPARED_NO_MEASUREMENTS", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "design": config, "immutable_per_finger_sizing": DEFAULT, "ports": PORTS,
        "solver": {"method": "KLU", "reltol": 1e-6, "abstol_A": 1e-14, "vntol_V": 1e-8, "chgtol_C": 1e-16},
        "per_corner_wall_limit_s": 120, "planned_controls": 4, "planned_OP_AC_corner_calls": 12,
        "analysis_contracts": {"op": {"kind": "op", "columns": 14, "expected_rows": 1},
            "ac": {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 241, "scale": "log"}},
        "controls": [], "source_snapshot": str(snapshot), "new_physical_calls": 0,
        "formal_trials": 0, "training_examples": 0}
    for control in config["four_predeclared_bias_controls"]:
        directory = out / control["id"]
        directory.mkdir()
        reference = directory / "independent_reference.spice"
        reference.write_text(schematic())
        point = {**control, "independent_reference_file": str(reference),
            "container_reference_file": "/work/"+str(reference.relative_to(ROOT)), "predeclared_decks": {}}
        decks = directory / "predeclared_decks"
        decks.mkdir()
        for corner in config["corners"]:
            path = decks / (corner+".spice")
            path.write_text(analysis_deck(manifest, point, corner))
            point["predeclared_decks"][corner] = str(path.relative_to(out))
        manifest["controls"].append(point)
    write(out / "design_manifest.json", manifest)
    print(json.dumps({"prepared": str(out), "controls": 4, "planned_corner_calls": 12, "actual_SPICE_calls": 0}))


def device_OP(text, expected):
    """Read actual printed BSIM operating parameters, with short unique names."""
    devices, names, errors = {}, [], []
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "device":
            names = fields[1:]
            for name in names:
                if re.match(r"m\.xdut\.x(?:n[1-4]|p[1-4]|nt|nr)_\d+\.", name.lower()):
                    devices[name] = {}
        elif fields[0] in ["gm", "gds", "id", "vds", "vdsat"]:
            for name, value in zip(names, fields[1:]):
                if name in devices:
                    try:
                        number = float(value)
                    except ValueError:
                        number = None
                    if number is None or not math.isfinite(number):
                        devices[name][fields[0]] = value
                        errors.append({"device": name, "field": fields[0], "raw_value": value})
                    else:
                        devices[name][fields[0]] = number
    complete = not errors and len(devices) == expected and all(set(v) == {"gm", "gds", "id", "vds", "vdsat"} for v in devices.values())
    if not complete:
        return {"complete": False, "devices": devices, "expected_device_count": expected,
            "parse_errors": errors,
            "reason": "Actual printed per-finger OP binding is incomplete or nonfinite; not a circuit-negative label"}
    return {"complete": True, "devices": devices, "expected_device_count": expected}


def measure(out, prepared, manifest, control, corner):
    import numpy as np
    out.mkdir(parents=True, exist_ok=False)
    a = manifest["design"]["application"]
    (out / ".spiceinit").write_text("set ngbehavior=hsa\n")
    (out / "analysis.spice").write_bytes((prepared / control["predeclared_decks"][corner]).read_bytes())
    started, before = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    code, error = None, None
    with (out / "console.log").open("w") as log:
        try:
            simulation = subprocess.run(["ngspice", "-b", "-o", "ngspice.log", "analysis.spice"],
                cwd=out, stdout=log, stderr=subprocess.STDOUT, timeout=manifest["per_corner_wall_limit_s"])
            code = simulation.returncode
        except subprocess.TimeoutExpired:
            error = "predeclared_120second_corner_wall_timeout"
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    simulation_wall = time.monotonic()-started
    validated = {name: validate_analysis(out / ("operating_point.dat" if name == "op" else "ac.dat"),
        out / "ngspice.log", contract, returncode=code) for name, contract in manifest["analysis_contracts"].items()}
    expected = manifest["design"]["default_per_finger_device_count"]
    details = device_OP((out / "ngspice.log").read_text() if (out / "ngspice.log").exists() else "", expected)
    write(out / "device_operating_points.json", details)
    metrics = {}
    op_valid = False
    limits = manifest["design"]["fixed_OP_AC_requirements"]
    if validated["op"]["complete"] and details["complete"]:
        row = np.atleast_2d(np.loadtxt(out / "operating_point.dat", skiprows=1))[-1]
        power = {"VDD_W": float(-1.8*row[5]), "VBN_W": float(-control["VBN_V"]*row[6]),
            "VBP_W": float(-control["VBP_V"]*row[7])}
        total = sum(power.values())
        ratios = [abs(d["vds"])/max(abs(d["vdsat"]), 1e-30) for d in details["devices"].values()]
        finite = all(math.isfinite(x) for d in details["devices"].values() for x in d.values())
        metrics.update(output_bias_V=float(row[1]), bias_reference_V=float(row[4]), power_W=total,
            power_components=power, minimum_abs_Vds_over_abs_Vdsat=min(ratios),
            minimum_abs_channel_voltage_V=min(abs(d["vds"]) for d in details["devices"].values()),
            minimum_abs_per_finger_drain_current_A=min(abs(d["id"]) for d in details["devices"].values()),
            IREF_branch_total_W=1.8*a["bias_reference_current_A"],
            IREF_ideal_source_dissipation_W=(1.8-float(row[4]))*a["bias_reference_current_A"],
            IREF_reference_MOS_dissipation_W=float(row[4])*a["bias_reference_current_A"])
        op_valid = bool(finite and limits["output_OP_acceptance_min_V"] <= row[1] <= limits["output_OP_acceptance_max_V"]
            and 0 < total <= limits["total_VDD_and_cascode_bias_power_W_max"]
            and metrics["minimum_abs_Vds_over_abs_Vdsat"] >= limits["minimum_abs_Vds_over_abs_Vdsat"]
            and metrics["minimum_abs_channel_voltage_V"] >= limits["minimum_absolute_channel_voltage_V"]
            and metrics["minimum_abs_per_finger_drain_current_A"] > 1e-12)
    if validated["ac"]["complete"]:
        data = np.atleast_2d(np.loadtxt(out / "ac.dat", skiprows=1))
        frequency, response = data[:, 0], data[:, 1]+1j*data[:, 2]
        gain, phase = 20*np.log10(np.maximum(np.abs(response), 1e-300)), np.unwrap(np.angle(response))*180/np.pi
        crossing = np.flatnonzero((gain[:-1] >= 0) & (gain[1:] < 0))
        metrics.update(gain_at_10Hz_dB=float(gain[0]), gain_at_10Hz_real=float(response[0].real),
            descending_unity_crossings=len(crossing))
        if len(crossing):
            i = int(crossing[0]); t = -gain[i]/(gain[i+1]-gain[i])
            metrics.update(ugb_Hz=float(np.exp(np.log(frequency[i])+t*np.log(frequency[i+1]/frequency[i]))),
                phase_margin_deg=float(180+phase[i]+t*(phase[i+1]-phase[i])))
    complete = details["complete"] and all(v["complete"] for v in validated.values())
    passed = bool(complete and op_valid and metrics.get("gain_at_10Hz_real", 0) > 0
        and metrics.get("gain_at_10Hz_dB", -1) >= limits["gain_at_10Hz_dB_min"]
        and metrics.get("ugb_Hz", 0) >= limits["ugb_Hz_min"]
        and limits["phase_margin_deg_min"] <= metrics.get("phase_margin_deg", -1) <= limits["phase_margin_deg_max"])
    record = {"control_id": control["id"], "corner": corner, "complete": complete,
        "operating_point_valid": op_valid, "ideal_OP_AC_requirements_passed": passed,
        "metrics": metrics, "analysis_validation": validated, "per_finger_OP_complete": details["complete"],
        "returncode": code, "error": error, "wall_seconds": time.monotonic()-started,
        "simulation_wall_seconds": simulation_wall,
        "actual_ngspice_CPU_seconds": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        "CPU_scope": "Actual waited ngspice children; component of the whole probe CPU, not an additional addend",
        "power_accounting": manifest["design"]["power_accounting"],
        "new_GDS_DRC_LVS_PEX_calls": 0, "S1_or_S2_established": False,
        "unmeasured_requirements": ["transient", "DC transfer/swing", "layout physical correctness", "post-RC performance"]}
    write(out / "result.json", record)
    return record


def run(prepared, out):
    prepared, out = Path(prepared).resolve(), Path(out).resolve()
    manifest = json.loads((prepared / "design_manifest.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    write(out / "input_preparation_binding.json", {"preparation": str(prepared),
        "manifest": str(prepared / "design_manifest.json"), "measurement_output": str(out),
        "predeclared_corner_calls": 12, "new_declarations_selected_from_results": False})
    rows = []
    for control in manifest["controls"]:
        for corner in manifest["design"]["corners"]:
            row = measure(out / control["id"] / corner, prepared, manifest, control, corner)
            rows.append(row)
            write(out / "progress.json", {"scope": manifest["scope"], "rows": rows, "actual_OP_AC_corner_calls": len(rows)})
            print(json.dumps({"control": control["id"], "corner": corner, "complete": row["complete"],
                "OP_valid": row["operating_point_valid"], "passed": row["ideal_OP_AC_requirements_passed"], "metrics": row["metrics"]}), flush=True)
    positive = [control["id"] for control in manifest["controls"]
        if all(row["ideal_OP_AC_requirements_passed"] for row in rows if row["control_id"] == control["id"])]
    write(out / "summary.json", {"scope": manifest["scope"], "all12_corner_calls_complete": all(row["complete"] for row in rows),
        "positive_controls": positive, "first_predeclared_positive_control": positive[0] if positive else None,
        "actual_OP_AC_corner_calls": len(rows), "actual_ngspice_CPU_seconds": sum(row["actual_ngspice_CPU_seconds"] for row in rows),
        "actual_SPICE_wall_seconds_sum": sum(row["simulation_wall_seconds"] for row in rows),
        "actual_analysis_stage_wall_seconds_sum": sum(row["wall_seconds"] for row in rows), "new_GDS_DRC_LVS_PEX_calls": 0,
        "S1_or_S2_established": False, "no_adaptive_bias_search": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path, help="Existing predeclared source/reference/deck directory for ideal mode")
    parser.add_argument("--mode", choices=["prepare", "ideal"], required=True)
    args = parser.parse_args()
    if args.mode == "ideal" and args.input is None:
        parser.error("ideal mode requires an explicit predeclared --input directory")
    prepare(args.output) if args.mode == "prepare" else run(args.input, args.output)
