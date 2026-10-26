"""Independent three-column stacked cascode assembly and dedicated spine paths.

Only MOS/via/PDK primitives are shared. No circuit assembly or universal netlist
compiler is imported. Local narrow escapes obey the same common PDK terminal
access constraints as other development generators; the circuit placement and
its internal, bias, output and ground paths are defined here.
"""
import json
from pathlib import Path
import gdstk
from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos
from glayout.primitives.via_gen import via_stack
from src.generators.cascode_mirror_reference import DEFAULT


def build(output, config=None):
    z = {**DEFAULT, **(config or {})}
    sky130.activate()
    top = Component("cascode_mirror")
    snap = lambda v: round(round(float(v)/.005)*.005, 3)
    def segment(layer, a, b, width=.6):
        x0,y0=map(snap,a);x1,y1=map(snap,b)
        if x0!=x1 and y0!=y1: raise ValueError("Cascode path must be orthogonal")
        top.add_polygon([(min(x0,x1)-width/2,min(y0,y1)-width/2),
            (max(x0,x1)+width/2,min(y0,y1)-width/2),
            (max(x0,x1)+width/2,max(y0,y1)+width/2),
            (min(x0,x1)-width/2,max(y0,y1)+width/2)],layer=sky130.get_glayer(layer))
    def via(a,b,p):
        v=top<<via_stack(sky130,a,b,fullbottom=True,fulltop=True);v.move(tuple(map(snap,p)))
    remove=[v for k,v in sky130.glayers.items() if k.endswith(("_label","_pin"))]+[(64,44)]
    device=nmos(sky130,width=z["width"],length=z["length"],fingers=z["fingers"],
        with_dummy=False,with_tie=True,with_dnwell=False).copy().remove_layers(remove,include_labels=True)
    cells={};access={}
    for name,center in [("BLOW",(0,-35)),("BHIGH",(0,15)),("RLOW",(60,-35)),
                        ("RHIGH",(60,15)),("OLOW",(120,-35)),("OHIGH",(120,15))]:
        ref=top<<device;ref.move(origin=ref.center,destination=center);cells[name]=ref
        access[name]={}
        for terminal,key,direction in [("D","multiplier_0_drain_W",(-3,0)),
                ("G","multiplier_0_gate_W",(-3,0)),("S","multiplier_0_source_E",(3,0)),
                ("B","tie_S_top_met_S",(0,-3))]:
            port=ref.ports[key];point=tuple(map(snap,port.center))
            layer=sky130.layer_to_glayer(port.layer)
            if terminal=="D":
                # The north M1 path crosses the primitive's upper body strap.
                # Leave west first, then lift outside the contact ring.
                elbow=(snap(ref.xmin-3),point[1]);landing=(elbow[0],snap(point[1]+2))
                segment(layer,point,elbow,.2);segment(layer,elbow,landing,.2)
            else:
                landing=(snap(point[0]+direction[0]),snap(point[1]+direction[1]))
                segment(layer,point,landing,.2)
            via(layer,"met3",landing)
            access[name][terminal]=landing
    def p(name,terminal):return access[name][terminal]
    # Private stack nodes use vertical M4 spines and M3 lateral branches.
    def stack(members,x):
        ys=[]
        for name,terminal in members:
            endpoint=p(name,terminal);ys.append(endpoint[1]);segment("met3",endpoint,(x,endpoint[1]))
            via("met3","met4",(x,endpoint[1]))
        segment("met4",(x,min(ys)),(x,max(ys)),.8)
    stack([("BLOW","D"),("BLOW","G"),("BHIGH","S")],-18)
    stack([("RLOW","D"),("RLOW","G"),("RHIGH","S"),("OLOW","G")],42)
    stack([("OLOW","D"),("OHIGH","S")],144)
    pins={}
    # The independently fed bias stack controls both upper cascodes.
    for name,terminal in [("BHIGH","D"),("BHIGH","G"),("RHIGH","G"),("OHIGH","G")]:
        endpoint=p(name,terminal);via("met3","met4",endpoint)
        segment("met4",endpoint,(endpoint[0],70))
        via("met4","met5",(endpoint[0],70))
    segment("met5",(-30,70),(130,70),1);pins["IBIAS"]=("met5",(-27,70))
    # Ground travels below every device; upper body connections descend on M4.
    for name in cells:
        members=["B"]+(["S"]if name.endswith("LOW")else[])
        for terminal in members:
            endpoint=p(name,terminal);via("met3","met4",endpoint)
            segment("met4",endpoint,(endpoint[0],-65));via("met4","met5",(endpoint[0],-65))
    segment("met5",(-30,-65),(145,-65),1);pins["GND"]=("met5",(-27,-65))
    for name,net,y,left,right in [("RHIGH","IREF",82,35,70),("OHIGH","IOUT",94,108,160)]:
        endpoint=p(name,"D");via("met3","met4",endpoint)
        segment("met4",endpoint,(endpoint[0],y));via("met4","met5",(endpoint[0],y))
        segment("met5",(left,y),(right,y),1);pins[net]=("met5",(right-2,y))
    for net,(layer,point)in pins.items():
        x,y=point;top.add_polygon([(x-.2,y-.2),(x+.2,y-.2),(x+.2,y+.2),(x-.2,y+.2)],layer=sky130.get_glayer(layer+"_pin"))
        top.add_label(net,position=point,layer=sky130.get_glayer(layer+"_label"))
    out=Path(output);out.mkdir(parents=True,exist_ok=True);path=out/"cascode_mirror.gds";top.write_gds(path)
    actual,=gdstk.read_gds(path).top_level();actual.flatten();actual.name="cascode_mirror"
    lib=gdstk.Library();lib.add(actual);lib.write_gds(path)
    (out/"layout_intent.json").write_text(json.dumps({"sizing":z,"terminal_access":access,
        "placement":"three columns; independent bias/reference/output stacks",
        "routing":"private M4 stack spines, dedicated M5 external rails and M3 branches",
        "shared_dependencies":["MOS","via_stack","SKY130 PDK"],"imported_circuit_assemblies":[],
        "bbox_um":[list(v)for v in actual.bounding_box()]},indent=2)+"\n")
    return path
