"""Validate an already generated independent OTA probe without rebuilding geometry."""
import json
import os
from pathlib import Path
import shutil
from glayout import sky130

source = Path(os.environ["PROBE_INPUT"])
out = Path.cwd()
for name in ["ota7.gds", "ota7.spice", "pin_bindings.json"]:
    shutil.copy(source / name, out / name)
sky130.drc_magic(out / "ota7.gds", "ota7", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc", output_file=out / "drc")
sky130.lvs_netgen(out / "ota7.gds", "ota7", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=out / "ota7.spice", output_file_path=out / "lvs", copy_intermediate_files=True)
report = next((out / "lvs").rglob("*_lvs.rpt")).read_text()
result = {"LVS_match": "Circuits match uniquely" in report,
          "DRC_report": next((out / "drc").rglob("*.rpt")).read_text()}
(out / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
