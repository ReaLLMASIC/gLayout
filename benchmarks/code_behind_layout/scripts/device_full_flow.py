"""Single MOS development pilot: labeled GDS, DRC/LVS, full RC, three-corner OP."""
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import gdstk
from gdsfactory.components.rectangle import rectangle
from glayout import sky130
from glayout.primitives.fet import nmos
from glayout.util.comp_utils import align_comp_to_port

sys.path.insert(0, "/work")
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory

out = Path.cwd()
c = nmos(sky130, width=3, length=.5, fingers=2, with_dummy=False, with_tie=True, with_dnwell=False).copy()
c = c.remove_layers([v for k,v in sky130.glayers.items() if k.endswith(("_label", "_pin"))])
c.name = "device4"
c.info["netlist"].circuit_name = "device4"
reference = c.info["netlist"].generate_netlist()
(out / "device4.spice").write_text(reference)
ports = {"D":"multiplier_0_drain_N", "G":"multiplier_0_gate_W",
         "S":"multiplier_0_source_S", "B":"tie_W_top_met_W"}
pin_records = {}
for label, name in ports.items():
    port = c.ports[name]
    glayer = sky130.layer_to_glayer(port.layer)
    pin = rectangle(size=(.2,.2),layer=sky130.get_glayer(glayer+"_pin"),centered=True).copy()
    pin.add_label(label,layer=sky130.get_glayer(glayer+"_label"))
    c.add(align_comp_to_port(pin,port,("c","c")))
    pin_records[label] = {"port":name,"center_um":list(map(float,port.center)),"layer":list(port.layer)}
(out / "pin_bindings.json").write_text(json.dumps(pin_records,indent=2)+"\n")
# Export external pin names at the top level. Magic otherwise qualifies labels
# retained inside pin-marker child cells, leaving an empty external interface.
c = c.remove_layers([(64,44)], include_labels=True)
c.name = "device4"
c.write_gds(out / "device4.gds")
# gdsfactory may suffix a cached cell name on export. Normalize the actual GDS
# top rather than assuming the Python component name survived serialization.
top, = gdstk.read_gds(out/"device4.gds").top_level()
top.flatten(); top.name="device4"
library=gdstk.Library();library.add(top);library.write_gds(out/"device4.gds")
drc = check_gds(out/"device4.gds", out/"drc_full")
sky130.lvs_netgen(out/"device4.gds","device4",pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=out/"device4.spice",output_file_path=out/"lvs",copy_intermediate_files=True)
record = {"scope":"development_device_flow_no_frozen_S2_specs",
    "with_dnwell":False, "DRC":drc,
    "LVS":netgen_lvs_report(next((out/"lvs").rglob("*_lvs.rpt")).read_text()),"corners":{}}
with (out/"pex.log").open("w") as log:
    pex = subprocess.run(["bash","/work/vendor/glayout/src/glayout/verification/run_pex.sh",str(out/"device4.gds"),"device4"],
        stdout=log,stderr=subprocess.STDOUT,timeout=120)
net = out/"device4_pex.spice"
text = net.read_text()
record["pex_returncode"] = pex.returncode
record["element_counts"] = {k:len(re.findall(r"^"+k+r"\S*\s",text,re.I|re.M)) for k in ["R","C","X","M"]}
decl = next(s.split() for s in text.splitlines() if s.lower().startswith(".subckt "))
record["extracted_port_order"] = decl[2:]
record["RC"] = rc_netlist_inventory(text, "device4_rc", ["D","G","S","B"])
binding = {"D":"drain","G":"gate","S":"0","B":"0"}
if set(decl[2:]) != set(binding) or len(decl[2:]) != 4:
    raise SystemExit("Full extracted D/G/S/B terminal interface is required")
nodes = [binding[p.upper()] for p in decl[2:]]
for corner in ["tt","ss","ff"]:
    work = out/corner;work.mkdir()
    (work/".spiceinit").write_text("set ngbehavior=hsa\n")
    deck = "\n".join(["Extracted MOS OP development pilot",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
        ".option scale=1e-6", ".temp 27", ".include "+str(net),
        "VGS gate 0 .9", "VDS drain 0 .9", "XDUT "+" ".join(nodes)+" "+decl[1],
        ".control","op","set wr_vecnames","set wr_singlescale",
        "wrdata operating_point.dat v(gate) v(drain) i(vds)","quit",".endc",".end",""])
    (work/"testbench.spice").write_text(deck)
    with (work/"console.log").open("w") as log:
        sim = subprocess.run(["ngspice","-b","-o","ngspice.log","testbench.spice"],cwd=work,
            stdout=log,stderr=subprocess.STDOUT,timeout=60)
    data = work/"operating_point.dat"
    result = {"returncode":sim.returncode,"numeric_output_present":False}
    if data.exists():
        values = list(map(float,data.read_text().splitlines()[-1].split()))
        result.update(numeric_output_present=len(values)==4 and all(map(math.isfinite,values)),
            gate_V=values[1],drain_V=values[2],drain_source_current_A=values[3])
    record["corners"][corner] = result
record["flow_complete"] = (record["DRC"]["is_clean"] and record["LVS"]["is_clean"]
    and pex.returncode==0 and record["RC"]["has_real_RC"]
    and all(r["numeric_output_present"] and r["returncode"]==0 and r["drain_source_current_A"]<0
            for r in record["corners"].values()))
(out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
print(json.dumps(record,indent=2))
raise SystemExit(0 if record["flow_complete"] else 2)
