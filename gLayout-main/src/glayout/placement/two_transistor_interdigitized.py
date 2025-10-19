from glayout.pdk.mappedpdk import MappedPDK
from pydantic import validate_arguments
from gdsfactory.component import Component
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.util.comp_utils import evaluate_bbox
from typing import Literal, Union
from glayout.util.port_utils import rename_ports_by_orientation, rename_ports_by_list, create_private_ports
from glayout.util.comp_utils import prec_ref_center,evaluate_bbox, prec_center, align_comp_to_port
from glayout.routing.straight_route import straight_route
from gdsfactory.functions import transformed
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import add_ports_perimeter
from gdsfactory.cell import clear_cache
from typing import Literal, Optional, Union
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.spice.netlist import Netlist
from gdsfactory.components import text_freetype, rectangle
from glayout.primitives.via_gen import via_stack
#from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized; from glayout.pdk.sky130_mapped import sky130_mapped_pdk as pdk; biasParams=[6,2,4]; rmult=2
def add_two_int_labels(two_int_in: Component,
                pdk: MappedPDK 
                ) -> Component:
	
    two_int_in.unlock()

    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    # vss1
    vss1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss1label.add_label(text="VSS1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss1label,two_int_in.ports["A_source_E"],None))
    # vss2
    vss2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss2label.add_label(text="VSS2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss2label,two_int_in.ports["B_source_E"],None))
    # vdd1
    vdd1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd1label.add_label(text="VDD1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd1label,two_int_in.ports["A_drain_N"],None))
    # vdd2
    vdd2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd2label.add_label(text="VDD2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd2label,two_int_in.ports["B_drain_N"],None))
    
    # vg1
    vg1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg1label.add_label(text="VG1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg1label,two_int_in.ports["A_gate_S"],None))
    # vg2
    vg2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg2label.add_label(text="VG2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg2label,two_int_in.ports["B_gate_S"],None))
    
    # VB
    vblabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.5,0.5),centered=True).copy()
    vblabel.add_label(text="VB",layer=pdk.get_glayer("met2_label"))
    move_info.append((vblabel,two_int_in.ports["welltie_S_top_met_S"], None))
    
    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        two_int_in.add(compref)
    return two_int_in.flatten() 


def two_tran_interdigitized_netlist(
    pdk: MappedPDK, 
    width: float,
    length: float,
    fingers: int,
    multipliers: int, 
    with_dummy: True,
    n_or_p_fet: Optional[str] = 'nfet',
    subckt_only: Optional[bool] = False
) -> Netlist:
    if length is None:
        length = pdk.get_grule('poly')['min_width']
    if width is None:
        width = 3 
    #mtop = multipliers if subckt_only else 1
    #mtop=1
    model = pdk.models[n_or_p_fet]
    mtop = fingers * multipliers
    
    source_netlist = """.subckt {circuit_name} {nodes} """ + f'l={length} w={width} m={1} '+ f"""
XA VDD1 VG1 VSS1 VB {model} l={length} w={width} m={mtop}
XB VDD2 VG2 VSS2 VB {model} l={length} w={width} m={mtop}"""
    if with_dummy:
        source_netlist += f"\nXDUMMY VB VB VB VB {model} l={length} w={width} m={2}"
    source_netlist += "\n.ends {circuit_name}"

    instance_format = "X{name} {nodes} {circuit_name} l={length} w={width} m={{1}}"
 
    return Netlist(
        circuit_name='two_trans_interdigitized',
        nodes=['VDD1', 'VDD2', 'VSS1', 'VSS2', 'VG1', 'VG2', 'VB'], 
        source_netlist=source_netlist,
        instance_format=instance_format,
        parameters={
            'model': model,
            'width': width,
            'length': length,   
            'mult': multipliers
        }
    )
@validate_arguments
def macro_two_transistor_interdigitized(
    pdk: MappedPDK,
    numcols: int,
    deviceA_and_B: Literal["nfet", "pfet"],
    dummy: Union[bool, tuple[bool, bool]] = True,
    **kwargs
) -> Component:
    """place two transistors in a single row with interdigitized placement
    Currently only supports two of the same transistor (same devices)
    Place follows an ABABAB... pattern
    args:
    pdk = MappedPDK to use
    numcols = a single col is actually one col for both transistors (so AB). 2 cols = ABAB ... so on
    deviceA_and_B = the device to place for both transistors (either nfet or pfet)
    dummy = place dummy at the edges of the interdigitized place (true by default). you can specify tuple to place only on one side
    kwargs = key word arguments for device. 
    ****NOTE: These are the same as glayout.flow.primitives.fet.multiplier arguments EXCLUDING dummy, sd_route_extension, and pdk options
    """
    if isinstance(dummy, bool):
        dummy = (dummy, dummy)
    # override kwargs for needed options
    kwargs["sd_route_extension"] = 0
    kwargs["gate_route_extension"] = 0
    kwargs["sdlayer"] = "n+s/d" if deviceA_and_B == "nfet" else "p+s/d"
    kwargs["pdk"] = pdk
    # create devices dummy l/r and A/B (change extension options)
    kwargs["dummy"] = (True,False) if dummy[0] else False
    lefttmost_devA = multiplier(**kwargs)
    kwargs["dummy"] = False
    center_devA = multiplier(**kwargs)
    devB_sd_extension = pdk.util_max_metal_seperation() + abs(center_devA.ports["drain_N"].center[1]-center_devA.ports["diff_N"].center[1])
    devB_gate_extension = pdk.util_max_metal_seperation() + abs(center_devA.ports["row0_col0_gate_S"].center[1]-center_devA.ports["gate_S"].center[1])
    kwargs["sd_route_extension"] = pdk.snap_to_2xgrid(devB_sd_extension)
    kwargs["gate_route_extension"] = pdk.snap_to_2xgrid(devB_gate_extension)
    center_devB = multiplier(**kwargs)
    kwargs["dummy"] = (False,True) if dummy[1] else False
    rightmost_devB = multiplier(**kwargs)
    # place devices
    idplace = Component()
    dims = evaluate_bbox(center_devA)
    xdisp = pdk.snap_to_2xgrid(dims[0]+pdk.get_grule("active_diff")["min_separation"])
    refs = list()
    for i in range(2*numcols):
        if i==0:
            refs.append(idplace << lefttmost_devA)
        elif i==((2*numcols)-1):
            refs.append(idplace << rightmost_devB)
        elif i%2: # is odd (so device B)
            refs.append(idplace << center_devB)
        else: # not i%2 == i is even (so device A)
            refs.append(idplace << center_devA)
        refs[-1].movex(i*(xdisp))
        devletter = "B" if i%2 else "A"
        prefix=devletter+"_"+str(int(i/2))+"_"
        idplace.add_ports(refs[-1].get_ports_list(), prefix=prefix)
    # extend poly layer for equal parasitics
    for i in range(2*numcols):
        desired_end_layer = pdk.layer_to_glayer(refs[i].ports["row0_col0_rightsd_top_met_N"].layer)
        idplace << straight_route(pdk, refs[i].ports["row0_col0_rightsd_top_met_N"],refs[-1].ports["drain_E"],glayer2=desired_end_layer)
        idplace << straight_route(pdk, refs[i].ports["leftsd_top_met_N"],refs[-1].ports["drain_E"],glayer2=desired_end_layer)
        if not i%2:
            desired_gate_end_layer = "poly"
            idplace << straight_route(pdk, refs[i].ports["row0_col0_gate_S"], refs[-1].ports["gate_E"],glayer2=desired_gate_end_layer)
    # merge s/d layer for all transistors
    idplace << straight_route(pdk, refs[0].ports["plusdoped_W"],refs[-1].ports["plusdoped_E"])
    # create s/d/gate connections extending over entire row
    A_src = idplace << rename_ports_by_orientation(rename_ports_by_list(straight_route(pdk, refs[0].ports["source_W"], refs[-1].ports["source_E"]), [("route_","_")]))
    B_src = idplace << rename_ports_by_orientation(rename_ports_by_list(straight_route(pdk, refs[-1].ports["source_E"], refs[0].ports["source_W"]), [("route_","_")]))
    A_drain = idplace << rename_ports_by_orientation(rename_ports_by_list(straight_route(pdk, refs[0].ports["drain_W"], refs[-1].ports["drain_E"]), [("route_","_")]))
    B_drain = idplace << rename_ports_by_orientation(rename_ports_by_list(straight_route(pdk, refs[-1].ports["drain_E"], refs[0].ports["drain_W"]), [("route_","_")]))
    A_gate = idplace << rename_ports_by_orientation(rename_ports_by_list(straight_route(pdk, refs[0].ports["gate_W"], refs[-1].ports["gate_E"]), [("route_","_")]))
    B_gate = idplace << rename_ports_by_orientation(rename_ports_by_list(straight_route(pdk, refs[-1].ports["gate_E"], refs[0].ports["gate_W"]), [("route_","_")]))
    # add route ports and return
    prefixes = ["A_source","B_source","A_drain","B_drain","A_gate","B_gate"]
    for i, ref in enumerate([A_src, B_src, A_drain, B_drain, A_gate, B_gate]):
        idplace.add_ports(ref.get_ports_list(),prefix=prefixes[i])
    idplace = transformed(prec_ref_center(idplace))
    idplace.unlock()
    idplace.add_ports(create_private_ports(idplace, prefixes))
    return idplace


@validate_arguments
def two_nfet_interdigitized(
    pdk: MappedPDK,
    numcols: int,
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str,str]=("met2","met1"),
    **kwargs
) -> Component:
    """Currently only supports two of the same nfet instances. does NOT support multipliers (currently)
    Place follows an ABABAB... pattern
    args:
    pdk = MappedPDK to use
    numcols = a single col is actually one col for both nfets (so AB). 2 cols = ABAB ... so on
    dummy = place dummy at the edges of the interdigitized place (true by default). you can specify tuple to place only on one side
    kwargs = key word arguments for multiplier. 
    ****NOTE: These are the same as glayout.flow.primitives.fet.multiplier arguments EXCLUDING dummy, sd_route_extension, and pdk options
    tie_layers: tuple[str,str] specifying (horizontal glayer, vertical glayer) or well tie ring. default=("met2","met1")
    """
    base_multiplier = macro_two_transistor_interdigitized(pdk, numcols, "nfet", dummy, **kwargs)
    # tie
    if with_tie:
        tap_separation = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule("p+s/d", "active_tap")["min_enclosure"]
        tap_encloses = (
            2 * (tap_separation + base_multiplier.xmax),
            2 * (tap_separation + base_multiplier.ymax),
        )
        tiering_ref = base_multiplier << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        base_multiplier.add_ports(tiering_ref.get_ports_list(), prefix="welltie_")
        try:
            base_multiplier<<straight_route(pdk,base_multiplier.ports["A_0_dummy_L_gsdcon_top_met_W"],base_multiplier.ports["welltie_W_top_met_W"],glayer2="met1")
        except KeyError:
            pass
        try:
            base_multiplier<<straight_route(pdk,base_multiplier.ports[f"B_{numcols-1}_dummy_R_gsdcon_top_met_E"],base_multiplier.ports["welltie_E_top_met_E"],glayer2="met1")
        except KeyError:
            pass
    # add pwell
    base_multiplier.add_padding(
        layers=(pdk.get_glayer("pwell"),),
        default=pdk.get_grule("pwell", "active_tap")["min_enclosure"],
    )
    # add substrate tap
    base_multiplier = add_ports_perimeter(base_multiplier,layer=pdk.get_glayer("pwell"),prefix="well_")
    # add substrate tap if with_substrate_tap
    if with_substrate_tap:
        substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")[
            "min_separation"
        ]
        substrate_tap_encloses = (
            2 * (substrate_tap_separation + base_multiplier.xmax),
            2 * (substrate_tap_separation + base_multiplier.ymax),
        )
        ringtoadd = tapring(
            pdk,
            enclosed_rectangle=substrate_tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer="met2",
            vertical_glayer="met1",
        )
        tapring_ref = base_multiplier << ringtoadd
        base_multiplier.add_ports(tapring_ref.get_ports_list(),prefix="substratetap_")
    base_multiplier.info["route_genid"] = "two_transistor_interdigitized"

    base_multiplier.info['netlist'] = two_tran_interdigitized_netlist(
        pdk, 
        width=kwargs.get('width', 3), length=kwargs.get('length', 0.15), fingers=kwargs.get('fingers', 1), multipliers=numcols, with_dummy=dummy,
        n_or_p_fet="nfet",
        subckt_only=True
    )
    return base_multiplier



@validate_arguments
def two_pfet_interdigitized(
    pdk: MappedPDK,
    numcols: int,
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str,str]=("met2","met1"),
    **kwargs
) -> Component:
    """Currently only supports two of the same nfet instances. does NOT support multipliers (currently)
    Place follows an ABABAB... pattern
    args:
    pdk = MappedPDK to use
    numcols = a single col is actually one col for both nfets (so AB). 2 cols = ABAB ... so on
    dummy = place dummy at the edges of the interdigitized place (true by default). you can specify tuple to place only on one side
    kwargs = key word arguments for multiplier. 
    ****NOTE: These are the same as glayout.flow.primitives.fet.multiplier arguments EXCLUDING dummy, sd_route_extension, and pdk options
    tie_layers: tuple[str,str] specifying (horizontal glayer, vertical glayer) or well tie ring. default=("met2","met1")
    """
    base_multiplier = macro_two_transistor_interdigitized(pdk, numcols, "pfet", dummy, **kwargs)
    # tie
    if with_tie:
        tap_separation = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule("n+s/d", "active_tap")["min_enclosure"] 
        tap_encloses = (
            2 * (tap_separation + base_multiplier.xmax),
            2 * (tap_separation + base_multiplier.ymax),
        )
        tiering_ref = base_multiplier << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="n+s/d",
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        base_multiplier.add_ports(tiering_ref.get_ports_list(), prefix="welltie_")
        try:
            base_multiplier<<straight_route(pdk,base_multiplier.ports["A_0_dummy_L_gsdcon_top_met_W"],base_multiplier.ports["welltie_W_top_met_W"],glayer2="met1")
        except KeyError:
            pass
        try:
            base_multiplier<<straight_route(pdk,base_multiplier.ports[f"B_{numcols-1}_dummy_R_gsdcon_top_met_E"],base_multiplier.ports["welltie_E_top_met_E"],glayer2="met1")
        except KeyError:
            pass
    # add pwell
    base_multiplier.add_padding(
        layers=(pdk.get_glayer("nwell"),),
        default=pdk.get_grule("nwell", "active_tap")["min_enclosure"],
    )
    # add substrate tap
    base_multiplier = add_ports_perimeter(base_multiplier,layer=pdk.get_glayer("nwell"),prefix="well_")
    # add substrate tap if with_substrate_tap
    if with_substrate_tap:
        substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")[
            "min_separation"
        ]
        substrate_tap_encloses = (
            2 * (substrate_tap_separation + base_multiplier.xmax),
            2 * (substrate_tap_separation + base_multiplier.ymax),
        )
        ringtoadd = tapring(
            pdk,
            enclosed_rectangle=substrate_tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer="met2",
            vertical_glayer="met1",
        )
        tapring_ref = base_multiplier << ringtoadd
        base_multiplier.add_ports(tapring_ref.get_ports_list(),prefix="substratetap_")
    base_multiplier.info["route_genid"] = "two_transistor_interdigitized"

    base_multiplier.info['netlist'] = two_tran_interdigitized_netlist(
        pdk, 
        width=kwargs.get('width', 3), length=kwargs.get('length', 0.15), fingers=kwargs.get('fingers', 1), multipliers=numcols, with_dummy=dummy,
        n_or_p_fet="pfet",
        subckt_only=True
    )
    return base_multiplier




def two_transistor_interdigitized(
    pdk: MappedPDK,
    device: Literal["nfet","pfet"],
    numcols: int,
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str,str]=("met2","met1"),
    **kwargs
) -> Component:
    if device=="nfet":
        return two_nfet_interdigitized(pdk=pdk,numcols=numcols,dummy=dummy,with_substrate_tap=with_substrate_tap,with_tie=with_tie,tie_layers=tie_layers,**kwargs)
    else:
        return two_pfet_interdigitized(pdk=pdk,numcols=numcols,dummy=dummy,with_substrate_tap=with_substrate_tap,with_tie=with_tie,tie_layers=tie_layers,**kwargs)