from glayout import MappedPDK, sky130,gf180
from glayout.routing import c_route,L_route,straight_route
from glayout.spice.netlist import Netlist
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from glayout.spice.netlist import Netlist
from glayout.primitives.fet import nmos, pmos
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import add_ports_perimeter,rename_ports_by_orientation
from gdsfactory.component import Component
from gdsfactory.cell import cell
from glayout.util.comp_utils import evaluate_bbox, prec_center, prec_ref_center, align_comp_to_port
from typing import Optional, Union 
from glayout.primitives.via_gen import via_stack
from gdsfactory.components import text_freetype, rectangle

try:
    from evaluator_wrapper import run_evaluation
except ImportError:
    print("Warning: evaluator_wrapper not found. Evaluation will be skipped.")
    run_evaluation = None

def sky130_add_cm_labels(cm_in: Component) -> Component:
	
    cm_in.unlock()
    
    # define layers`
    met1_pin = (68,16)
    met1_label = (68,5)
    met2_pin = (69,16)
    met2_label = (69,5)
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    # vss
    vsslabel = rectangle(layer=met1_pin,size=(0.27,0.27),centered=True).copy()
    vsslabel.add_label(text="VSS",layer=met1_label)
    move_info.append((vsslabel,cm_in.ports["fet_A_source_E"],None))
    
    # vref
    vreflabel = rectangle(layer=met1_pin,size=(0.27,0.27),centered=True).copy()
    vreflabel.add_label(text="VREF",layer=met1_label)
    move_info.append((vreflabel,cm_in.ports["fet_A_drain_N"],None))
    
    # vcopy
    vcopylabel = rectangle(layer=met1_pin,size=(0.27,0.27),centered=True).copy()
    vcopylabel.add_label(text="VCOPY",layer=met1_label)
    move_info.append((vcopylabel,cm_in.ports["fet_B_drain_N"],None))
    
    # VB
    vblabel = rectangle(layer=met1_pin,size=(0.5,0.5),centered=True).copy()
    vblabel.add_label(text="VB",layer=met1_label)
    move_info.append((vblabel,cm_in.ports["welltie_S_top_met_S"], None))
    
    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        cm_in.add(compref)
    return cm_in.flatten() 

def current_mirror_netlist(
    pdk: MappedPDK, 
    width: float,
    length: float,
    multipliers: int, 
    with_dummy: Optional[bool] = False,
    n_or_p_fet: Optional[str] = 'nfet',
    subckt_only: Optional[bool] = False
) -> Netlist:
    if length is None:
        length = pdk.get_grule('poly')['min_width']
    if width is None:
        width = 3 
    mtop = multipliers if subckt_only else 1
    model = pdk.models[n_or_p_fet]
    
    source_netlist = """.subckt {circuit_name} {nodes} """ + f'l={length} w={width} m={mtop} ' + """
XA VREF VREF VSS VB {model} l={{l}} w={{w}} m={{m}}
XB VCOPY VREF VSS VB {model} l={{l}} w={{w}} m={{m}}"""
    if with_dummy:
        source_netlist += "\nXDUMMY VB VB VB VB {model} l={{l}} w={{w}} m={{2}}"
    source_netlist += "\n.ends {circuit_name}"

    instance_format = "X{name} {nodes} {circuit_name} l={length} w={width} m={mult}"
 
    return Netlist(
        circuit_name='CMIRROR',
        nodes=['VREF', 'VCOPY', 'VSS', 'VB'], 
        source_netlist=source_netlist,
        instance_format=instance_format,
        parameters={
            'model': model,
            'width': width,
            'length': length,   
            'mult': multipliers
        }
    )


