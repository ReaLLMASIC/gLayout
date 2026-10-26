"""Independent block placement and local interconnect for a two-stage OTA.

This assembly does not invoke the row-OTA implementation or a netlist compiler.
The first-stage mirror and gain node use separate local vertical spines; the
second-stage output reaches the MIM bottom plate and gain node its top. Inputs,
bias references and power rails have explicit topology-specific paths.
"""
import json
from pathlib import Path
import gdstk
from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos, pmos
from glayout.primitives.mimcap import mimcap
from glayout.primitives.via_gen import via_stack
from src.generators.compact_miller_reference import DEFAULT, PORTS


def build(output, config=None):
    sizes = {**DEFAULT, **(config or {})}
    sky130.activate()
    top = Component("compact_miller_ota")
    routes, placement = [], {}
    snap = lambda value: round(round(float(value) / .005) * .005, 3)
    remove = [value for key, value in sky130.glayers.items() if key.endswith(("_label", "_pin"))] + [(64, 44)]

    def segment(layer, first, last, width=.6, net=None):
        x0, y0 = map(snap, first); x1, y1 = map(snap, last)
        if x0 != x1 and y0 != y1:
            raise ValueError("Explicit Miller route must be Manhattan")
        top.add_polygon([(min(x0,x1)-width/2,min(y0,y1)-width/2),
                         (max(x0,x1)+width/2,min(y0,y1)-width/2),
                         (max(x0,x1)+width/2,max(y0,y1)+width/2),
                         (min(x0,x1)-width/2,max(y0,y1)+width/2)], layer=sky130.get_glayer(layer))
        if net:
            routes.append({"net":net,"layer":layer,"first_um":[x0,y0],"last_um":[x1,y1],"width_um":width})

    def via(lower, upper, point):
        instance = top << via_stack(sky130, lower, upper, fullbottom=True, fulltop=True)
        instance.move(tuple(map(snap, point)))

    def transistor(name, kind, category, center):
        kwargs = {"width":sizes[category+"_width"], "length":sizes[category+"_length"],
                  "fingers":sizes[category+"_fingers"],"with_dummy":False,"with_tie":True}
        cell = (nmos(sky130,with_dnwell=False,**kwargs) if kind=="n" else pmos(sky130,dnwell=False,**kwargs)).copy()
        reference = top << cell.remove_layers(remove, include_labels=True)
        reference.move(origin=reference.center,destination=center)
        placement[name] = {"kind":kind,"category":category,"center_um":list(center),"bbox_um":[list(p) for p in reference.bbox]}
        return reference

    # Independent stage placement: diode references left, differential first
    # stage in the middle, vertically stacked common-source output stage right.
    cells = {
        "NREF":transistor("NREF","n","tail",(0,-15)),
        "NTAIL":transistor("NTAIL","n","tail",(20,-15)),
        "NLEFT":transistor("NLEFT","n","input",(40,0)),
        "NRIGHT":transistor("NRIGHT","n","input",(64,0)),
        "NSECOND":transistor("NSECOND","n","second_n",(95,0)),
        "PREF":transistor("PREF","p","p_ref",(0,20)),
        "PLEFT":transistor("PLEFT","p","load",(38,20)),
        "PRIGHT":transistor("PRIGHT","p","load",(62,20)),
        "PSECOND":transistor("PSECOND","p","second_p",(100,20))}
    access = {}
    ports = {"D":"multiplier_0_drain_W","G":"multiplier_0_gate_W",
             "S":"multiplier_0_source_E","B":"tie_S_top_met_S"}
    for name, reference in cells.items():
        access[name] = {}
        for terminal, port_name in ports.items():
            port = reference.ports[port_name]
            x,y = map(snap,port.center)
            # Sources leave east; drains/gates/body ties leave west. This gives
            # the complete via landing room without crossing the source bar or
            # taking an LI path through the outer substrate contact ring.
            endpoint_x = snap(reference.xmax+3) if terminal=="S" else snap(reference.xmin-{"D":2,"G":4,"B":6}[terminal])
            # These two actual body risers otherwise leave only 0.11/0.06 um
            # to the neighbouring source/gain-node via landings (met2.2).
            if terminal == "B" and name in {"NTAIL", "NRIGHT"}:
                endpoint_x = snap(endpoint_x-2)
            segment(sky130.layer_to_glayer(port.layer),(x,y),(endpoint_x,y),width=.2)
            via(sky130.layer_to_glayer(port.layer),"met3",(endpoint_x,y))
            access[name][terminal]=(endpoint_x,y)

    def point(name, terminal):
        return access[name][terminal]

    def rail(net, endpoints, y, left=None, right=None):
        xmin=min(p[0] for p in endpoints)-2 if left is None else left
        xmax=max(p[0] for p in endpoints)+2 if right is None else right
        segment("met4",(xmin,y),(xmax,y),width=.8,net=net)
        for endpoint in endpoints:
            segment("met3",endpoint,(endpoint[0],y),net=net)
            via("met3","met4",(endpoint[0],y))
        return xmin,xmax,y

    def spine(net, endpoints, x, lower=None, upper=None):
        low=min(p[1] for p in endpoints) if lower is None else lower
        high=max(p[1] for p in endpoints) if upper is None else upper
        segment("met3",(x,low),(x,high),net=net)
        for endpoint in endpoints:
            via("met3","met4",endpoint)
            segment("met4",endpoint,(x,endpoint[1]),width=.8,net=net)
            via("met3","met4",(x,endpoint[1]))

    pins = {}
    # Global supply rails are independent of the gain/mirror interconnects.
    pins["VDD"] = rail("VDD",[point(name,terminal) for name in ["PREF","PLEFT","PRIGHT","PSECOND"] for terminal in ["S","B"]],38,left=-16)
    ground_points=[point(name,"B") for name in ["NREF","NTAIL","NLEFT","NRIGHT","NSECOND"]]
    ground_points += [point(name,"S") for name in ["NREF","NTAIL","NSECOND"]]
    pins["GND"] = rail("GND",ground_points,-34,left=-16)

    # The shared source of the input pair joins the tail drain below the pair.
    rail("tail",[point("NLEFT","S"),point("NRIGHT","S"),point("NTAIL","D")],-8)

    # First-stage mirror: local vertical spine plus horizontal diode/gate links.
    mirror_x = point("PLEFT","D")[0]
    spine("mirror",[point("NLEFT","D"),point("PLEFT","D"),point("PLEFT","G"),point("PRIGHT","G")],mirror_x)

    # High-impedance gain node has its own spine, directly drives the output
    # NMOS gate, and continues locally to the MIM top plate below.
    stage1_x = point("PRIGHT","D")[0]
    stage1_endpoints=[point("NRIGHT","D"),point("PRIGHT","D"),point("NSECOND","G")]
    spine("stage1",stage1_endpoints,stage1_x,lower=min(p[1] for p in stage1_endpoints),upper=max(p[1] for p in stage1_endpoints))

    # Explicit independent diode-reference networks and their bias feeds.
    pins["IBIASN"] = rail("IBIASN",[point("NREF","D"),point("NREF","G"),point("NTAIL","G")],-26,left=-16)
    pins["IBIASP"] = rail("IBIASP",[point("PREF","D"),point("PREF","G"),point("PSECOND","G")],30,left=-16)
    pins["VP"] = rail("VP",[point("NRIGHT","G")],-18,left=-16)
    pins["VN"] = rail("VN",[point("NLEFT","G")],-15,left=-16)

    cap = top << mimcap(sky130,size=(sizes["cap_size"],sizes["cap_size"])).copy().remove_layers(remove,include_labels=True)
    cap.move(origin=cap.center,destination=(130,10))
    bottom=tuple(map(snap,cap.ports["bottom_met_W"].center))
    cap_top=tuple(map(snap,cap.ports["top_met_W"].center))
    # The independent gold's model pin 1 is stage1. Magic extracts the top
    # plate as pin 1, so preserve that intended orientation in the geometry.
    via("met3","met5",(stage1_x,cap_top[1]))
    segment("met5",(stage1_x,cap_top[1]),cap_top,width=.8,net="stage1")

    # Output joins the bottom M3 plate directly. Its external pin rail stays
    # below the plate, with a separate M2 spine joining the output devices.
    output_points=[point("NSECOND","D"),point("PSECOND","D")]
    output_x=max(p[0] for p in output_points)+2
    spine("VOUT",output_points,output_x,lower=-9)
    landing=(snap(cap.xmax+4),bottom[1])
    via("met3","met4",(output_x,bottom[1]))
    segment("met4",(output_x,bottom[1]),bottom,width=.8,net="VOUT")
    segment("met4",(output_x,-9),(landing[0],-9),width=.8,net="VOUT")
    via("met3","met4",(output_x,-9))
    pins["VOUT"]=(output_x,landing[0],-9)

    for net in PORTS:
        left,right,y=pins[net]
        x=snap(left+1 if net!="VOUT" else right-1)
        top.add_polygon([(x-.2,y-.2),(x+.2,y-.2),(x+.2,y+.2),(x-.2,y+.2)],layer=sky130.get_glayer("met4_pin"))
        top.add_label(net,position=(x,y),layer=sky130.get_glayer("met4_label"))
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    gds=output/"compact_miller_ota.gds"
    top.write_gds(gds)
    actual,=gdstk.read_gds(gds).top_level();actual.flatten();actual.name="compact_miller_ota"
    library=gdstk.Library();library.add(actual);library.write_gds(gds)
    (output/"layout_intent.json").write_text(json.dumps({"generator":"independent_block_Miller_OTA_assembly",
        "sizing":sizes,"placement":placement,"terminal_access":access,"critical_interconnects":routes,
        "capacitor":{"bottom_output":bottom,"top_stage1":cap_top,"output_pin_extent":landing},
        "bbox_um":[list(p) for p in actual.bounding_box()],
        "source_dependencies":["glayout.primitives.fet.nmos","glayout.primitives.fet.pmos",
            "glayout.primitives.mimcap.mimcap","glayout.primitives.via_gen.via_stack","gdsfactory.component.Component","gdstk"],
        "existing_OTA_or_benchmark_compiler_called":False,"formal_lineage_assignment":None},indent=2)+"\n")
    return gds
