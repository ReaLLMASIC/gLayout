"""Read the single-device physical ports and schematic in the recovered runtime."""
import json
from glayout import sky130
from glayout.primitives.fet import nmos
c = nmos(sky130, width=3, length=.5, fingers=2, with_dummy=False, with_tie=True)
print(json.dumps({k: {"center": list(map(float, p.center)), "layer": list(p.layer)}
                  for k, p in c.ports.items()}, indent=2))
print(c.info["netlist"].generate_netlist())
