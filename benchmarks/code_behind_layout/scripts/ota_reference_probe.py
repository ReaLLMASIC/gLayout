#!/usr/bin/env python3
"""Development-only independent seven-terminal OTA reference and physical probe.

Run inside the recovered EDA container, with the research checkout on PYTHONPATH.
The schematic expresses the intended stage connections before LVS is inspected.
Inherited subcell labels are removed; only actual external pin locations are named.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import re

import gdstk
from glayout import sky130
from glayout.cells.composite.opamp.opamp_twostage import opamp_twostage
from glayout.spice import Netlist
import sys

sys.path.insert(0,"/work")
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, duplicate_subcircuits


out = Path.cwd()
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--mim-cap-size",type=float,default=12)
p.add_argument("--routing-multiplier",type=int,default=2)
p.add_argument("--diffpair-fingers",type=int,default=4)
args = p.parse_args()
c = opamp_twostage(sky130,mim_cap_size=(args.mim_cap_size,args.mim_cap_size),
    rmult=args.routing_multiplier,half_diffpair_params=(6,1,args.diffpair_fingers))
old = c.info["netlist"]
(out / "legacy_reference.spice").write_text(deepcopy(old).generate_netlist())
input_stage = deepcopy(old.sub_netlists[0])
input_stage.nodes = ["VP", "VN", "VDD1", "VDD2", "IBIAS", "VSS",
                     "NBIAS_GATE", "NBIAS_DRAIN", "NBIAS_REF_SOURCE_L", "NBIAS_REF_SOURCE_R"]
gain_stage = deepcopy(old.sub_netlists[1])
gold = Netlist(circuit_name="ota7", nodes=["VDD", "GND", "DIFFPAIR_BIAS", "VP", "VN", "CS_BIAS", "VOUT"])
gold.connect_netlist(input_stage, [
    ("VP", "VP"), ("VN", "VN"), ("VDD1", "stage1_l"), ("VDD2", "stage1_r"),
    ("IBIAS", "DIFFPAIR_BIAS"), ("VSS", "GND"), ("NBIAS_GATE", "CS_BIAS"),
    ("NBIAS_DRAIN", "VOUT"), ("NBIAS_REF_SOURCE_L", "GND"), ("NBIAS_REF_SOURCE_R", "GND")])
gold.connect_netlist(gain_stage, [("VIN1", "stage1_l"), ("VIN2", "stage1_r"),
    ("VOUT", "VOUT"), ("VDD", "VDD"), ("VSS2", "compensation")])
reference = gold.generate_netlist()
(out / "ota7.spice").write_text(reference)
if duplicate_subcircuits(reference):
    raise SystemExit("Independent reference contains duplicate subcircuit names")
# These terminals follow the generator's explicit pin routing, rather than a
# permutation chosen by LVS. Input polarity is checked separately in simulation.
pin_ports = {"VDD": "pin_vdd_e4", "GND": "pin_gnd_N",
             "DIFFPAIR_BIAS": "diffpair_ibias_A_drain_E",
             "VP": "pin_plus_e3", "VN": "pin_minus_e3",
             "CS_BIAS": "pin_commonsourceibias_e2", "VOUT": "commonsource_output_E"}
pins = {}
for name, key in pin_ports.items():
    port = c.ports[key]
    glayer = sky130.layer_to_glayer(port.layer)
    pins[name] = {"port": key, "center_um": list(map(float, port.center)),
                  "metal_layer": list(port.layer),
                  "label_layer": list(sky130.get_glayer(glayer + "_label")),
                  "pin_layer": list(sky130.get_glayer(glayer + "_pin"))}
(out / "pin_bindings.json").write_text(json.dumps(pins, indent=2) + "\n")
debug_names = ["diffpair_MINUSgateroute_W_con_N", "diffpair_PLUSgateroute_E_con_N",
    "diffpair_bl_multiplier_0_gate_S", "diffpair_br_multiplier_0_gate_S",
    "commonsource_cmirror_ref_L_multiplier_0_source_W",
    "commonsource_cmirror_ref_R_multiplier_0_source_E"]
(out / "debug_ports.json").write_text(json.dumps({name: {
    "center_um": list(map(float, c.ports[name].center)), "layer": list(c.ports[name].layer)}
    for name in debug_names}, indent=2) + "\n")
c.write_gds(out / "legacy.gds")
lib = gdstk.read_gds(out / "legacy.gds")
top, = lib.top_level()
top.flatten()
top.remove(*top.labels)
# Preserve all conductive geometry, devices and capacitor layers. Remove only
# annotation/pin layers, including the pwell annotation unsupported by Magic.
annotation = {(64, 44)}
for glayer, layer in sky130.glayers.items():
    if glayer.endswith(("_label", "_pin")) and isinstance(layer, tuple):
        annotation.add(layer)
top.remove(*(p for p in top.polygons if (p.layer, p.datatype) in annotation))
top.name = "ota7"
for name, pin in pins.items():
    x, y = pin["center_um"]
    half = .15 if name=="GND" else .1
    if name=="GND":
        y -= .15
    pin["label_center_um"] = [x,y]
    layer, dtype = pin["pin_layer"]
    top.add(gdstk.rectangle((x-half,y-half),(x+half,y+half),layer=layer,datatype=dtype))
    layer, texttype = pin["label_layer"]
    top.add(gdstk.Label(name,(x,y),layer=layer,texttype=texttype))
clean = gdstk.Library(unit=lib.unit, precision=lib.precision)
clean.add(top)
clean.write_gds(out / "ota7.gds")
(out / "pin_bindings.json").write_text(json.dumps(pins,indent=2)+"\n")
print("INDEPENDENT_REFERENCE_WRITTEN", flush=True)
drc = check_gds(out/"ota7.gds", out/"drc_full")
sky130.lvs_netgen(out / "ota7.gds", "ota7", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=out / "ota7.spice", output_file_path=out / "lvs", copy_intermediate_files=True)
report = next((out / "lvs").rglob("*_lvs.rpt")).read_text()
lvs = netgen_lvs_report(report)
result = {"LVS_match": lvs["is_clean"], "LVS":lvs, "DRC":drc,
          "mim_cap_size_um":args.mim_cap_size,"routing_multiplier":args.routing_multiplier,
          "diffpair_fingers":args.diffpair_fingers,
          "flow_complete":lvs["is_clean"] and drc["is_clean"], "output": str(out)}
(out / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["flow_complete"] else 2)
