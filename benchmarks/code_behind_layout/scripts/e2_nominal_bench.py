"""Actual TT OP/AC from the frozen OTA bench, without other SPICE analyses.

A trusted launcher intercepts the original function's first ngspice call while
it prepares the exact TT AC deck. That preparation executes no simulator. The
captured deck is then run once with the original timeout, followed by strict
OP/AC validation. This is an observation, never S2 or a calibrated prediction.
"""
import json
from pathlib import Path
import resource
import subprocess
import time

import numpy as np
import ota_frozen_bench
from src.spice_validation import validate_analysis


def run_nominal(out, pex, cell, ports, parameters, contract, *, kind, bench_snapshot, reference_path):
    out = Path(out)
    capture_file = out / "nominal_deck_capture.json"
    actual_popen = subprocess.Popen
    launchers = []
    prefix = "\n".join([
        "import json,subprocess,sys",
        "from pathlib import Path",
        "_capture=Path("+repr(str(capture_file))+")",
        "def _capture_original_ngspice(argv,*args,**kwargs):",
        "    if Path(str(argv[0])).name!='ngspice':raise RuntimeError('Unexpected tool during nominal deck preparation')",
        "    cwd=Path(kwargs.get('cwd') or Path.cwd())",
        "    deck=Path(str(argv[-1]));deck=deck if deck.is_absolute() else cwd/deck",
        "    text=deck.read_text()",
        "    corner=[line.split()[-1].lower() for line in text.splitlines() if line.lower().startswith('.lib ')]",
        "    if corner==['tt'] and not _capture.exists():",
        "        _capture.write_text(json.dumps({'argv':list(map(str,argv)),'cwd':str(cwd),'deck':str(deck),'timeout_s':kwargs.get('timeout'),'new_SPICE_calls_during_capture':0},indent=2)+'\\n')",
        "    raise SystemExit(0)",
        "subprocess.run=_capture_original_ngspice", ""])
    def capture_launcher(argv, *args, **kwargs):
        if len(argv) != 2 or Path(str(argv[1])).name != "run_bench.py":
            raise ValueError("Nominal preparation expected the original trusted benchmark launcher")
        launcher = Path(argv[1])
        original = launcher.read_text()
        (launcher.parent / "original_full_launcher.py").write_text(original)
        launcher.write_text(prefix+"\n"+original)
        launchers.append(str(launcher))
        return actual_popen(argv, *args, **kwargs)
    capture_started = time.monotonic()
    before_capture = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        subprocess.Popen = capture_launcher
        function = ota_frozen_bench.run_vendor_post_rc if kind in ["fvf", "legacy_miller"] else ota_frozen_bench.run_post_rc
        prepared = function(out, pex, cell, ports, parameters, contract, kind=kind,
            bench_snapshot=bench_snapshot, reference_path=reference_path)
    finally:
        subprocess.Popen = actual_popen
    after_capture = resource.getrusage(resource.RUSAGE_CHILDREN)
    capture_wall = time.monotonic()-capture_started
    capture = json.loads(capture_file.read_text())
    work = Path(capture["cwd"])
    if len(launchers) != 1 or not work.is_relative_to(out) or capture["timeout_s"] is None:
        raise ValueError("Nominal deck preparation did not retain the exact original invocation")
    # The retained function/loop itself is unchanged. Only its independent
    # trusted launcher was instrumented to stop before each simulator call.
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started, code, timed_out = time.monotonic(), None, False
    with (work / "nominal_console.log").open("w") as log:
        try:
            process = subprocess.run(capture["argv"], cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=capture["timeout_s"])
            code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    analysis_wall = time.monotonic()-started
    argv = capture["argv"]
    log = work / argv[argv.index("-o")+1]
    op = work / ("op.dat" if kind in ["five_t", "compact_miller"] else "operating_point.dat")
    ac = work / "ac.dat"
    validations = {"op": validate_analysis(op, log, contract["analysis_contracts"]["op"], code),
        "ac": validate_analysis(ac, log, contract["analysis_contracts"]["ac"], code)}
    complete = bool(not timed_out and all(row["complete"] for row in validations.values()))
    metrics, healthy = {}, False
    if complete:
        operating = np.loadtxt(op, skiprows=1, ndmin=2)[-1]
        response_data = np.loadtxt(ac, skiprows=1, ndmin=2)
        response = response_data[:, 1]+1j*response_data[:, 2]
        amplitude = np.maximum(np.abs(response), 1e-300) if kind in ["fvf", "legacy_miller"] else np.abs(response)
        gain = 20*np.log10(amplitude)
        phase = np.unwrap(np.angle(response))*180/np.pi
        crossings = np.flatnonzero((gain[:-1] >= 0) & (gain[1:] < 0))
        metrics.update(tt_gain_dB=float(gain[0]), tt_output_V=float(operating[1]),
            tt_positive_low_frequency_gain=bool(response[0].real > 0 and abs(phase[0]) < 10))
        if len(crossings):
            index = int(crossings[0])
            fraction = -gain[index]/(gain[index+1]-gain[index])
            metrics.update(tt_ugb_Hz=float(np.exp(np.log(response_data[index, 0])+fraction*np.log(response_data[index+1, 0]/response_data[index, 0]))),
                tt_phase_margin_deg=float(180+phase[index]+fraction*(phase[index+1]-phase[index])))
        supply = -float(operating[-1])
        metrics["tt_power_W"] = 1.8*supply
        if kind == "five_t":
            healthy = bool(metrics["tt_positive_low_frequency_gain"] and .15 < operating[3] < .8
                and .4 < operating[4] < 1.6 and 20e-6 < supply < 80e-6)
        elif kind == "compact_miller":
            healthy = bool(metrics["tt_positive_low_frequency_gain"] and .15 < operating[4] < .8
                and .3 < operating[6] < 1.2 and 50e-6 < supply < 160e-6)
        else:
            healthy = bool(supply > 0 and 0 < operating[1] < 1.8)
    record = {"scope": "E2_actual_nominal_TT_OP_AC_NOT_S2_NOT_CALIBRATED_PREDICTION", "kind": kind,
        "complete": complete, "operating_point_valid": healthy, "metrics": metrics,
        "units": {"tt_ugb_Hz": "Hz", "tt_gain_dB": "dB", "tt_phase_margin_deg": "deg", "tt_power_W": "W", "tt_output_V": "V"},
        "analyses": {"op": {"data": str(op), "log": str(log), "returncode": code},
            "ac": {"data": str(ac), "log": str(log), "returncode": code}}, "analysis_validation": validations,
        "timeout": timed_out, "original_timeout_s": capture["timeout_s"], "analysis_wall_seconds": analysis_wall,
        "analysis_waited_child_user_CPU_seconds": after.ru_utime-before.ru_utime,
        "analysis_waited_child_system_CPU_seconds": after.ru_stime-before.ru_stime,
        "deck_preparation_wall_seconds": capture_wall,
        "deck_preparation_waited_child_CPU_seconds": after_capture.ru_utime-before_capture.ru_utime+after_capture.ru_stime-before_capture.ru_stime,
        "new_SPICE_calls": 1, "new_Tran_DC_SS_FF_SPICE_calls": 0,
        "measurement_function_or_loop_unchanged": True, "capture_manifest": str(capture_file),
        "full_bench_completion_claimed": False, "UGB_worst_corner_prediction": None}
    (out / "nominal_measurement.json").write_text(json.dumps(record, indent=2, allow_nan=False)+"\n")
    return record
