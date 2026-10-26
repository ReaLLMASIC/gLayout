"""Independent row placement and explicit channel routing for a 5T OTA core.

Only MOS, via-stack and rectangle primitives are borrowed from gLayout. No
existing OTA, differential-pair, current-mirror or benchmark assembly is called.
The separate five_t_reference module owns the intended electrical schematic.
"""
import json
from pathlib import Path

import gdstk
from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos, pmos
from glayout.primitives.via_gen import via_stack

from src.generators.five_t_reference import DEFAULT, PORTS


def snap(value):
    return round(round(float(value) / .005) * .005, 3)


def rectangle(component, layer, x0, y0, x1, y1):
    component.add_polygon([(snap(x0), snap(y0)), (snap(x1), snap(y0)),
                           (snap(x1), snap(y1)), (snap(x0), snap(y1))], layer=layer)


def build(output, config=None):
    sizes = {**DEFAULT, **(config or {})}
    sky130.activate()
    top = Component("five_t_ota")
    escape_width, drop_width, trunk_width = .2, .6, .8
    # The row is a deliberate independent placement strategy. Wide routing
    # channels keep each device's terminal escape separate from the next device.
    devices = [
        ("NREF", "n", "tail", {"D": "IBIAS", "G": "IBIAS", "S": "GND", "B": "GND"}),
        ("NTAIL", "n", "tail", {"D": "tail", "G": "IBIAS", "S": "GND", "B": "GND"}),
        ("NIP", "n", "input", {"D": "mirror", "G": "VP", "S": "tail", "B": "GND"}),
        ("NIM", "n", "input", {"D": "VOUT", "G": "VN", "S": "tail", "B": "GND"}),
        ("PLD", "p", "load", {"D": "mirror", "G": "mirror", "S": "VDD", "B": "VDD"}),
        ("POUT", "p", "load", {"D": "VOUT", "G": "mirror", "S": "VDD", "B": "VDD"})]
    terminals = {"D": "multiplier_0_drain_W", "G": "multiplier_0_gate_W",
                 "S": "multiplier_0_source_W", "B": "tie_S_top_met_S"}
    records, cursor, top_edge = [], 0.0, 0.0
    removable = [value for key, value in sky130.glayers.items() if key.endswith(("_label", "_pin"))] + [(64, 44)]
    for name, kind, category, connections in devices:
        kwargs = dict(width=sizes[category + "_width"], length=sizes[category + "_length"],
                      fingers=sizes[category + "_fingers"], with_dummy=False, with_tie=True)
        cell = (nmos(sky130, with_dnwell=False, **kwargs) if kind == "n" else pmos(sky130, dnwell=False, **kwargs)).copy()
        cell = cell.remove_layers(removable, include_labels=True)
        reference = top << cell
        reference.movex(snap(cursor - reference.xmin))
        top_edge = max(top_edge, reference.ymax)
        for index, (terminal, port_name) in enumerate(terminals.items()):
            port = reference.ports[port_name]
            x, y = map(snap, port.center)
            track_x = snap(reference.xmin - 2 - 2 * index)
            layer = sky130.layer_to_glayer(port.layer)
            # Source/drain access bars can be only 0.43 um apart. A wide local
            # strap would short them before reaching the separated via tracks.
            rectangle(top, sky130.get_glayer(layer), track_x - escape_width / 2, y - escape_width / 2,
                      x + escape_width / 2, y + escape_width / 2)
            # A complete M1/M2 via landing is wider than the original access
            # bars. Lift the drain landing outside the neighbouring source
            # escape before changing layers; shortening the wire alone is not
            # sufficient to clear that landing.
            via_y = snap(y + 2) if terminal == "D" else y
            if via_y != y:
                rectangle(top, sky130.get_glayer(layer), track_x - escape_width / 2, y - escape_width / 2,
                          track_x + escape_width / 2, via_y + escape_width / 2)
            via = top << via_stack(sky130, layer, "met3", fullbottom=True, fulltop=True)
            via.move((track_x, via_y))
            records.append({"device": name, "terminal": terminal, "net": connections[terminal],
                            "port_name": port_name, "port_xy_um": [x, y], "port_layer": layer,
                            "track_x_um": track_x, "track_start_y_um": via_y})
        cursor = snap(reference.xmax + 22)
    buses = {}
    for index, net in enumerate(PORTS + ["tail", "mirror"]):
        members = [value for value in records if value["net"] == net]
        y = snap(top_edge + 8 + 3 * index)
        x0 = snap(min(value["track_x_um"] for value in members) - 2)
        x1 = snap(max(value["track_x_um"] for value in members) + 2)
        rectangle(top, sky130.get_glayer("met4"), x0, y - trunk_width / 2, x1, y + trunk_width / 2)
        for member in members:
            x, start_y = member["track_x_um"], member["track_start_y_um"]
            rectangle(top, sky130.get_glayer("met3"), x - drop_width / 2, start_y - drop_width / 2,
                      x + drop_width / 2, y + drop_width / 2)
            via = top << via_stack(sky130, "met3", "met4", fullbottom=True, fulltop=True)
            via.move((x, y))
        buses[net] = {"y_um": y, "x_range_um": [x0, x1]}
        if net in PORTS:
            pin_x = snap(x0 + 1)
            rectangle(top, sky130.get_glayer("met4_pin"), pin_x - .2, y - .2, pin_x + .2, y + .2)
            top.add_label(net, position=(pin_x, y), layer=sky130.get_glayer("met4_label"))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    gds = output / "five_t_ota.gds"
    top.write_gds(gds)
    actual, = gdstk.read_gds(gds).top_level()
    actual.flatten()
    actual.name = "five_t_ota"
    library = gdstk.Library()
    library.add(actual)
    library.write_gds(gds)
    metadata = {"generator": "independent_row_5T_OTA_assembly", "sizing": sizes,
                "source_dependencies": ["glayout.primitives.fet.nmos", "glayout.primitives.fet.pmos",
                    "glayout.primitives.via_gen.via_stack", "gdsfactory.component.Component", "gdstk"],
                "terminals": records, "buses": buses, "bbox_um": [list(point) for point in actual.bounding_box()],
                "formal_lineage_assignment": None}
    (output / "layout_intent.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return gds
