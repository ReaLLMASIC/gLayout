"""Development current-mirror sizing domain with independent per-finger gold."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import traceback

import gdstk
import numpy as np
from gdsfactory.components import rectangle
from glayout import sky130
from glayout.cells.elementary.current_mirror.current_mirror import current_mirror
from glayout.util.comp_utils import align_comp_to_port

sys.path.insert(0, "/work")
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
from src.spice_validation import validate_analysis

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--width", type=float, required=True)
p.add_argument("--length", type=float, required=True)
p.add_argument("--numcols", type=int, default=2)
p.add_argument("--device", choices=["pfet", "nfet"], default="pfet")
p.add_argument("--bias-ua", type=float, default=10)
a = p.parse_args()
out = Path.cwd()
name = "mirror4"
ports = ["VREF", "VOUT", "VSS", "B"]
reference = out / (name + ".spice")
record = {"scope": "development_mirror_domain_not_formal_or_training",
    "configuration": vars(a), "ratio": "1:1", "fingers_per_group": 1,
    "gold_main_device_width_um": a.width, "gold_main_parallel_multiplier": a.numcols,
    "supply_V": 1.8, "temperature_C": 27, "nominal_output_V": .9,
    "reference_current_A": a.bias_ua * 1e-6,
    "compliance_sweep_V": {"start": .05, "end": 1.75, "step": .025, "points": 69},
    "input_current_sweep_A": {"start": 2e-6, "end": 20e-6, "step": 2e-6, "points": 10},
    "diagnostic_compliance_relative_error_limit": .05,
    "diagnostic_limit_status": "declared_development_probe_not_frozen_S2",
    "results": {}}

def save():
    (out / "measurements.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")

save()
model = "sky130_fd_pr__" + a.device + "_01v8"
# Main devices retain the actual physical finger width. Aggregating numcols
# into one wide MOS changes BSIM width-bin behavior even when LVS summed W agrees.
reference.write_text("\n".join(["* Independent 1:1 mirror fixed before physical comparison",
    ".subckt mirror4 " + " ".join(ports),
    f"XREF VREF VREF VSS B {model} w={a.width:g} l={a.length:g} m={a.numcols}",
    f"XOUT VOUT VREF VSS B {model} w={a.width:g} l={a.length:g} m={a.numcols}",
    f"XDUMMY B B B B {model} w={a.width:g} l={a.length:g} m=2", ".ends mirror4", ""]))
(out / "consumed_current_mirror.py").write_text(Path(
    "/work/vendor/glayout/src/glayout/cells/elementary/current_mirror/current_mirror.py").read_text())

try:
    component = current_mirror(sky130, numcols=a.numcols, device=a.device,
        width=a.width, length=a.length, fingers=1, with_labels=False).copy()
    removable = [v for k, v in sky130.glayers.items() if k.endswith(("_label", "_pin"))]
    component = component.remove_layers(removable)
    bindings = {"VREF": "fet_A_drain_N", "VOUT": "fet_B_drain_N",
                "VSS": "fet_A_source_W", "B": "welltie_N_top_met_N"}
    positions = {}
    for label, port_name in bindings.items():
        port = component.ports[port_name]
        layer = sky130.layer_to_glayer(port.layer)
        marker = rectangle(size=(.14, .14), layer=sky130.get_glayer(layer + "_pin"), centered=True).copy()
        marker.add_label(label, layer=sky130.get_glayer(layer + "_label"))
        marker_ref = align_comp_to_port(marker, port, ("c", "c"))
        angle = np.deg2rad(port.orientation)
        marker_ref.move((-.1*np.cos(angle), -.1*np.sin(angle)))
        component.add(marker_ref)
        positions[label] = {"port": port_name, "center_um": list(map(float, port.center)), "layer": list(port.layer)}
    (out / "pin_bindings.json").write_text(json.dumps(positions, indent=2) + "\n")
    component = component.remove_layers([(64, 44)], include_labels=True)
    component.write_gds(out / (name + ".gds"))
    top, = gdstk.read_gds(out / (name + ".gds")).top_level()
    top.flatten(); top.name = name
    library = gdstk.Library(); library.add(top); library.write_gds(out / (name + ".gds"))
    record["DRC"] = check_gds(out / (name + ".gds"), out / "drc_full")
    sky130.lvs_netgen(out / (name + ".gds"), name, pdk_root="/foss/pdks",
        magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
        lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
        lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
        netlist=reference, output_file_path=out / "lvs", copy_intermediate_files=True)
    record["LVS"] = netgen_lvs_report(next((out / "lvs").rglob("*_lvs.rpt")).read_text())
    save()
    if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:
        record["flow_complete"] = False; save()
        raise SystemExit(2)
    with (out / "pex.log").open("w") as log:
        pex = subprocess.run(["bash", "/work/vendor/glayout/src/glayout/verification/run_pex.sh",
            str(out / (name + ".gds")), name], stdout=log, stderr=subprocess.STDOUT, timeout=180)
    record["pex_returncode"] = pex.returncode
    extracted = out / (name + "_pex.spice")
    record["RC"] = rc_netlist_inventory(extracted.read_text(), name + "_rc", ports)
    save()
    if pex.returncode or not record["RC"]["has_real_RC"]:
        record["flow_complete"] = False; save()
        raise SystemExit(2)

    polarity = 1 if a.device == "pfet" else -1
    for fidelity, netlist, cell in [("prelayout", reference, name), ("post_rc", extracted, name + "_rc")]:
        declaration = next(line.split() for line in netlist.read_text().splitlines()
                           if line.lower().startswith(".subckt " + cell + " "))
        binding = {"VREF": "ref", "VOUT": "out", "VSS": "vdd" if polarity == 1 else "0",
                   "B": "vdd" if polarity == 1 else "0"}
        nodes = [binding[n.upper()] for n in declaration[2:]]
        record["results"][fidelity] = {}
        for corner in ["tt", "ss", "ff"]:
            work = out / fidelity / corner; work.mkdir(parents=True)
            (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
            common = ["Independent mirror development DC qualification",
                ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
                ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16", ".temp 27",
                ".include " + str(netlist), "VSUPPLY vdd 0 1.8", "VOUT out 0 .9",
                (f"IREF ref 0 {a.bias_ua:g}u" if polarity == 1 else f"IREF vdd ref {a.bias_ua:g}u"),
                "XDUT " + " ".join(nodes) + " " + cell,
                ".save v(ref) v(out) i(vout) i(vsupply)", ".control", "set wr_vecnames", "set wr_singlescale"]
            analyses = {
                "compliance": ["op", "wrdata op.dat v(ref) v(out) i(vout) i(vsupply)",
                    "dc VOUT .05 1.75 .025", "wrdata compliance.dat v(ref) v(out) i(vout) i(vsupply)"],
                "input_gain": ["dc IREF 2u 20u 2u", "wrdata input_gain.dat v(ref) v(out) i(vout) i(vsupply)"]}
            result = {"analyses": {}, "metrics": {}}
            for analysis, commands in analyses.items():
                (work / (analysis + ".spice")).write_text("\n".join(common + commands + ["quit", ".endc", ".end", ""]))
                with (work / (analysis + "_console.log")).open("w") as log:
                    try:
                        sim = subprocess.run(["ngspice", "-b", "-o", analysis + ".log", analysis + ".spice"],
                            cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=120)
                        result["analyses"][analysis] = {"returncode": sim.returncode}
                    except subprocess.TimeoutExpired:
                        result["analyses"][analysis] = {"returncode": None, "timeout": True}
            contracts = {"op": ("op.dat", "compliance", {"kind": "op", "columns": 5}),
                "compliance": ("compliance.dat", "compliance", {"kind": "dc", "columns": 5,
                    "start": .05, "end": 1.75, "points": 69, "scale": "linear"}),
                "input_gain": ("input_gain.dat", "input_gain", {"kind": "dc", "columns": 5,
                    "start": 2e-6, "end": 20e-6, "points": 10, "scale": "linear"})}
            result["analysis_validation"] = {key: validate_analysis(work / filename, work / (analysis + ".log"),
                contract, result["analyses"][analysis]["returncode"])
                for key, (filename, analysis, contract) in contracts.items()}
            result["complete"] = all(x["complete"] for x in result["analysis_validation"].values())
            if result["complete"]:
                op = np.loadtxt(work / "op.dat", skiprows=1, ndmin=2)[0]
                curve = np.loadtxt(work / "compliance.dat", skiprows=1, ndmin=2)
                gain_curve = np.loadtxt(work / "input_gain.dat", skiprows=1, ndmin=2)
                voltage, current = curve[:, 2], polarity * curve[:, 3]
                ratio = current / (a.bias_ua * 1e-6)
                conductance = np.gradient(current, voltage)
                nominal = int(np.argmin(np.abs(voltage - .9)))
                passed = (np.abs(ratio - 1) <= .05) & (current > 0)
                edges = np.diff(np.r_[False, passed, False].astype(int))
                intervals = [[float(voltage[s]), float(voltage[e-1])]
                             for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))]
                gain_current = polarity * gain_curve[:, 3]
                input_gain = np.gradient(gain_current, gain_curve[:, 0])
                center = int(np.argmin(np.abs(gain_curve[:, 0] - a.bias_ua*1e-6)))
                g = float(conductance[nominal])
                dc_nominal = curve[nominal]
                result["metrics"] = {"nominal_metric_source": "steady_DC_sweep_row_at_0p9V",
                    "reference_bias_V": float(dc_nominal[1]),
                    "nominal_output_current_A": float(current[nominal]),
                    "nominal_supply_current_A": float(-dc_nominal[4]), "nominal_power_W": float(-1.8 * dc_nominal[4]),
                    "OP_solver_diagnostic": {"output_current_A": float(polarity * op[3]),
                        "relative_current_difference_from_steady_DC": float((polarity*op[3]-current[nominal])/(a.bias_ua*1e-6)),
                        "reference_bias_difference_V": float(op[1]-dc_nominal[1])},
                    "nominal_current_ratio_A_per_A": float(ratio[nominal]),
                    "nominal_relative_current_error": float(ratio[nominal] - 1),
                    "nominal_output_conductance_S": g,
                    "nominal_output_resistance_ohm": 1/abs(g) if g != 0 else None,
                    "incremental_input_current_gain_A_per_A": float(input_gain[center]),
                    "compliance_intervals_at_5percent_V": intervals,
                    "minimum_sampled_compliance_headroom_V": (float(1.8-voltage[passed].max()) if polarity == 1
                        else float(voltage[passed].min())) if passed.any() else None,
                    "nominal_within_5percent_probe": bool(passed[nominal]),
                    "dc_curve": [{"output_V": float(v), "output_current_A": float(i), "ratio_A_per_A": float(r),
                                  "relative_current_error": float(r-1)} for v, i, r in zip(voltage, current, ratio)]}
            record["results"][fidelity][corner] = result
            save()
            print(json.dumps({"fidelity": fidelity, "corner": corner, "complete": result["complete"],
                "metrics": {k: v for k, v in result["metrics"].items() if k != "dc_curve"}}), flush=True)
    record["flow_complete"] = all(x["complete"] for corners in record["results"].values() for x in corners.values())
    save()
except Exception as error:
    record["flow_complete"] = False
    record["infrastructure_or_generation_exception"] = str(error)
    record["traceback"] = traceback.format_exc()
    save()
    raise
raise SystemExit(0 if record["flow_complete"] else 2)
