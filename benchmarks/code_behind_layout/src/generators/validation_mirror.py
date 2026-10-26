"""Separate validation target: two-NMOS mirror with explicit three-net routing.

Uses only common MOS/via primitives. It calls no evaluation assembly or public
compiler. Local terminal escapes follow the same PDK access constraints already
observed in development; placement and the three fixed net paths are explicit.
"""
from pathlib import Path
import json
import gdstk
from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos
from glayout.primitives.via_gen import via_stack


PORTS=["REF","OUT","GND"]


def schematic(width=3.,length=1.,fingers=2):
    lines=["* Independently specified validation NMOS current mirror",
        ".subckt validation_mirror REF OUT GND"]
    for name,drain in [("REF","REF"),("OUT","OUT")]:
        for finger in range(fingers):
            lines.append(f"X{name}{finger} {drain} REF GND GND sky130_fd_pr__nfet_01v8 w={width:g} l={length:g}")
    return "\n".join(lines+[".ends validation_mirror",""])


def build(output,width=3.,length=1.,fingers=2,channel=24.):
    sky130.activate();top=Component("validation_mirror")
    def metal(layer,x0,y0,x1,y1):
        points=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
        top.add_polygon([(round(x/.005)*.005,round(y/.005)*.005) for x,y in points],layer=sky130.get_glayer(layer))
    def via(bottom,upper,x,y):
        ref=top<<via_stack(sky130,bottom,upper,fullbottom=True,fulltop=True);ref.move((x,y))
    remove=[v for k,v in sky130.glayers.items() if k.endswith(("_label","_pin"))]+[(64,44)]
    cell=nmos(sky130,width=width,length=length,fingers=fingers,with_dummy=False,with_tie=True,with_dnwell=False).copy()
    cell=cell.remove_layers(remove,include_labels=True)
    reference=top<<cell;reference.movex(-reference.xmin)
    output_device=top<<cell;output_device.movex(reference.xmax+channel-output_device.xmin)
    high=max(reference.ymax,output_device.ymax)+6;low=min(reference.ymin,output_device.ymin)-6
    access={}
    for name,device in [("reference",reference),("output",output_device)]:
        for index,(terminal,port_name) in enumerate([
                ("D","multiplier_0_drain_W"),("G","multiplier_0_gate_W"),
                ("S","multiplier_0_source_W"),("B","tie_S_top_met_S")]):
            port=device.ports[port_name];x,y=map(float,port.center)
            layer=sky130.layer_to_glayer(port.layer);escape=device.xmin-2-2*index
            metal(layer,escape-.1,y-.1,x+.1,y+.1)
            landing=y+2 if terminal=="D" else y
            if landing!=y:metal(layer,escape-.1,y-.1,escape+.1,landing+.1)
            via(layer,"met3",escape,landing);access[name,terminal]=(escape,landing)
    def branch(key,y):
        x,start=access[key];metal("met3",x-.3,min(start,y)-.3,x+.3,max(start,y)+.3);via("met3","met4",x,y)
        return x
    # The diode and output gate share the upper reference spine. The output
    # drain has a separate higher spine; all four source/body ends join below.
    paths={"REF":([("reference","D"),("reference","G"),("output","G")],high),
        "OUT":([("output","D")],high+4),
        "GND":([("reference","S"),("reference","B"),("output","S"),("output","B")],low)}
    for net,(members,y) in paths.items():
        xs=[branch(key,y) for key in members];x0=min(xs)-2;x1=max(xs)+2
        metal("met4",x0,y-.4,x1,y+.4)
        metal("met4_pin",x0+.6,y-.15,x0+.9,y+.15)
        top.add_label(net,position=(x0+.75,y),layer=sky130.get_glayer("met4_label"))
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    path=output/"validation_mirror.gds";top.write_gds(path)
    actual,=gdstk.read_gds(path).top_level();actual.flatten();actual.name="validation_mirror"
    lib=gdstk.Library();lib.add(actual);lib.write_gds(path)
    (output/"reference.spice").write_text(schematic(width,length,fingers))
    (output/"source_role.json").write_text(json.dumps({"role":"validation_candidate_not_frozen",
        "width_per_finger_um":width,"length_um":length,"fingers":fingers,"channel_um":channel,
        "shared_dependencies":["glayout.primitives.fet.nmos","glayout.primitives.via_gen.via_stack"]},indent=2)+"\n")
    return path
