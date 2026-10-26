"""Development TG on resistance, off leakage and loaded transient domain."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import gdstk
import numpy as np
from gdsfactory.components import rectangle
from glayout import sky130
from glayout.cells.elementary.transmission_gate.transmission_gate import transmission_gate
from glayout.util.comp_utils import align_comp_to_port

sys.path.insert(0, "/work")
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
from src.spice_validation import validate_analysis

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--width", type=float, default=2)
p.add_argument("--length", type=float, default=.5)
a = p.parse_args()
out = Path.cwd()
ports = ["VIN", "VSS", "VOUT", "VCC", "VGP", "VGN"]
gold = out / "tg6.spice"
gold.write_text("\n".join(["* Independent TG reference fixed before generation",
    ".subckt tg6 " + " ".join(ports),
    f"XNMOS VOUT VGN VIN VSS sky130_fd_pr__nfet_01v8 w={a.width:g} l={a.length:g}",
    f"XPMOS VOUT VGP VIN VCC sky130_fd_pr__pfet_01v8 w={a.width:g} l={a.length:g}",
    f"XNDUMMY VSS VSS VSS VSS sky130_fd_pr__nfet_01v8 w={a.width:g} l={a.length:g} m=2",
    f"XPDUMMY VCC VCC VCC VCC sky130_fd_pr__pfet_01v8 w={a.width:g} l={a.length:g} m=2",
    ".ends tg6", ""]))
record = {"scope": "development_TG_domain_not_formal_or_training", "configuration": vars(a),
    "supply_V": 1.8, "temperature_C": 27, "on_gate_V": {"VGN": 1.8, "VGP": 0},
    "off_gate_V": {"VGN": 0, "VGP": 1.8}, "terminal_difference_V": .01,
    "common_mode_sweep_V": {"start": .05, "end": 1.75, "step": .05, "points": 35},
    "transient_load": {"R_ohm": 100000, "C_F": 1e-12},
    "input_pulse_V": [.2, 1.6], "results": {}}

def save():
    (out / "measurements.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")

save()
(out / "consumed_transmission_gate.py").write_text(Path(
    "/work/vendor/glayout/src/glayout/cells/elementary/transmission_gate/transmission_gate.py").read_text())
c = transmission_gate(sky130, width=(a.width, a.width), length=(a.length, a.length),
    fingers=(1, 1), multipliers=(1, 1), with_labels=False).copy()
c = c.remove_layers([v for k, v in sky130.glayers.items() if k.endswith(("_label", "_pin"))])
bindings = {"VIN": "N_multiplier_0_source_E", "VSS": "N_tie_N_top_met_N",
    "VOUT": "P_multiplier_0_drain_W", "VCC": "P_tie_S_top_met_S",
    "VGP": "P_multiplier_0_gate_E", "VGN": "N_multiplier_0_gate_E"}
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
c.write_gds(out / "tg6.gds")
top, = gdstk.read_gds(out / "tg6.gds").top_level()
top.flatten(); top.name = "tg6"
lib = gdstk.Library(); lib.add(top); lib.write_gds(out / "tg6.gds")
record["DRC"] = check_gds(out / "tg6.gds", out / "drc_full")
sky130.lvs_netgen(out / "tg6.gds", "tg6", pdk_root="/foss/pdks",
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
        str(out / "tg6.gds"), "tg6"], stdout=log, stderr=subprocess.STDOUT, timeout=180)
pex = out / "tg6_pex.spice"
record["RC"] = rc_netlist_inventory(pex.read_text(), "tg6_rc", ports)
record["pex_returncode"] = extraction.returncode
save()
if extraction.returncode or not record["RC"]["has_real_RC"]:
    raise SystemExit(2)
for fidelity, netlist, cell in [("prelayout", gold, "tg6"), ("post_rc", pex, "tg6_rc")]:
    declaration = next(x.split() for x in netlist.read_text().splitlines() if x.lower().startswith(".subckt " + cell + " "))
    bind = {"VIN": "in", "VOUT": "out", "VSS": "0", "VCC": "vdd", "VGN": "gn", "VGP": "gp"}
    nodes = [bind[p.upper()] for p in declaration[2:]]
    record["results"][fidelity] = {}
    for corner in ["tt", "ss", "ff"]:
        work = out / fidelity / corner; work.mkdir(parents=True)
        (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
        result = {"analyses": {}, "metrics": {}}
        common = ["Independent TG DC and transient development domain",
            ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
            ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16", ".temp 27",
            ".include " + str(netlist), "VSUPPLY vdd 0 1.8", "XDUT " + " ".join(nodes) + " " + cell]
        for analysis in ["on", "off", "transient"]:
            gates = ["VGN gn 0 0", "VGP gp 0 1.8"] if analysis == "off" else ["VGN gn 0 1.8", "VGP gp 0 0"]
            if analysis == "transient":
                tail = ["VIN in 0 pulse(.2 1.6 1u 10n 10n 1u 2u)", "RLOAD out 0 100k", "CLOAD out 0 1p",
                    ".save v(in) v(out) i(vin) i(vsupply)", ".control", "set wr_vecnames", "set wr_singlescale",
                    "tran 2n 4u", "wrdata transient.dat v(in) v(out) i(vin) i(vsupply)"]
                contract = {"kind": "transient", "columns": 5, "start": 0, "end": 4e-6,
                            "required_windows": [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]}
            else:
                tail = ["VIN in 0 .9", "VDIFF out in .01", ".save v(in) v(out) i(vdiff) i(vsupply)",
                    ".control", "set wr_vecnames", "set wr_singlescale", "dc VIN .05 1.75 .05",
                    f"wrdata {analysis}.dat v(in) v(out) i(vdiff) i(vsupply)"]
                contract = {"kind": "dc", "columns": 5, "start": .05, "end": 1.75, "points": 35, "scale": "linear"}
            (work / (analysis + ".spice")).write_text("\n".join(common + gates + tail + ["quit", ".endc", ".end", ""]))
            with (work / (analysis + "_console.log")).open("w") as log:
                try:
                    sim = subprocess.run(["ngspice", "-b", "-o", analysis + ".log", analysis + ".spice"],
                        cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=120)
                    status = {"returncode": sim.returncode}
                except subprocess.TimeoutExpired:
                    status = {"returncode": None, "timeout": True}
            status["validation"] = validate_analysis(work / (analysis + ".dat"), work / (analysis + ".log"), contract, status["returncode"])
            result["analyses"][analysis] = status
            if status["validation"]["complete"]:
                data = np.loadtxt(work / (analysis + ".dat"), skiprows=1, ndmin=2)
                if analysis == "on":
                    resistances = .01 / np.abs(data[:, 3])
                    result["metrics"]["on_resistance_ohm"] = {"min": float(resistances.min()),
                        "max": float(resistances.max()), "at_0p9V": float(resistances[np.argmin(abs(data[:, 1]-.9))])}
                elif analysis == "off":
                    result["metrics"]["max_abs_off_terminal_current_A"] = float(np.max(np.abs(data[:, 3])))
                else:
                    high = (data[:, 0] > 1.8e-6) & (data[:, 0] < 1.99e-6)
                    low = (data[:, 0] > 2.8e-6) & (data[:, 0] < 2.99e-6)
                    result["metrics"].update(max_abs_high_settled_error_V=float(np.max(abs(data[high, 2]-data[high, 1]))),
                        max_abs_low_settled_error_V=float(np.max(abs(data[low, 2]-data[low, 1]))),
                        output_min_V=float(data[:, 2].min()), output_max_V=float(data[:, 2].max()))
        result["complete"] = all(x["validation"]["complete"] for x in result["analyses"].values())
        record["results"][fidelity][corner] = result
        save(); print(json.dumps({"fidelity": fidelity, "corner": corner, **result}), flush=True)
record["flow_complete"] = all(x["complete"] for cs in record["results"].values() for x in cs.values())
save()
raise SystemExit(0 if record["flow_complete"] else 2)
