"""Move the GND pin marker inside the physical ground bar, then verify it."""
import json
import os
from pathlib import Path
import shutil
import sys
import gdstk
from glayout import sky130

sys.path.insert(0, "/work")
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report

source = Path(os.environ["PROBE_INPUT"])
out = Path.cwd()
pins = json.loads((source/"pin_bindings.json").read_text())
library = gdstk.read_gds(source/"ota7.gds")
top, = library.top_level()
x, y = pins["GND"]["center_um"]
top.remove(*(p for p in top.polygons if (p.layer, p.datatype)==tuple(pins["GND"]["pin_layer"])
    and p.contain((x, y))))
top.remove(*(p for p in top.labels if p.text=="GND"))
layer, dtype = pins["GND"]["pin_layer"]
top.add(gdstk.rectangle((x-.15,y-.3),(x+.15,y),layer=layer,datatype=dtype))
layer, dtype = pins["GND"]["label_layer"]
top.add(gdstk.Label("GND",(x,y-.15),layer=layer,texttype=dtype))
pins["GND"]["label_center_um"] = [x,y-.15]
library.write_gds(out/"ota7.gds")
shutil.copy2(source/"ota7.spice", out/"ota7.spice")
(out/"pin_bindings.json").write_text(json.dumps(pins, indent=2)+"\n")
drc = check_gds(out/"ota7.gds", out/"drc_full")
sky130.lvs_netgen(out/"ota7.gds", "ota7", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=out/"ota7.spice", output_file_path=out/"lvs", copy_intermediate_files=True)
lvs = netgen_lvs_report(next((out/"lvs").rglob("*_lvs.rpt")).read_text())
record = {"scope":"development_pin_marker_repair", "input_directory":str(source),
    "DRC":drc, "LVS":lvs, "LVS_match":lvs["is_clean"], "flow_complete":drc["is_clean"] and lvs["is_clean"]}
(out/"validation.json").write_text(json.dumps(record, indent=2)+"\n")
print(json.dumps(record, indent=2))
raise SystemExit(0 if record["flow_complete"] else 2)
