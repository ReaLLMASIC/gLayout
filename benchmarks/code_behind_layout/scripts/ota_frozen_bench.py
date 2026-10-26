"""Trusted post-RC transport for the complete original 5T/compact OTA benches.

Call only after full DRC, independent LVS, exact device intent and positive RC.
No candidate source is imported. Stimuli, solver settings, timeouts, validation
and metric formulas remain the complete frozen benchmark's original code.
"""
import ast
import difflib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def run_post_rc(out, pex, cell, ports, parameters, contract, *, kind, bench_snapshot, reference_path):
    if kind not in ["five_t", "compact_miller"] or cell != kind+"_ota_rc":
        raise ValueError("Frozen source-specific post-RC cell binding changed")
    if contract["required_corners"] != ["tt", "ss", "ff"]:
        raise ValueError("Exact original OTA bench requires all three declared corners")
    out, pex = Path(out), Path(pex)
    work = out / "post_rc_measurements"
    work.mkdir()
    inputs = work / "physical_input"
    inputs.mkdir()
    (inputs / (kind+"_ota_pex.spice")).write_bytes(pex.read_bytes())
    (inputs / "sizing.json").write_text(json.dumps(parameters)+"\n")
    (inputs / "validation.json").write_text(json.dumps({"physical_connectivity_and_positive_RC": True})+"\n")
    reference = Path(reference_path).read_text()
    reference_code = "DEFAULT="+repr(parameters)+"\nPORTS="+repr(list(ports))+"\ndef schematic(config=None):\n    return "+repr(reference)+"\n"
    binding = work / "trusted_reference_binding.py"
    binding.write_text(reference_code)
    original = Path(bench_snapshot).read_text()
    site = 'Path("/work/src/generators/'+kind+'_reference.py").read_text()'
    if original.count(site) != 1:
        raise ValueError("Frozen benchmark reference metadata transport site changed")
    adapted = original.replace(site, repr(reference_code))
    function = "simulate" if kind == "five_t" else "measure"
    def body(source):
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == function)
        return ast.get_source_segment(source, node)
    if body(original) != body(adapted):
        raise ValueError("Frozen measurement function changed during transport")
    bench = work / "frozen_bench.py"
    bench.write_text(adapted)
    (work / "bench_transport.patch").write_text("".join(difflib.unified_diff(original.splitlines(True), adapted.splitlines(True),
        fromfile=str(bench_snapshot), tofile=str(bench))))
    arguments = [str(bench), "--post-rc", "--load-pf", "2"]
    arguments += ["--vcm", "1.1", "--bias-ua", "20"] if kind == "five_t" else [
        "--vcm", "1.05", "--n-bias-ua", "20", "--p-bias-ua", "10", "--cap-size", str(parameters["cap_size"])]
    launcher = work / "run_bench.py"
    launcher.write_text("\n".join([
        "import importlib.util,os,runpy,sys,types",
        "import src.report_parsers,src.spice_validation",
        "package=types.ModuleType('src.generators');package.__path__=[];sys.modules['src.generators']=package",
        "spec=importlib.util.spec_from_file_location("+repr("src.generators."+kind+"_reference")+","+repr(str(binding))+")",
        "module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)",
        "os.environ['PROBE_INPUT']="+repr(str(inputs)),
        "sys.argv="+repr(arguments),
        "runpy.run_path("+repr(str(bench))+",run_name='__main__')", ""]))
    started = time.monotonic()
    timed_out = False
    with (work / "bench_console.log").open("w") as log:
        process = subprocess.Popen([sys.executable, str(launcher)], cwd=work,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=1200)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    measurement_file = work / "measurements.json"
    measurements = json.loads(measurement_file.read_text()) if measurement_file.exists() else {"results": {}}
    result = {"scope": "trusted_original_frozen_OTA_measurement_transport", "corners": {},
        "bench_returncode": process.returncode, "outer_timeout": timed_out,
        "wall_seconds": time.monotonic()-started, "raw_measurements": str(measurement_file),
        "measurement_function_source_identical": True,
        "source_specific_inner_timeouts_s": 90 if kind == "five_t" else 120,
        "physical_gates": "caller must establish actual DRC/LVS/device_intent/positiveRC first",
        "transport_patch": str(work / "bench_transport.patch")}
    units = {"gain": ("gain_10Hz_dB", "dB"), "ugb": ("ugb_Hz", "Hz"), "phase_margin": ("phase_margin_deg", "deg"),
        "settled_tracking_error": ("settled_tracking_error_V", "V"), "power": ("power_W", "W")}
    for name, row in measurements["results"].items():
        corner = row["corner"]
        op_field = "operating_point_integrity" if kind == "five_t" else "op_integrity"
        complete = bool(row.get(op_field, {}).get("complete") and set(row.get("analyses", {})) == {"ac", "tran", "dc"}
            and all(v.get("returncode") == 0 and v.get("integrity", {}).get("complete") for v in row["analyses"].values()))
        metrics = {}
        if complete:
            metrics = {target: {"value": row[source], "unit": unit} for target, (source, unit) in units.items() if source in row}
            metrics["nominal_tracking_error"] = {"value": abs(row["output_V"]-(1.1 if kind == "five_t" else 1.05)), "unit": "V"}
        healthy = bool(complete and row.get("positive_low_frequency_gain") and .15 < row["tail_V"] < .8)
        if healthy and kind == "five_t":
            healthy = .4 < row["mirror_V"] < 1.6 and 20e-6 < row["supply_current_A"] < 80e-6
        if healthy and kind == "compact_miller":
            healthy = .3 < row["stage1_V"] < 1.2 and 50e-6 < row["supply_current_A"] < 160e-6
        artifacts = {key: {"data": str(work / name / (key+".dat")), "log": str(work / name / (("ac" if key == "op" else key)+".log")),
            "returncode": row.get("analyses", {}).get("ac" if key == "op" else key, {}).get("returncode")}
            for key in ["op", "ac", "tran", "dc"]}
        result["corners"][corner] = {"complete": complete, "converged": complete, "operating_point_valid": bool(healthy),
            "metrics": metrics, "analyses": artifacts,
            "original_development_constraints_passed": bool(row.get("development_feasible" if kind == "five_t" else "development_nominal_feasible")),
            "raw": row}
        if complete:
            metrics["original_development_predicate"] = {"value": float(result["corners"][corner]["original_development_constraints_passed"]), "unit": "1"}
    result["all_analyses_complete"] = bool(set(result["corners"]) == {"tt", "ss", "ff"}
        and process.returncode in [0, 2] and not timed_out and all(row["complete"] for row in result["corners"].values()))
    (work / "normalized.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    return result


def run_vendor_post_rc(out, pex, cell, ports, parameters, contract, *, kind, bench_snapshot, reference_path):
    """Execute a retained vendor OTA loop in a separate trusted process.

    The caller supplies a frozen analysis_function.py beside bench_snapshot.
    Its function body must equal the complete original top-level analysis loop.
    New application loads/windows must already be explicit in the contract and
    retained full benchmark; this adapter never changes their analysis code.
    """
    if kind not in ["fvf", "legacy_miller"] or cell != ("fvf7_rc" if kind == "fvf" else "ota7_rc"):
        raise ValueError("Vendor OTA source/cell binding changed")
    if contract["required_corners"] != ["tt", "ss", "ff"] or parameters != contract["immutable_parameters"]:
        raise ValueError("Vendor OTA requires its exact per-configuration three-corner binding")
    bench_parameters = contract["bench_parameters"]
    if (bench_parameters["supply_V"] != 1.8 or bench_parameters["temperature_C"] != 27
            or bench_parameters["common_mode_V"] != .9 or bench_parameters["bias_currents_A"] != [1e-5, 1e-5]):
        raise ValueError("Retained vendor OTA stimulus binding changed")
    original = Path(bench_snapshot).read_text()
    body_path = Path(bench_snapshot).parent / "analysis_function.py"
    body = body_path.read_text()
    original_loop = next(n for n in ast.parse(original).body if isinstance(n, ast.For))
    function, = ast.parse(body).body
    if (not isinstance(function, ast.FunctionDef) or function.name != "run_exact_analysis_loop"
            or len(function.body) != 1 or ast.dump(function.body[0]) != ast.dump(original_loop)):
        raise ValueError("Frozen complete vendor analysis loop differs from its retained source")
    out, pex = Path(out), Path(pex)
    work = out / "post_rc_measurements"
    work.mkdir()
    (work / "reference.spice").write_bytes(Path(reference_path).read_bytes())
    (work / ("fvf7_pex.spice" if kind == "fvf" else "ota7_pex.spice")).write_bytes(pex.read_bytes())
    (work / "analysis_function.py").write_text(body)
    (work / "bench_binding.json").write_text(json.dumps({"kind": kind, "parameters": parameters,
        "ports": list(ports), "bench_parameters": bench_parameters,
        "analysis_contracts": contract["analysis_contracts"],
        "analysis_timeout_s": contract.get("analysis_timeout_s", 180)}, indent=2)+"\n")
    launcher = work / "run_bench.py"
    launcher.write_text("\n".join([
        "import json,re,subprocess,time",
        "from pathlib import Path",
        "from types import SimpleNamespace",
        "import numpy as np",
        "from src.spice_validation import validate_analysis",
        "from src.report_parsers import duplicate_subcircuits,rc_netlist_inventory",
        "out=Path.cwd()",
        "binding=json.loads((out/'bench_binding.json').read_text())",
        "kind=binding['kind']",
        "a=args=SimpleNamespace(fidelity='post_rc',corners=['tt','ss','ff'],solver='klu',analysis_timeout=binding['analysis_timeout_s'],load_pf=binding['bench_parameters']['load_F']/1e-12)",
        "reference=ref=out/'reference.spice'",
        "pex=out/('fvf7_pex.spice' if kind=='fvf' else 'ota7_pex.spice')",
        "record={'scope':'trusted_retained_vendor_OTA_postRC','results':{}}",
        "def save():\n    (out/'measurements.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\\n')",
        "exec(compile((out/'analysis_function.py').read_text(),str(out/'analysis_function.py'),'exec'))",
        "run_exact_analysis_loop()",
        "save()", ""]))
    started, timed_out = time.monotonic(), False
    with (work / "bench_console.log").open("w") as log:
        process = subprocess.Popen([sys.executable, str(launcher)], cwd=work,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=1800 if kind == "fvf" else 4800)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    path = work / "measurements.json"
    measures = json.loads(path.read_text()) if path.exists() else {"results": {}}
    result = {"scope": "trusted_original_frozen_vendor_OTA_measurement_transport", "corners": {},
        "bench_returncode": process.returncode, "outer_timeout": timed_out,
        "wall_seconds": time.monotonic()-started, "raw_measurements": str(path),
        "measurement_loop_AST_identical_to_retained_benchmark": True,
        "physical_gates": "caller must establish actual DRC/LVS/device_intent/positiveRC first",
        "bench_parameters": bench_parameters, "additional_circuit_or_analysis_changes": False}
    windows = contract["analysis_contracts"]["tran"]["required_windows"]
    for corner, row in measures["results"].get("post_rc", {}).items():
        integrity = row.get("analysis_validation" if kind == "fvf" else "analysis_evidence", {})
        complete = bool(set(row.get("analyses", {})) == {"ac", "transient", "dc"}
            and len(integrity) == 4 and all(v.get("complete") for v in integrity.values())
            and all(v.get("returncode") == 0 for v in row["analyses"].values()))
        metrics, passed, healthy = {}, False, False
        if complete:
            import numpy as np
            raw = row["metrics"]
            transient = np.loadtxt(work / "post_rc" / corner / "transient.dat", skiprows=1, ndmin=2)
            errors = []
            for lower, upper in windows:
                mask = (transient[:, 0] > lower) & (transient[:, 0] < upper)
                if not mask.any():
                    raise ValueError("Complete vendor transient lacks a declared settled sample window")
                errors.append(abs(float(np.mean(transient[mask, 2]-transient[mask, 1]))))
            settled = max(errors)
            nominal = abs(raw["output_bias_V"]-.9)
            values = {"gain": (raw["gain_at_10Hz_dB"], "dB"), "ugb": (raw.get("ugb_Hz"), "Hz"),
                "phase_margin": (raw.get("phase_margin_deg"), "deg"),
                "nominal_tracking_error": (nominal, "V"), "settled_tracking_error": (settled, "V"),
                "power": (raw["power_W"], "W")}
            metrics = {key: {"value": value, "unit": unit} for key, (value, unit) in values.items() if value is not None}
            healthy = bool(0 < raw["power_W"] and 0 < raw["output_bias_V"] < 1.8)
            passed = bool(raw["gain_at_10Hz_real"] > 0 and 0 < raw["power_W"] <= .001
                and raw["gain_at_10Hz_dB"] >= 30 and raw.get("ugb_Hz", 0) >= 1e6
                and 60 <= raw.get("phase_margin_deg", -1) <= 180 and nominal < .01 and settled < .01)
            metrics["original_development_predicate"] = {"value": float(passed), "unit": "1"}
        artifacts = {("op" if key in ["op", "operating_point"] else "tran" if key == "transient" else key):
            {"data": item["data_path"], "log": item["log_path"],
             "returncode": row["analyses"]["ac" if key in ["op", "operating_point"] else key]["returncode"]}
            for key, item in integrity.items()}
        result["corners"][corner] = {"complete": complete, "converged": complete,
            "operating_point_valid": healthy, "metrics": metrics, "analyses": artifacts,
            "original_development_constraints_passed": passed, "raw": row}
    result["all_analyses_complete"] = bool(set(result["corners"]) == {"tt", "ss", "ff"}
        and process.returncode == 0 and not timed_out and all(v["complete"] for v in result["corners"].values()))
    (work / "normalized.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    return result
