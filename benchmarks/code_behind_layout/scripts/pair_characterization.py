"""Development differential-pair domain from fixed source and independent gold."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import gdstk
import numpy as np
from gdsfactory.components import rectangle
from glayout import sky130
from glayout.cells.elementary.diff_pair.diff_pair import diff_pair
from glayout.util.comp_utils import align_comp_to_port

sys.path.insert(0, "/work")
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
from src.spice_validation import validate_analysis

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--width", type=float, default=3)
p.add_argument("--length", type=float, default=1)
p.add_argument("--fingers", type=int, default=2)
a = p.parse_args()
out = Path.cwd()
ports = ["VP", "VN", "VDD1", "VDD2", "VTAIL", "B"]
gold = out / "pair6.spice"
# The source places two copies of each fingered branch in AB/BA order.
# Dummy terminals are all at body; they are not active tail-current devices.
gold.write_text("\n".join(["* Independent differential-pair circuit before layout",
    ".subckt pair6 " + " ".join(ports),
    f"XPLUS VDD1 VP VTAIL B sky130_fd_pr__nfet_01v8 w={a.width:g} l={a.length:g} m={2*a.fingers}",
    f"XMINUS VDD2 VN VTAIL B sky130_fd_pr__nfet_01v8 w={a.width:g} l={a.length:g} m={2*a.fingers}",
    f"XDUMMY B B B B sky130_fd_pr__nfet_01v8 w={a.width:g} l={a.length:g} m=4", ".ends pair6", ""]))
record = {"scope": "development_differential_pair_domain_not_formal_or_training", "configuration": vars(a),
    "main_finger_width_um": a.width, "parallel_fingers_per_branch": 2*a.fingers,
    "tail_current_A": 20e-6, "common_mode_V": .9, "temperature_C": 27,
    "DC_drain_clamp_V": 1.2, "AC_transient_load": {"supply_V": 1.8, "R_each_ohm": 10000, "C_each_F": 1e-12},
    "differential_input_sweep_V": {"start": -.1, "end": .1, "step": .005, "points": 41},
    "common_mode_sweep_V": {"start": .65, "end": 1.3, "step": .05, "points": 14},
    "balance_interpretation": "deterministic symmetric-device balance; no mismatch yield claim", "results": {}}

def save():
    (out / "measurements.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")

save()
(out / "consumed_diff_pair.py").write_text(Path(
    "/work/vendor/glayout/src/glayout/cells/elementary/diff_pair/diff_pair.py").read_text())
c = diff_pair(sky130, width=a.width, length=a.length, fingers=a.fingers).copy()
c = c.remove_layers([v for k, v in sky130.glayers.items() if k.endswith(("_label", "_pin"))])
bindings = {"VP": "br_multiplier_0_gate_S", "VN": "bl_multiplier_0_gate_S",
    "VDD1": "tl_multiplier_0_drain_N", "VDD2": "tr_multiplier_0_drain_N",
    "VTAIL": "bl_multiplier_0_source_S", "B": "tap_N_top_met_S"}
positions = {}
for label, key in bindings.items():
    port = c.ports[key]
    layer = sky130.layer_to_glayer(port.layer)
    marker = rectangle(size=(.14, .14), layer=sky130.get_glayer(layer + "_pin"), centered=True).copy()
    marker.add_label(label, layer=sky130.get_glayer(layer + "_label"))
    marker_ref = align_comp_to_port(marker, port, ("c", "c"))
    angle = np.deg2rad(port.orientation)
    marker_ref.move((-.1*np.cos(angle), -.1*np.sin(angle)))
    c.add(marker_ref)
    positions[label] = {"port": key, "center_um": list(map(float, port.center)), "layer": list(port.layer)}
(out / "pin_bindings.json").write_text(json.dumps(positions, indent=2) + "\n")
c = c.remove_layers([(64, 44)], include_labels=True)
c.write_gds(out / "pair6.gds")
top, = gdstk.read_gds(out / "pair6.gds").top_level()
top.flatten(); top.name = "pair6"
lib = gdstk.Library(); lib.add(top); lib.write_gds(out / "pair6.gds")
record["DRC"] = check_gds(out / "pair6.gds", out / "drc_full")
sky130.lvs_netgen(out / "pair6.gds", "pair6", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=gold, output_file_path=out / "lvs", copy_intermediate_files=True)
record["LVS"] = netgen_lvs_report(next((out / "lvs").rglob("*_lvs.rpt")).read_text())
save()
if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:
    raise SystemExit(2)
with (out / "pex.log").open("w") as log:
    extraction = subprocess.run(["bash", "/work/vendor/glayout/src/glayout/verification/run_pex.sh",
        str(out / "pair6.gds"), "pair6"], stdout=log, stderr=subprocess.STDOUT, timeout=180)
pex = out / "pair6_pex.spice"
record["RC"] = rc_netlist_inventory(pex.read_text(), "pair6_rc", ports)
record["pex_returncode"] = extraction.returncode
save()
if extraction.returncode or not record["RC"]["has_real_RC"]:
    raise SystemExit(2)
for fidelity, netlist, cell in [("prelayout", gold, "pair6"), ("post_rc", pex, "pair6_rc")]:
    declaration = next(x.split() for x in netlist.read_text().splitlines() if x.lower().startswith(".subckt " + cell + " "))
    bind = {"VP": "vp", "VN": "vn", "VDD1": "d1", "VDD2": "d2", "VTAIL": "tail", "B": "0"}
    nodes = [bind[key.upper()] for key in declaration[2:]]
    record["results"][fidelity] = {}
    for corner in ["tt", "ss", "ff"]:
        work = out / fidelity / corner; work.mkdir(parents=True)
        (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
        result = {"analyses": {}, "metrics": {}}
        common = ["Independent differential pair development measurements",
            ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
            ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16", ".temp 27",
            ".include " + str(netlist), "XDUT " + " ".join(nodes) + " " + cell,
            "ITA tail 0 20u", "VCM cm 0 .9", "EPLUS vp cm diff 0 .5", "EMINUS vn cm diff 0 -.5"]
        dc_setup = ["VDIFF diff 0 0", "VD1 d1 0 1.2", "VD2 d2 0 1.2",
            ".save v(vp) v(vn) v(tail) i(vd1) i(vd2)"]
        loaded = ["VSUPPLY vdd 0 1.8", "RD1 vdd d1 10k", "RD2 vdd d2 10k", "CL1 d1 0 1p", "CL2 d2 0 1p"]
        controls = [".control", "set wr_vecnames", "set wr_singlescale"]
        analyses = {
            "differential": (dc_setup + controls + ["op", "wrdata op.dat v(tail) i(vd1) i(vd2)",
                "dc VDIFF -.1 .1 .005", "wrdata differential.dat v(vp) v(vn) v(tail) i(vd1) i(vd2)"],
                {"kind": "dc", "columns": 6, "start": -.1, "end": .1, "points": 41, "scale": "linear"}),
            "common_mode": (dc_setup + controls + ["dc VCM .65 1.3 .05",
                "wrdata common_mode.dat v(vp) v(vn) v(tail) i(vd1) i(vd2)"],
                {"kind": "dc", "columns": 6, "start": .65, "end": 1.3, "points": 14, "scale": "linear"}),
            "ac": (loaded + ["VDIFF diff 0 dc 0 ac 1", ".save v(d1) v(d2)"] + controls +
                ["ac dec 30 10 1G", "let response=v(d2)-v(d1)", "wrdata ac.dat real(response) imag(response)"],
                {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 241, "scale": "log"}),
            "transient": (loaded + ["VDIFF diff 0 pulse(-.01 .01 1u 10n 10n 1u 2u)", ".save v(diff) v(d1) v(d2)"] + controls +
                ["tran 2n 4u", "wrdata transient.dat v(diff) v(d1) v(d2)"],
                {"kind": "transient", "columns": 4, "start": 0, "end": 4e-6,
                 "required_windows": [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]})}
        for analysis, (commands, contract) in analyses.items():
            (work / (analysis + ".spice")).write_text("\n".join(common + commands + ["quit", ".endc", ".end", ""]))
            with (work / (analysis + "_console.log")).open("w") as log:
                try:
                    sim = subprocess.run(["ngspice", "-b", "-o", analysis + ".log", analysis + ".spice"],
                        cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=120)
                    status = {"returncode": sim.returncode}
                except subprocess.TimeoutExpired:
                    status = {"returncode": None, "timeout": True}
            status["validation"] = validate_analysis(work / (analysis + ".dat"), work / (analysis + ".log"), contract, status["returncode"])
            result["analyses"][analysis] = status
        result["OP_validation"] = validate_analysis(work / "op.dat", work / "differential.log",
            {"kind": "op", "columns": 4}, result["analyses"]["differential"]["returncode"])
        result["complete"] = all(x["validation"]["complete"] for x in result["analyses"].values()) and result["OP_validation"]["complete"]
        if result["complete"]:
            dc = np.loadtxt(work / "differential.dat", skiprows=1, ndmin=2)
            cm = np.loadtxt(work / "common_mode.dat", skiprows=1, ndmin=2)
            ac = np.loadtxt(work / "ac.dat", skiprows=1, ndmin=2)
            tran = np.loadtxt(work / "transient.dat", skiprows=1, ndmin=2)
            plus, minus = -dc[:, 4], -dc[:, 5]
            differential_current = plus-minus
            center = int(np.argmin(abs(dc[:, 0])))
            response = ac[:, 1]+1j*ac[:, 2]
            gain = 20*np.log10(np.abs(response))
            crossing = np.flatnonzero(gain <= gain[0]-3)
            bandwidth = None
            if len(crossing) and crossing[0] > 0:
                i = int(crossing[0]); fraction = (gain[0]-3-gain[i-1])/(gain[i]-gain[i-1])
                bandwidth = float(np.exp(np.log(ac[i-1, 0])+fraction*np.log(ac[i, 0]/ac[i-1, 0])))
            result["metrics"] = {"differential_transconductance_S": float(np.gradient(differential_current, dc[:, 0])[center]),
                "zero_input_branch_difference_A": float(differential_current[center]),
                "zero_input_relative_branch_imbalance": float(differential_current[center]/20e-6),
                "zero_input_tail_V": float(dc[center, 3]),
                "tail_current_sum_A": float(plus[center]+minus[center]),
                "loaded_differential_gain_10Hz_V_per_V": float(abs(response[0])),
                "loaded_bandwidth_3dB_Hz": bandwidth,
                "transient_output_difference_min_V": float((tran[:, 3]-tran[:, 2]).min()),
                "transient_output_difference_max_V": float((tran[:, 3]-tran[:, 2]).max()),
                "common_mode_curve": [{"input_common_mode_V": float(row[0]), "tail_V": float(row[3]),
                    "branch_plus_A": float(-row[4]), "branch_minus_A": float(-row[5])} for row in cm]}
        record["results"][fidelity][corner] = result
        save(); print(json.dumps({"fidelity": fidelity, "corner": corner, **result}), flush=True)
record["flow_complete"] = all(x["complete"] for cs in record["results"].values() for x in cs.values())
save()
raise SystemExit(0 if record["flow_complete"] else 2)
