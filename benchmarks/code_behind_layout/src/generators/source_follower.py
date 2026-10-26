"""Independent L-shaped common-drain buffer with a separate sink/reference pair.

The output has a right-side vertical collector, bias uses a short lower crossbar
and power/input leave above the input device. No existing FVF, mirror, OTA or
netlist-driven circuit assembly is called.
"""
import json
from pathlib import Path
import gdstk
from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos
from glayout.primitives.via_gen import via_stack
from src.generators.source_follower_reference import DEFAULT


def build(output, config=None):
    z={**DEFAULT,**(config or {})};sky130.activate();top=Component("source_follower")
    snap=lambda v:round(round(float(v)/.005)*.005,3)
    def line(layer,a,b,width=.6):
        x0,y0=map(snap,a);x1,y1=map(snap,b)
        if x0!=x1 and y0!=y1:raise ValueError("Buffer path must be orthogonal")
        top.add_polygon([(min(x0,x1)-width/2,min(y0,y1)-width/2),(max(x0,x1)+width/2,min(y0,y1)-width/2),
            (max(x0,x1)+width/2,max(y0,y1)+width/2),(min(x0,x1)-width/2,max(y0,y1)+width/2)],layer=sky130.get_glayer(layer))
    def lift(lower,upper,point):
        v=top<<via_stack(sky130,lower,upper,fullbottom=True,fulltop=True);v.move(tuple(map(snap,point)))
    remove=[v for k,v in sky130.glayers.items()if k.endswith(("_label","_pin"))]+[(64,44)]
    access={}
    for name,category,center in [("IN","input",(40,35)),("SINK","bias",(40,-15)),("BIAS","bias",(-15,-15))]:
        mos=nmos(sky130,width=z[category+"_width"],length=z[category+"_length"],fingers=z[category+"_fingers"],
            with_dummy=False,with_tie=True,with_dnwell=False).copy().remove_layers(remove,include_labels=True)
        ref=top<<mos;ref.move(origin=ref.center,destination=center);access[name]={}
        for terminal,key,offset in [("D","multiplier_0_drain_W",(-3,0)),("G","multiplier_0_gate_W",(-3,0)),
                ("S","multiplier_0_source_E",(3,0)),("B","tie_S_top_met_S",(0,-3))]:
            port=ref.ports[key];a=tuple(map(snap,port.center));layer=sky130.layer_to_glayer(port.layer)
            if terminal=="D":
                elbow=(snap(ref.xmin-3),a[1]);b=(elbow[0],snap(a[1]+2))
                line(layer,a,elbow,.2);line(layer,elbow,b,.2)
            else:
                b=(snap(a[0]+offset[0]),snap(a[1]+offset[1]));line(layer,a,b,.2)
            lift(layer,"met3",b);access[name][terminal]=b
    def p(n,t):return access[n][t]
    # A dedicated right-side vertical output collector joins source to sink.
    ends=[p("IN","S"),p("SINK","D")]
    line("met3",ends[0],(70,ends[0][1]));lift("met3","met4",(70,ends[0][1]))
    # The sink drain crosses the separate gate-bias drop above it on M5.
    lift("met3","met5",ends[1]);line("met5",ends[1],(70,ends[1][1]),1)
    lift("met4","met5",(70,ends[1][1]))
    line("met4",(70,min(q[1]for q in ends)),(70,max(q[1]for q in ends)),.8)
    pins={"VOUT":("met4",(70,10))}
    # The diode reference and sink gate share one small lower crossbar.
    endpoints=[p("BIAS","D"),p("BIAS","G"),p("SINK","G")]
    for endpoint in endpoints:
        line("met3",endpoint,(endpoint[0],5));lift("met3","met4",(endpoint[0],5))
    line("met4",(-35,5),(max(v[0]for v in endpoints)+1,5),.8);pins["IBIAS"]=("met4",(-33,5))
    # Ground is an M5 floor, with body and lower-device sources landing on M4.
    for name,terms in [("IN",["B"]),("SINK",["B","S"]),("BIAS",["B","S"])]:
        for terminal in terms:
            endpoint=p(name,terminal);lift("met3","met4",endpoint)
            line("met4",endpoint,(endpoint[0],-45));lift("met4","met5",(endpoint[0],-45))
    line("met5",(-35,-45),(70,-45),1);pins["GND"]=("met5",(-33,-45))
    drain=p("IN","D");lift("met3","met4",drain);line("met4",drain,(drain[0],60))
    lift("met4","met5",(drain[0],60));line("met5",(drain[0],60),(70,60),1);pins["VDD"]=("met5",(68,60))
    gate=p("IN","G");line("met3",gate,(-35,gate[1]));lift("met3","met4",(-35,gate[1]))
    line("met4",(-35,gate[1]),(-35,50));pins["VIN"]=("met4",(-35,48))
    for net,(layer,point)in pins.items():
        x,y=point;top.add_polygon([(x-.2,y-.2),(x+.2,y-.2),(x+.2,y+.2),(x-.2,y+.2)],layer=sky130.get_glayer(layer+"_pin"))
        top.add_label(net,position=point,layer=sky130.get_glayer(layer+"_label"))
    out=Path(output);out.mkdir(parents=True,exist_ok=True);path=out/"source_follower.gds";top.write_gds(path)
    actual,=gdstk.read_gds(path).top_level();actual.flatten();actual.name="source_follower"
    lib=gdstk.Library();lib.add(actual);lib.write_gds(path)
    (out/"layout_intent.json").write_text(json.dumps({"sizing":z,"terminal_access":access,
        "placement":"L-shaped input/sink/reference devices","routing":"right output collector, lower bias crossbar, ground floor, independent upper input/power feeds",
        "shared_dependencies":["MOS","via_stack","SKY130 PDK"],"imported_circuit_assemblies":[],
        "bbox_um":[list(v)for v in actual.bounding_box()]},indent=2)+"\n")
    return path
