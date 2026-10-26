"""Development local-feedback follower actual per-finger domain characterization."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import gdstk
from gdsfactory.components import rectangle
from glayout import sky130
from glayout.cells.elementary.FVF.fvf import flipped_voltage_follower
from glayout.util.comp_utils import align_comp_to_port

sys.path.insert(0, "/work")
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
from src.spice_validation import validate_analysis

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--width", type=float, default=4.15)
p.add_argument("--length", type=float, default=2)
a = p.parse_args()
out = Path.cwd()
ref = out / "follower4.spice"
ref.write_text("\n".join(["* Independent intended two-transistor FVF reference",
    ".subckt follower4 VIN VBULK VOUT IB",
    f"XINPUT IB VIN VOUT VBULK sky130_fd_pr__nfet_01v8 w={a.width:g} l={a.length:g} m=2",
    f"XSHUNT VOUT IB VBULK VBULK sky130_fd_pr__nfet_01v8 w={a.width:g} l={a.length:g} m=2",
    f"XDUMMY VBULK VBULK VBULK VBULK sky130_fd_pr__nfet_01v8 w={a.width:g} l={a.length:g} m=4",
    ".ends follower4", ""]))

c = flipped_voltage_follower(sky130, width=(a.width, a.width), length=(a.length, a.length), fingers=(2, 2),
    multipliers=(1, 1), with_dnwell=False, with_labels=False).copy()
c = c.remove_layers([v for k, v in sky130.glayers.items() if k.endswith(("_label", "_pin"))])
bindings = {"VIN": "A_multiplier_0_gate_N", "VBULK": "B_tie_N_top_met_N",
            "VOUT": "A_source_bottom_met_N", "IB": "A_drain_bottom_met_N"}
positions = {}
for label, name in bindings.items():
    port = c.ports[name]
    layer = sky130.layer_to_glayer(port.layer)
    # Place the marker inside its north-facing wire rather than crossing its edge.
    pin = rectangle(size=(.14, .14), layer=sky130.get_glayer(layer + "_pin"), centered=True).copy()
    pin.add_label(label, layer=sky130.get_glayer(layer + "_label"))
    marker_ref = align_comp_to_port(pin, port, ("c", "c"))
    angle = np.deg2rad(port.orientation)
    marker_ref.move((-.1*np.cos(angle), -.1*np.sin(angle)))
    c.add(marker_ref)
    positions[label] = {"port": name, "center_um": list(map(float, port.center)), "layer": list(port.layer)}
(out / "pin_bindings.json").write_text(json.dumps(positions, indent=2) + "\n")
c = c.remove_layers([(64, 44)], include_labels=True)
c.write_gds(out / "follower4.gds")
top, = gdstk.read_gds(out / "follower4.gds").top_level()
top.flatten(); top.name = "follower4"
library = gdstk.Library(); library.add(top); library.write_gds(out / "follower4.gds")

record = {"scope": "development_local_feedback_follower_not_formal_or_training",
    "configuration": vars(a), "gold_width_per_finger_um": a.width, "gold_parallel_fingers": 2,
    "supply_V": 1.8, "bias_current_A": 1e-5, "common_mode_V": .9, "temperature_C": 27,
    "load_F": 1e-12, "dc_input_V": {"start": .75, "end": 1.25, "step": .05, "points": 11},
    "interpretation": "FVF level shift is intrinsic; gain and output impedance do not assume unity DC voltage tracking",
    "results": {}}

def save():
    (out / "measurements.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")

save()
(out / "consumed_fvf.py").write_text(Path("/work/vendor/glayout/src/glayout/cells/elementary/FVF/fvf.py").read_text())
record["DRC"] = check_gds(out / "follower4.gds", out / "drc_full")
sky130.lvs_netgen(out / "follower4.gds", "follower4", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=ref, output_file_path=out / "lvs", copy_intermediate_files=True)
record["LVS"] = netgen_lvs_report(next((out / "lvs").rglob("*_lvs.rpt")).read_text())
save()
if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:
    raise SystemExit(2)
with (out / "pex.log").open("w") as log:
    extraction = subprocess.run(["bash", "/work/vendor/glayout/src/glayout/verification/run_pex.sh",
        str(out / "follower4.gds"), "follower4"], stdout=log, stderr=subprocess.STDOUT, timeout=180)
pex = out / "follower4_pex.spice"
record["RC"] = rc_netlist_inventory(pex.read_text(), "follower4_rc", list(bindings))
record["pex_returncode"] = extraction.returncode
save()
if extraction.returncode or not record["RC"]["has_real_RC"]:
    raise SystemExit(2)
for fidelity, netlist, cell in [("prelayout", ref, "follower4"), ("post_rc", pex, "follower4_rc")]:
    declaration = next(x.split() for x in netlist.read_text().splitlines() if x.lower().startswith(".subckt " + cell + " "))
    binding = {"VIN": "in", "VBULK": "0", "VOUT": "out", "IB": "ib"}
    nodes = [binding[p.upper()] for p in declaration[2:]]
    record["results"][fidelity] = {}
    for corner in ["tt", "ss", "ff"]:
        work = out / fidelity / corner; work.mkdir(parents=True)
        (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
        result = {"analyses": {}, "metrics": {}}
        common = ["Independent FVF local-feedback follower development domain",
            ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
            ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16", ".temp 27",
            ".include " + str(netlist), "XDUT " + " ".join(nodes) + " " + cell,
            "VSUPPLY vdd 0 1.8", "IBIAS vdd ib 10u", "CLOAD out 0 1p", ".save v(in) v(out) v(ib) i(vsupply)"]
        controls = [".control", "set wr_vecnames", "set wr_singlescale"]
        ac_contract = {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 241, "scale": "log"}
        analyses = {
            "gain": (["VIN in 0 dc .9 ac 1"] + controls + ["op", "wrdata op.dat v(out) v(ib) i(vsupply)",
                "ac dec 30 10 1G", "wrdata gain.dat real(v(out)) imag(v(out))"], ac_contract),
            "impedance": (["VIN in 0 .9", "ITEST out 0 dc 0 ac 1"] + controls +
                ["ac dec 30 10 1G", "wrdata impedance.dat real(v(out)) imag(v(out))"], ac_contract),
            "dc": (["VIN in 0 .9"] + controls + ["dc VIN .75 1.25 .05", "wrdata dc.dat v(in) v(out) v(ib) i(vsupply)"],
                {"kind": "dc", "columns": 5, "start": .75, "end": 1.25, "points": 11, "scale": "linear"}),
            "transient": (["VIN in 0 pulse(.89 .91 1u 10n 10n 1u 2u)"] + controls +
                ["tran 2n 4u", "wrdata transient.dat v(in) v(out) v(ib)"],
                {"kind": "transient", "columns": 4, "start": 0, "end": 4e-6,
                 "required_windows": [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]})}
        for analysis, (commands, contract) in analyses.items():
            (work / (analysis + ".spice")).write_text("\n".join(common + commands + ["quit", ".endc", ".end", ""]))
            with (work / (analysis + "_console.log")).open("w") as log:
                try:
                    process = subprocess.run(["ngspice", "-b", "-o", analysis + ".log", analysis + ".spice"],
                        cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=120)
                    status = {"returncode": process.returncode}
                except subprocess.TimeoutExpired:
                    status = {"returncode": None, "timeout": True}
            status["validation"] = validate_analysis(work / (analysis + ".dat"), work / (analysis + ".log"), contract, status["returncode"])
            result["analyses"][analysis] = status
        result["OP_validation"] = validate_analysis(work / "op.dat", work / "gain.log", {"kind": "op", "columns": 4}, result["analyses"]["gain"]["returncode"])
        result["complete"] = all(x["validation"]["complete"] for x in result["analyses"].values()) and result["OP_validation"]["complete"]
        if result["complete"]:
            dc = np.loadtxt(work / "dc.dat", skiprows=1, ndmin=2)
            ac = np.loadtxt(work / "gain.dat", skiprows=1, ndmin=2)
            z = np.loadtxt(work / "impedance.dat", skiprows=1, ndmin=2)
            tran = np.loadtxt(work / "transient.dat", skiprows=1, ndmin=2)
            response = ac[:, 1]+1j*ac[:, 2]
            db = 20*np.log10(abs(response))
            crossings = np.flatnonzero(db <= db[0]-3)
            bandwidth = None
            if len(crossings) and crossings[0] > 0:
                i = int(crossings[0]); fraction = (db[0]-3-db[i-1])/(db[i]-db[i-1])
                bandwidth = float(np.exp(np.log(ac[i-1, 0])+fraction*np.log(ac[i, 0]/ac[i-1, 0])))
            nominal = dc[np.argmin(abs(dc[:, 1]-.9))]
            high = (tran[:, 0] > 1.8e-6) & (tran[:, 0] < 1.99e-6)
            low = (tran[:, 0] > 2.8e-6) & (tran[:, 0] < 2.99e-6)
            result["metrics"] = {"nominal_output_V": float(nominal[2]), "nominal_bias_V": float(nominal[3]),
                "nominal_level_shift_V": float(nominal[1]-nominal[2]),
                "voltage_gain_10Hz_V_per_V": float(abs(response[0])), "bandwidth_3dB_Hz": bandwidth,
                "output_impedance_10Hz_ohm": float(abs(z[0, 1]+1j*z[0, 2])),
                "nominal_supply_power_W": float(-1.8*nominal[4]),
                "transient_positive_plateau_V": float(tran[high, 2].mean()),
                "transient_negative_plateau_V": float(tran[low, 2].mean()),
                "transient_output_min_V": float(tran[:, 2].min()), "transient_output_max_V": float(tran[:, 2].max()),
                "dc_transfer_curve": [{"input_V": float(row[1]), "output_V": float(row[2]), "bias_V": float(row[3])} for row in dc]}
        record["results"][fidelity][corner] = result
        save(); print(json.dumps({"fidelity": fidelity, "corner": corner, **result}), flush=True)
record["flow_complete"] = all(x["complete"] for cs in record["results"].values() for x in cs.values())
save()
raise SystemExit(0 if record["flow_complete"] else 2)
