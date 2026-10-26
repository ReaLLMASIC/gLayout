"""Standalone FVF development: independent flat reference, full DRC/LVS/RC/OP."""
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

out = Path.cwd()
c = flipped_voltage_follower(sky130, width=(4.15, 4.15), length=(2, 2), fingers=(2, 2),
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
    ref = align_comp_to_port(pin, port, ("c", "c"))
    angle = np.deg2rad(port.orientation)
    ref.move((-.1*np.cos(angle), -.1*np.sin(angle)))
    c.add(ref)
    positions[label] = {"port": name, "center_um": list(map(float, port.center)), "layer": list(port.layer)}
(out / "pin_bindings.json").write_text(json.dumps(positions, indent=2) + "\n")
c = c.remove_layers([(64, 44)], include_labels=True)
c.write_gds(out / "follower4.gds")
top, = gdstk.read_gds(out / "follower4.gds").top_level()
top.flatten(); top.name = "follower4"
library = gdstk.Library(); library.add(top); library.write_gds(out / "follower4.gds")
ref = out / "follower4.spice"
ref.write_text("\n".join(["* Independent intended two-transistor FVF reference",
    ".subckt follower4 VIN VBULK VOUT IB",
    "XINPUT IB VIN VOUT VBULK sky130_fd_pr__nfet_01v8 w=8.3 l=2",
    "XSHUNT VOUT IB VBULK VBULK sky130_fd_pr__nfet_01v8 w=8.3 l=2",
    "XDUMMY VBULK VBULK VBULK VBULK sky130_fd_pr__nfet_01v8 w=16.6 l=2",
    ".ends follower4", ""]))
record = {"scope": "development_FVF_follower_independent_reference_no_frozen_S2_claim", "corners": {}}
record["DRC"] = check_gds(out / "follower4.gds", out / "drc_full")
sky130.lvs_netgen(out / "follower4.gds", "follower4", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=ref, output_file_path=out / "lvs", copy_intermediate_files=True)
record["LVS"] = netgen_lvs_report(next((out / "lvs").rglob("*_lvs.rpt")).read_text())
(out / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
with (out / "pex.log").open("w") as log:
    pex = subprocess.run(["bash", "/work/vendor/glayout/src/glayout/verification/run_pex.sh",
        str(out / "follower4.gds"), "follower4"], stdout=log, stderr=subprocess.STDOUT, timeout=120)
net = out / "follower4_pex.spice"
record["pex_returncode"] = pex.returncode
record["RC"] = rc_netlist_inventory(net.read_text(), "follower4_rc", list(bindings))
decl = next(s.split() for s in net.read_text().splitlines() if s.lower().startswith(".subckt follower4_rc "))
binding = {"VIN": "in", "VBULK": "0", "VOUT": "out", "IB": "ib"}
nodes = [binding[p.upper()] for p in decl[2:]]
if not record["RC"]["has_real_RC"]:
    (out / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
    raise SystemExit("Full positive follower RC and terminal binding required")
for corner in ["tt", "ss", "ff"]:
    work = out / corner; work.mkdir()
    (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
    deck = ["FVF actual post-RC development operating point",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
        ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16", ".temp 27",
        ".include " + str(net), "VIN in 0 .9", "VSUPPLY vdd 0 1.8", "IBIAS vdd ib 10u", "CLOAD out 0 1p",
        "XDUT " + " ".join(nodes) + " follower4_rc", ".save v(in) v(out) v(ib) i(vsupply)", ".control", "op",
        "set wr_vecnames", "set wr_singlescale", "wrdata operating_point.dat v(in) v(out) v(ib) i(vsupply)",
        "quit", ".endc", ".end", ""]
    (work / "op.spice").write_text("\n".join(deck))
    with (work / "console.log").open("w") as log:
        try:
            sim = subprocess.run(["ngspice", "-b", "-o", "ngspice.log", "op.spice"], cwd=work,
                stdout=log, stderr=subprocess.STDOUT, timeout=90)
            result = {"returncode": sim.returncode, "numeric_output_present": False}
        except subprocess.TimeoutExpired:
            result = {"returncode": None, "timeout": True, "numeric_output_present": False}
    if (work / "operating_point.dat").exists():
        values = np.loadtxt(work / "operating_point.dat", skiprows=1, ndmin=2)
        if values.shape[1] == 5 and np.all(np.isfinite(values)):
            r = values[-1]
            result.update(numeric_output_present=True, input_V=float(r[1]), output_V=float(r[2]),
                bias_gate_V=float(r[3]), supply_current_A=float(r[4]))
    record["corners"][corner] = result
    (out / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
record["flow_complete"] = (record["DRC"]["is_clean"] and record["LVS"]["is_clean"]
    and pex.returncode == 0 and record["RC"]["has_real_RC"]
    and all(r["numeric_output_present"] and r["returncode"] == 0 and .05 < r["output_V"] < .9
            and r["supply_current_A"] < 0 for r in record["corners"].values()))
(out / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
raise SystemExit(0 if record["flow_complete"] else 2)
