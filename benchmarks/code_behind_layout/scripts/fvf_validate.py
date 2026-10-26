"""Development-only FVF independent-reference LVS and actual circuit measurements."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import numpy as np
import gdstk

sys.path.insert(0, "/work")
sys.path.insert(0, "/work/scripts")
from fvf_reference import PORTS, intended_reference
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
from src.spice_validation import validate_analysis
from glayout import sky130

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--gds-relative", default="super_class_ab_ota/super_class_ab_ota.baseline.gds")
p.add_argument("--fidelity", choices=["prelayout", "post_rc", "both"], default="prelayout")
p.add_argument("--skip-physical", action="store_true")
p.add_argument("--physical-only", action="store_true")
p.add_argument("--analysis-timeout", type=int, default=180)
p.add_argument("--corners", nargs="+", choices=["tt", "ss", "ff"], default=["tt", "ss", "ff"])
p.add_argument("--load-pf", type=float, default=1)
a = p.parse_args()
out = Path.cwd()
source = Path(os.environ["PROBE_INPUT"])
ref = out / "fvf7.spice"
ref.write_text(intended_reference())
record = {"scope": "development_independent_FVF_reference_no_S2_claim", "results": {},
          "reference_provenance": "flat intended transistor connectivity fixed independently before LVS",
          "supply_V": 1.8, "bias_currents_A": [1e-5, 1e-5], "load_F": a.load_pf*1e-12,
          "requested_corners": a.corners, "reference_version": "flat_intended_parallel_finger_widths_v2",
          "temperature_C": 27, "common_mode_V": .9, "transient_window_s": 4e-6,
          "follower_dc_input_range_V": [.6, 1.2], "follower_dc_step_V": .1}

def save():
    (out / "measurements.json").write_text(json.dumps(record, indent=2) + "\n")

if not a.skip_physical:
    top, = gdstk.read_gds(source / a.gds_relative).top_level()
    top.flatten(); top.name = "fvf7"
    lib = gdstk.Library(); lib.add(top); lib.write_gds(out / "fvf7.gds")
    record["DRC"] = check_gds(out / "fvf7.gds", out / "drc_full")
    sky130.lvs_netgen(out / "fvf7.gds", "fvf7", pdk_root="/foss/pdks",
        magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
        lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
        lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
        netlist=ref, output_file_path=out / "lvs", copy_intermediate_files=True)
    report = next((out / "lvs").rglob("*_lvs.rpt"))
    record["LVS"] = netgen_lvs_report(report.read_text())
    save()
    if a.physical_only:
        raise SystemExit(0 if record["DRC"]["is_clean"] and record["LVS"]["is_clean"] else 2)

if a.fidelity in ["post_rc", "both"]:
    if a.skip_physical:
        raise SystemExit("Post-RC flow requires retained physical checks")
    if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:
        raise SystemExit("Independent intended LVS and completed full DRC must pass before post-RC simulation")
    with (out / "pex.log").open("w") as log:
        extraction = subprocess.run(["bash", "/work/vendor/glayout/src/glayout/verification/run_pex.sh",
            str(out / "fvf7.gds"), "fvf7"], stdout=log, stderr=subprocess.STDOUT, timeout=240)
    record["pex_returncode"] = extraction.returncode
    record["RC"] = rc_netlist_inventory((out / "fvf7_pex.spice").read_text(), "fvf7_rc", PORTS)
    save()
    if extraction.returncode or not record["RC"]["has_real_RC"]:
        raise SystemExit("FVF RC extraction invalid; preserve output without simulation acceptance")

for fidelity in (["prelayout", "post_rc"] if a.fidelity == "both" else [a.fidelity]):
    netlist = ref if fidelity == "prelayout" else out / "fvf7_pex.spice"
    cell = "fvf7" if fidelity == "prelayout" else "fvf7_rc"
    decl = next(s.split() for s in netlist.read_text().splitlines()
                if s.lower().startswith(".subckt " + cell.lower() + " "))
    binding = {"AVDD": "vdd", "AVSS": "0", "INP": "vp", "INM": "vn", "VOUT": "out",
               "NBC_10U": "bias1", "NB_10U": "bias2"}
    nodes = [binding[n.upper()] for n in decl[2:]]
    record["results"][fidelity] = {}
    for corner in a.corners:
        work = out / fidelity / corner; work.mkdir(parents=True)
        (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
        common = ["Independent intended FVF OTA development measurements",
            ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
            ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
            ".temp 27", ".include " + str(netlist),
            "VSUPPLY vdd 0 1.8", "IBIAS1 vdd bias1 10u", "IBIAS2 vdd bias2 10u", f"CLOAD out 0 {a.load_pf:g}p",
            "XDUT " + " ".join(nodes) + " " + cell,
            ".save v(out) v(vp) v(vn) v(bias1) v(bias2) i(vsupply)"]
        analyses = {
            "ac": ["VIN vp 0 dc .9 ac 1", "LSERVO out vn 1G", "CAC vn 0 1G", ".control", "op",
                "set wr_vecnames", "set wr_singlescale",
                "wrdata operating_point.dat v(out) v(vp) v(vn) v(bias1) v(bias2) i(vsupply)",
                "ac dec 30 10 1G", "wrdata ac.dat real(v(out)) imag(v(out))", "quit", ".endc", ".end", ""],
            "transient": ["VIN vp 0 pulse(.89 .91 1u 10n 10n 1u 2u)", "VFEEDBACK out vn 0", ".control",
                "set wr_vecnames", "set wr_singlescale", "tran 5n 4u",
                "wrdata transient.dat v(vp) v(out) i(vsupply)", "quit", ".endc", ".end", ""],
            "dc": ["VIN vp 0 .9", "VFEEDBACK out vn 0", ".control", "set wr_vecnames", "set wr_singlescale",
                "dc VIN .6 1.2 .1", "wrdata dc.dat v(vp) v(out) i(vsupply)", "quit", ".endc", ".end", ""]}
        result = {"analyses": {}, "metrics": {}}
        for name, tail in analyses.items():
            (work / (name + ".spice")).write_text("\n".join(common + tail))
            with (work / (name + "_console.log")).open("w") as log:
                try:
                    sim = subprocess.run(["ngspice", "-b", "-o", name + "_ngspice.log", name + ".spice"],
                        cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=a.analysis_timeout)
                    result["analyses"][name] = {"returncode": sim.returncode}
                except subprocess.TimeoutExpired:
                    result["analyses"][name] = {"returncode": None, "timeout": True}
        def data(name, columns):
            path = work / name
            if not path.exists(): return None
            try:
                values = np.loadtxt(path, skiprows=1, ndmin=2)
                return values if values.shape[1] == columns and np.all(np.isfinite(values)) else None
            except ValueError:
                return None
        op, ac = data("operating_point.dat", 7), data("ac.dat", 3)
        tran, dc = data("transient.dat", 4), data("dc.dat", 4)
        if op is not None:
            r = op[-1]
            result["metrics"].update(output_bias_V=float(r[1]), vp_V=float(r[2]), vn_V=float(r[3]),
                bias1_V=float(r[4]), bias2_V=float(r[5]), power_W=float(-1.8*r[6]))
        if ac is not None:
            response = ac[:, 1] + 1j*ac[:, 2]
            gain = 20*np.log10(np.maximum(np.abs(response), 1e-300))
            phase = np.unwrap(np.angle(response))*180/np.pi
            crossings = np.flatnonzero((gain[:-1] >= 0) & (gain[1:] < 0))
            result["metrics"].update(gain_at_10Hz_dB=float(gain[0]), gain_at_10Hz_real=float(response[0].real),
                descending_unity_crossings=len(crossings))
            if len(crossings):
                i = int(crossings[0]); t = -gain[i]/(gain[i+1]-gain[i])
                result["metrics"].update(ugb_Hz=float(np.exp(np.log(ac[i, 0])+t*np.log(ac[i+1, 0]/ac[i, 0]))),
                    phase_margin_deg=float(180+phase[i]+t*(phase[i+1]-phase[i])))
        if tran is not None:
            time, vin, vout = tran[:, 0], tran[:, 1], tran[:, 2]
            mask = (time > 1.8e-6) & (time < 1.99e-6)
            result["metrics"].update(transient_output_min_V=float(vout.min()), transient_output_max_V=float(vout.max()),
                positive_step_final_error_V=float(np.mean(vout[mask]-vin[mask])) if mask.any() else None)
        if dc is not None:
            result["metrics"]["dc_follower_points"] = [{"input_V": float(r[1]), "output_V": float(r[2]),
                "error_V": float(r[2]-r[1])} for r in dc]
        result["all_waveforms_finite"] = all(d is not None for d in [op, ac, tran, dc])
        result["all_simulators_exited_zero"] = all(r["returncode"] == 0 for r in result["analyses"].values())
        contracts = {
            "op": ("operating_point.dat", "ac", {"kind": "op", "columns": 7}),
            "ac": ("ac.dat", "ac", {"kind": "ac", "columns": 3, "points": 241,
                "start": 10, "end": 1e9, "scale": "log"}),
            "transient": ("transient.dat", "transient", {"kind": "transient", "columns": 4,
                "start": 0, "end": 4e-6, "required_windows": [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]}),
            "dc": ("dc.dat", "dc", {"kind": "dc", "columns": 4, "points": 7,
                "start": .6, "end": 1.2, "scale": "linear"})}
        result["analysis_validation"] = {name: validate_analysis(work / filename,
            work / (analysis + "_ngspice.log"), contract, result["analyses"][analysis]["returncode"])
            for name, (filename, analysis, contract) in contracts.items()}
        record["results"][fidelity][corner] = result
        save(); print(json.dumps({"fidelity": fidelity, "corner": corner, **result}), flush=True)
record["simulation_flow_complete"] = all(r["all_waveforms_finite"] and r["all_simulators_exited_zero"]
    and all(v["complete"] for v in r["analysis_validation"].values())
    for corners in record["results"].values() for r in corners.values())
record["physical_flow_complete"] = (record.get("DRC", {}).get("is_clean", False)
    and record.get("LVS", {}).get("is_clean", False) and record.get("RC", {}).get("has_real_RC", False)
    and record["simulation_flow_complete"] and a.fidelity == "both")
record["full_tt_ss_ff_flow_complete"] = record["physical_flow_complete"] and set(a.corners) == {"tt", "ss", "ff"}
save()
raise SystemExit(0 if record["simulation_flow_complete"] else 2)
