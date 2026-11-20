"""Generate and independently verify all eight ASAP7 transistor flavors.

GLAYOUT_BACKEND=gdstk PDK_ROOT=/tmp python examples/asap7_devices.py --out-dir devices
The SPICE files reference model names; include the desired ASAP7 HSPICE corner
file when running an electrical simulation.
"""

import argparse
import json
import math
from pathlib import Path
from glayout import asap7, nmos, pmos
from glayout.pdk.asap7_mapped.verification import drc, lvs


def standalone_pins(comp):
    comp = comp.flatten()
    for terminal, portname in {
        "D": "drain_N",
        "G": "gate_S",
        "S": "source_W",
        "B": "tie_N_top_met_S",
    }.items():
        port = comp.ports[portname]
        angle = math.radians(port.orientation)
        position = (port.x - 0.001 * math.cos(angle), port.y - 0.001 * math.sin(angle))
        metal = asap7.layer_to_glayer(port.layer)
        comp.add_label(
            terminal, position=position, layer=asap7.get_glayer(metal + "_label")
        )
    comp.add_label("B", position=(0, 0), layer=(3, 251))
    return comp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for builder, polarity in ((nmos, "nmos"), (pmos, "pmos")):
        for vt in asap7.finfet_flavors:
            name = polarity + "_" + vt
            comp = standalone_pins(builder(asap7, vt=vt, nfin=3, fingers=2))
            comp.name = name
            gds = args.out_dir / (name + ".gds")
            spice = args.out_dir / (name + ".spice")
            comp.write_gds(gds)
            spice.write_text(comp.info["netlist"].generate_netlist())
            errors = drc(gds)
            extracted = lvs(gds, spice, args.out_dir / "reports" / name)
            results[name] = {
                "gds": gds.name,
                "spice": spice.name,
                "drc": errors,
                "lvs": extracted,
            }
            print(
                name,
                "PASS" if not errors and extracted["match"] else "FAIL",
                flush=True,
            )
    (args.out_dir / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    if any(r["drc"] or not r["lvs"]["match"] for r in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
