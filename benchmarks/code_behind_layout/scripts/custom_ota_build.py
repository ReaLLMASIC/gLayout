"""Build and independently check a new development-only 5T OTA assembly."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, "/work")
from src.generators.five_t import build
from src.generators.five_t_reference import schematic, PORTS
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
from glayout import sky130

out = Path.cwd()
gds = build(out)
reference = out / "five_t_ota.spice"
reference.write_text(schematic())
for name in ["five_t.py", "five_t_reference.py"]:
    (out / name).write_text((Path("/work/src/generators") / name).read_text())
record = {"scope": "development_independent_5T_assembly_not_formal_or_training", "topology": "five_t_ota"}
record["DRC"] = check_gds(gds, out / "drc_full")
sky130.lvs_netgen(gds, "five_t_ota", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=reference, output_file_path=out / "lvs", copy_intermediate_files=True)
report, = list((out / "lvs").rglob("*_lvs.rpt"))
record["LVS"] = netgen_lvs_report(report.read_text())
(out / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:
    print(json.dumps(record, indent=2), flush=True)
    raise SystemExit(2)
with (out / "pex.log").open("w") as log:
    process = subprocess.run(["bash", "/work/vendor/glayout/src/glayout/verification/run_pex.sh", str(gds), "five_t_ota"],
                             stdout=log, stderr=subprocess.STDOUT, timeout=180)
record["pex_returncode"] = process.returncode
netlist = out / "five_t_ota_pex.spice"
record["RC"] = rc_netlist_inventory(netlist.read_text(), "five_t_ota_rc", PORTS) if netlist.exists() else None
record["physical_connectivity_and_positive_RC"] = bool(process.returncode == 0 and record["RC"] and record["RC"]["has_real_RC"])
(out / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2), flush=True)
raise SystemExit(0 if record["physical_connectivity_and_positive_RC"] else 2)