@cell
def current_mirror(
    pdk: MappedPDK, 
    numcols: int = 3,
    device: str = 'nfet',
    with_dummy: Optional[bool] = True,
    with_substrate_tap: Optional[bool] = False,
    with_tie: Optional[bool] = True,
    tie_layers: tuple[str,str]=("met2","met1"),
    **kwargs
) -> Component:
    """An instantiable current mirror that returns a Component object. The current mirror is a two transistor interdigitized structure with a shorted source and gate. It can be instantiated with either nmos or pmos devices. It can also be instantiated with a dummy device, a substrate tap, and a tie layer, and is centered at the origin. Transistor A acts as the reference and Transistor B acts as the mirror fet

    Args:
        pdk (MappedPDK): the process design kit to use
        numcols (int): number of columns of the interdigitized fets
        device (str): nfet or pfet (can only interdigitize one at a time with this option)
        with_dummy (bool): True places dummies on either side of the interdigitized fets
        with_substrate_tap (bool): boolean to decide whether to place a substrate tapring
        with_tie (bool): boolean to decide whether to place a tapring for tielayer
        tie_layers (tuple[str,str], optional): the layers to use for the tie. Defaults to ("met2","met1").
        **kwargs: The keyword arguments are passed to the two_nfet_interdigitized or two_pfet_interdigitized functions and need to be valid arguments that can be accepted by the multiplier function

    Returns:
        Component: a current mirror component object
    """
    top_level = Component("current mirror")
    if device in ['nmos', 'nfet']:
        interdigitized_fets = two_nfet_interdigitized(
            pdk, 
            numcols=numcols, 
            dummy=with_dummy, 
            with_substrate_tap=False, 
            with_tie=False, 
            **kwargs
        )
    elif device in ['pmos', 'pfet']:
        interdigitized_fets = two_pfet_interdigitized(
            pdk, 
            numcols=numcols, 
            dummy=with_dummy, 
            with_substrate_tap=False, 
            with_tie=False, 
            **kwargs
        )
    top_level.add_ports(interdigitized_fets.get_ports_list(), prefix="fet_")
    maxmet_sep = pdk.util_max_metal_seperation()
    # short source of the fets
    source_short = interdigitized_fets << c_route(pdk, interdigitized_fets.ports['A_source_E'], interdigitized_fets.ports['B_source_E'], extension=3*maxmet_sep, viaoffset=False)
    # short gates of the fets
    gate_short = interdigitized_fets << c_route(pdk, interdigitized_fets.ports['A_gate_W'], interdigitized_fets.ports['B_gate_W'], extension=3*maxmet_sep, viaoffset=False)
    # short gate and drain of one of the reference 
    interdigitized_fets << L_route(pdk, interdigitized_fets.ports['A_drain_W'], gate_short.ports['con_N'], viaoffset=False, fullbottom=False)
    
    top_level << interdigitized_fets
    if with_tie:
        if device in ['nmos','nfet']:
            tap_layer = "p+s/d"
        if device in ['pmos','pfet']:
            tap_layer = "n+s/d"
        tap_sep = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_sep += pdk.get_grule(tap_layer, "active_tap")["min_enclosure"]
        tap_encloses = (
        2 * (tap_sep + interdigitized_fets.xmax),
        2 * (tap_sep + interdigitized_fets.ymax),
        )
        tie_ref = top_level << tapring(pdk, enclosed_rectangle = tap_encloses, sdlayer = tap_layer, horizontal_glayer = tie_layers[0], vertical_glayer = tie_layers[1])
        top_level.add_ports(tie_ref.get_ports_list(), prefix="welltie_")
        try:
            top_level << straight_route(pdk, top_level.ports[f"fet_B_{numcols - 1}_dummy_R_gsdcon_top_met_E"],top_level.ports["welltie_E_top_met_E"],glayer2="met1")
            top_level << straight_route(pdk, top_level.ports["fet_A_0_dummy_L_gsdcon_top_met_W"],top_level.ports["welltie_W_top_met_W"],glayer2="met1")
        except KeyError:
            pass
        try:
            end_col = numcols - 1
            port1 = f'B_{end_col}_dummy_R_gdscon_top_met_E'
            top_level << straight_route(pdk, top_level.ports[port1], top_level.ports["welltie_E_top_met_E"], glayer2="met1")
        except KeyError:
            pass
    
    # add a pwell 
    if device in ['nmos','nfet']:
        top_level.add_padding(layers = (pdk.get_glayer("pwell"),), default = pdk.get_grule("pwell", "active_tap")["min_enclosure"], )
        top_level = add_ports_perimeter(top_level, layer = pdk.get_glayer("pwell"), prefix="well_")
    if device in ['pmos','pfet']:
        top_level.add_padding(layers = (pdk.get_glayer("nwell"),), default = pdk.get_grule("nwell", "active_tap")["min_enclosure"], )
        top_level = add_ports_perimeter(top_level, layer = pdk.get_glayer("nwell"), prefix="well_")

 
    # add the substrate tap if specified
    if with_substrate_tap:
        subtap_sep = pdk.get_grule("dnwell", "active_tap")["min_separation"]
        subtap_enclosure = (
            2.5 * (subtap_sep + interdigitized_fets.xmax),
            2.5 * (subtap_sep + interdigitized_fets.ymax),
        )
        subtap_ring = top_level << tapring(pdk, enclosed_rectangle = subtap_enclosure, sdlayer = "p+s/d", horizontal_glayer = "met2", vertical_glayer = "met1")
        top_level.add_ports(subtap_ring.get_ports_list(), prefix="substrate_tap_")
  
    top_level.add_ports(source_short.get_ports_list(), prefix='purposegndports')
    
    
    top_level.info['netlist'] = current_mirror_netlist(
        pdk, 
        width=kwargs.get('width', 3), length=kwargs.get('length', 0.15), multipliers=numcols, with_dummy=with_dummy,
        n_or_p_fet=device,
        subckt_only=True
    )
 
    return top_level


