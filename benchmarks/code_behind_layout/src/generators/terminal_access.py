"""Frozen MOS terminal access and basic Manhattan drawing for new assemblies.

No circuit graph, placement, net routing policy, or reference is encoded here.
The 0.2um escape and raised drain landing are the disclosed PDK access rules
already qualified in the development 5T and validation-mirror layouts.
"""
from pathlib import Path
import gdstk
from glayout import sky130
from glayout.primitives.via_gen import via_stack


def rectangle(top, layer, x0, y0, x1, y1):
    top.add_polygon([(round(x/.005)*.005, round(y/.005)*.005)
                     for x, y in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]], layer=sky130.get_glayer(layer))


def wire(top, layer, a, b, width):
    if a[0] != b[0] and a[1] != b[1]:
        raise ValueError("A basic wire must be Manhattan; the assembly chooses its bends")
    rectangle(top, layer, min(a[0],b[0])-width/2, min(a[1],b[1])-width/2,
              max(a[0],b[0])+width/2, max(a[1],b[1])+width/2)


def via(top, bottom, upper, point):
    item = top << via_stack(sky130, bottom, upper, fullbottom=True, fulltop=True)
    item.move(point)


def expose(top, device):
    access = {}
    for index, (terminal, name) in enumerate([
        ("D","multiplier_0_drain_W"),("G","multiplier_0_gate_W"),
        ("S","multiplier_0_source_W"),("B","tie_S_top_met_S")]):
        port = device.ports[name]
        x, y = map(float, port.center)
        layer = sky130.layer_to_glayer(port.layer)
        landing_x = float(device.xmin)-2-2*index
        wire(top, layer, (landing_x,y), (x,y), .2)
        landing_y = y+2 if terminal == "D" else y
        if landing_y != y:
            wire(top, layer, (landing_x,y), (landing_x,landing_y), .2)
        via(top, layer, "met3", (landing_x,landing_y))
        access[terminal] = (landing_x,landing_y)
    return access


def pin(top, name, point):
    x, y = point
    rectangle(top, "met4_pin", x-.15,y-.15,x+.15,y+.15)
    top.add_label(name, position=point, layer=sky130.get_glayer("met4_label"))


def finish(top, output):
    path = Path(output)/(top.name+".gds")
    top.write_gds(path)
    flat, = gdstk.read_gds(path).top_level()
    flat.flatten()
    library = gdstk.Library()
    library.add(flat)
    library.write_gds(path)
    return path
