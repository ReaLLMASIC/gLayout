"""Actual primitive dimensions and port layers of the FVF local bias mirror."""
import json
from pathlib import Path
from glayout import sky130
from glayout.cells.elementary.current_mirror.current_mirror import current_mirror

c = current_mirror(sky130, numcols=2, device="pfet", width=1.88, length=3, fingers=1, with_labels=False)
names = ["fet_A_source_W", "fet_A_source_E", "fet_B_source_W", "fet_B_source_E",
         "fet_A_drain_E", "fet_A_gate_E", "welltie_W_top_met_W"]
names += [n for n in c.ports if n.startswith("purposegndports")]
record = {name: {"center_um": list(map(float, c.ports[name].center)), "layer": list(c.ports[name].layer),
                 "width_um": float(c.ports[name].width), "orientation": float(c.ports[name].orientation)} for name in names}
(Path.cwd() / "local_mirror_ports.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