def sky130_add_current_mirror_labels(current_mirror_in: Component) -> Component:
    """
    Add labels to current mirror component for simulation and testing
    """
    current_mirror_in.unlock()
    # define layers
    met1_pin = (68,16)
    met1_label = (68,5)
    met2_pin = (69,16)
    met2_label = (69,5)
    # list that will contain all port/comp info
    move_info = list()
    
    # Reference voltage (drain of reference transistor)
    vref_label = rectangle(layer=met1_pin, size=(0.5,0.5), centered=True).copy()
    vref_label.add_label(text="VREF", layer=met1_label)
    
    # Copy current output (drain of mirror transistor)  
    vcopy_label = rectangle(layer=met1_pin, size=(0.5,0.5), centered=True).copy()
    vcopy_label.add_label(text="VCOPY", layer=met1_label)
    
    # Ground/VSS (source connections)
    vss_label = rectangle(layer=met1_pin, size=(0.5,0.5), centered=True).copy()
    vss_label.add_label(text="VSS", layer=met1_label)
    
    # Bulk/VB (bulk/body connections)
    vb_label = rectangle(layer=met1_pin, size=(0.5,0.5), centered=True).copy()
    vb_label.add_label(text="VB", layer=met1_label)
    
    # Try to find appropriate ports and add labels
    try:
        # Look for drain ports for VREF and VCOPY
        ref_drain_ports = [p for p in current_mirror_in.ports.keys() if 'A_drain' in p and 'met' in p]
        copy_drain_ports = [p for p in current_mirror_in.ports.keys() if 'B_drain' in p and 'met' in p]
        source_ports = [p for p in current_mirror_in.ports.keys() if 'source' in p and 'met' in p]
        bulk_ports = [p for p in current_mirror_in.ports.keys() if ('tie' in p or 'well' in p) and 'met' in p]
        
        if ref_drain_ports:
            move_info.append((vref_label, current_mirror_in.ports[ref_drain_ports[0]], None))
        if copy_drain_ports:
            move_info.append((vcopy_label, current_mirror_in.ports[copy_drain_ports[0]], None))
        if source_ports:
            move_info.append((vss_label, current_mirror_in.ports[source_ports[0]], None))
        if bulk_ports:
            move_info.append((vb_label, current_mirror_in.ports[bulk_ports[0]], None))
            
    except (KeyError, IndexError):
        # Fallback - just add labels at component center
        print("Warning: Could not find specific ports for labels, using fallback positioning")
        move_info = [
            (vref_label, None, None),
            (vcopy_label, None, None), 
            (vss_label, None, None),
            (vb_label, None, None)
        ]
    
    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        if prt is not None:
            compref = align_comp_to_port(comp, prt, alignment=alignment)
        else:
            compref = comp
        current_mirror_in.add(compref)
    
    return current_mirror_in.flatten()


# Create and evaluate a current mirror instance
if __name__ == "__main__":
    # OLD EVAL CODE
    # comp = current_mirror(sky130)
    # # comp.pprint_ports()
    # comp = add_cm_labels(comp,sky130)
    # comp.name = "CM"
    # comp.show()
    # #print(comp.info['netlist'].generate_netlist())
    # print("...Running DRC...")
    # drc_result = sky130.drc_magic(comp, "CM")
    # ## Klayout DRC
    # #drc_result = sky130.drc(comp)\n
    
    # time.sleep(5)
        
    # print("...Running LVS...")
    # lvs_res=sky130.lvs_netgen(comp, "CM")
    # #print("...Saving GDS...")
    # #comp.write_gds('out_CMirror.gds')

    # NEW EVAL CODE
    # Create current mirror with labels
    cm = sky130_add_current_mirror_labels(
        current_mirror(
            pdk=sky130, 
            numcols=3, 
            device='nfet', 
            width=3, 
            length=1, 
            with_dummy=True,
            with_tie=True
        )
    )
    
    # Show the layout
    cm.show()
    cm.name = "current_mirror"
    
    # Write GDS file
    cm_gds = cm.write_gds("current_mirror.gds")
    
    # Run evaluation if available
    if run_evaluation is not None:
        result = run_evaluation("current_mirror.gds", cm.name, cm)
        print(result)
    else:
        print("Evaluation skipped - evaluator_wrapper not available")
