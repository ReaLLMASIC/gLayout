"""Diagnose extracted node identities at actual FVF component port locations."""
import json
import os
from pathlib import Path
import subprocess
import gdstk

source = Path(os.environ["PROBE_INPUT"])
out = Path.cwd()
top, = gdstk.read_gds(source / "fvf7.gds").top_level()
labels = [{"text": l.text, "origin": list(l.origin), "layer": l.layer, "texttype": l.texttype}
          for l in top.get_labels()]
(out / "input_labels.json").write_text(json.dumps(labels, indent=2) + "\n")
ports = json.loads((source / "debug_ports.json").read_text())
for label, name in [("REF_LEFT", "cmirr_1_fet_A_drain_E"), ("GATE_LEFT", "cmirr_1_fet_A_gate_E"),
                    ("SUPPLY_LEFT", "cmirr_1_welltie_N_top_met_N"),
                    ("GLOBAL_LEFT", "cbias_M_3_A_multiplier_0_drain_W")]:
    port = ports[name]
    x, y = port["center_um"]
    top.add(gdstk.rectangle((x-.05, y-.05), (x+.05, y+.05), layer=port["layer"][0], datatype=16))
    top.add(gdstk.Label(label, port["center_um"], layer=port["layer"][0], texttype=5))
top.name = "fvf_node_debug"
library = gdstk.Library(); library.add(top); library.write_gds(out / "fvf_node_debug.gds")
tcl = "\n".join(["gds read {" + str(out / "fvf_node_debug.gds") + "}", "load fvf_node_debug",
    "select top cell", "extract all", "ext2spice lvs", "ext2spice -o node_debug.spice",
    "select clear", "select short REF_LEFT AVDD", "select save fvf_bias_short", "load fvf_bias_short",
    "gds write fvf_bias_short.gds", "quit -noprompt", ""])
(out / "node_probe.tcl").write_text(tcl)
with (out / "magic.log").open("w") as log:
    result = subprocess.run(["magic", "-rcfile", "/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc", "-noconsole", "-dnull"],
        input=tcl, text=True, stdout=log, stderr=subprocess.STDOUT, timeout=90)
print((out / "node_debug.spice").read_text())
