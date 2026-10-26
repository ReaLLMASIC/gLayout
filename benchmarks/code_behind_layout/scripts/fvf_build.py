"""Generate the isolated FVF development source and retain diagnostic ports."""
import json
from pathlib import Path
import re
import sys
import gdstk

sys.path.insert(0, "/work/vendor/glayout-fvf-development/src")
from glayout import sky130
from glayout.cells.composite.fvf_based_ota.ota import super_class_AB_OTA
import glayout.cells.composite.fvf_based_ota.ota as ota_module
import glayout.spice.netlist as netlist_module

out = Path.cwd()
for module, name in [(ota_module, "consumed_ota.py"), (netlist_module, "consumed_netlist.py")]:
    (out / name).write_text(Path(module.__file__).read_text())
c = super_class_AB_OTA(sky130).copy()
ports = {n: {"center_um": list(map(float, p.center)), "layer": list(p.layer), "width": float(p.width),
             "orientation": float(p.orientation)} for n, p in c.ports.items()
         if (n.startswith(("cmirr_", "cbias_M_3_A_", "cbias_M_4_A_", "VCC_", "VSS_"))
             and any(x in n for x in ["source", "drain", "gate", "welltie", "top_met", "bottom_met"]))}
(out / "debug_ports.json").write_text(json.dumps(ports, indent=2) + "\n")
c.write_gds(out / "fvf7.gds")
top, = gdstk.read_gds(out / "fvf7.gds").top_level()
top.flatten(); top.name = "fvf7"
library = gdstk.Library(); library.add(top); library.write_gds(out / "fvf7.gds")
netlist = c.info["netlist_obj"]
netlist.circuit_name = "fvf7"
texts = [netlist.generate_netlist() for _ in range(3)]
(out / "generator_reference.spice").write_text(texts[0])
declared = [re.findall(r"^\.subckt\s+(\S+)", t, flags=re.M|re.I) for t in texts]
stable = texts[0] == texts[1] == texts[2]
unique = all(len(d) == len({s.lower() for s in d}) for d in declared)
(out / "namespace_validation.json").write_text(json.dumps({"three_calls_identical": stable,
    "all_declarations_unique": unique, "declarations_per_call": declared}, indent=2) + "\n")
if not stable or not unique:
    raise SystemExit("Actual FVF generator reference is unstable or repeats a subcircuit name")
source = Path("/work/vendor/glayout-fvf-development")
record = {"scope": "development_FVF_generation", "actual_top": top.name,
          "source_worktree": str(source),
          "source_manifest": "The host-side launcher must record the isolated worktree revision and patch; its absolute gitdir is outside this container mount."}
(out / "fvf_source.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record))
