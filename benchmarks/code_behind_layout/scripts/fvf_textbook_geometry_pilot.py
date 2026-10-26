"""Fresh public-compiler development geometry pilot; no imported results or S2 claim."""
import json
import os
from pathlib import Path
import subprocess
import sys
import gdstk

sys.dont_write_bytecode = True
source = Path("/work/vendor/textbook-sharing-readonly")
bench = source / "benchmarks/textbook_sharing"
sys.path[:0] = [str(source / "src"), str(bench), "/work"]
os.environ["GLAYOUT_BACKEND"] = "gdsfactory"
from glayout import sky130
from textbook_sharing.circuits import CIRCUITS
from textbook_sharing.layout import build
from textbook_sharing.nominal import nominal
from textbook_sharing.netlist import emit_subckt
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory

out = Path.cwd()
circuit = CIRCUITS["C08"]
case = nominal("C08", "sky130")
name = "textbook_c08"
reference = emit_subckt("sky130", circuit, case.sizing, name, per_finger=True, lvs=True)
(out / "target.spice").write_text(reference)
(out / "circuit_input.json").write_text(json.dumps(circuit.to_json(), indent=2) + "\n")
(out / "sizing_input.json").write_text(json.dumps(case.sizing, indent=2) + "\n")
(out / "source_LICENSE.txt").write_text((source / "LICENSE").read_text())
result = build(sky130, circuit, case.sizing, mode="independent", name=name)
result["component"].write_gds(out / (name + ".gds"))
top, = gdstk.read_gds(out / (name + ".gds")).top_level()
top.flatten(); top.name = name
library = gdstk.Library(); library.add(top); library.write_gds(out / (name + ".gds"))
record = {"scope": "fresh_development_public_compiler_geometry_only_no_S2_or_formal_claim",
          "source_repository": "https://github.com/DonaldLucy/gLayout", "source_revision": "1f90e33913208e572744b7c5a144a7da8c073235",
          "circuit_id": "C08", "mode": "independent", "imported_physical_results": False,
          "DRC": check_gds(out / (name + ".gds"), out / "drc_full")}
(out / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
tcl = "\n".join(["gds read {" + str(out / (name + ".gds")) + "}", "load " + name,
    "select top cell", "extract all", "ext2spice lvs", "ext2spice -o layout_lvs.spice", "quit -noprompt", ""])
(out / "lvs_extract.tcl").write_text(tcl)
with (out / "lvs_magic.log").open("w") as log:
    extraction = subprocess.run(["magic", "-rcfile", "/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc", "-noconsole", "-dnull"],
        input=tcl, text=True, stdout=log, stderr=subprocess.STDOUT, timeout=120)
with (out / "netgen.log").open("w") as log:
    lvs = subprocess.run(["netgen", "-batch", "lvs", str(out / "layout_lvs.spice") + " " + name,
        str(out / "target.spice") + " " + name, "/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
        str(out / "netgen_lvs.rpt")], stdout=log, stderr=subprocess.STDOUT, timeout=120)
record["LVS"] = netgen_lvs_report((out / "netgen_lvs.rpt").read_text())
record["LVS"]["returncode"] = lvs.returncode
(out / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:
    raise SystemExit("Fresh public compiler GDS failed trusted physical geometry checks")
with (out / "pex.log").open("w") as log:
    pex = subprocess.run(["bash", "/work/vendor/glayout/src/glayout/verification/run_pex.sh",
        str(out / (name + ".gds")), name], stdout=log, stderr=subprocess.STDOUT, timeout=180)
record["pex_returncode"] = pex.returncode
record["RC"] = rc_netlist_inventory((out / (name + "_pex.spice")).read_text(), name + "_rc", circuit.ports)
record["physical_geometry_stage_complete"] = (pex.returncode == 0 and record["RC"]["has_real_RC"])
(out / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
raise SystemExit(0 if record["physical_geometry_stage_complete"] else 2)
