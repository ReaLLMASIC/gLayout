from typing import Optional, Union
from glayout import MappedPDK, sky130,gf180
from glayout.spice.netlist import Netlist
from glayout.routing import c_route,L_route,straight_route

from gdsfactory.cell import cell
from gdsfactory.component import Component, copy
from gdsfactory.components.rectangle import rectangle
from gdsfactory.routing.route_quad import route_quad
from gdsfactory.routing.route_sharp import route_sharp
from glayout.pdk.mappedpdk import MappedPDK
from glayout.util.comp_utils import align_comp_to_port, evaluate_bbox, movex, movey
from glayout.util.port_utils import (
    add_ports_perimeter,
    get_orientation,
    print_ports,
    rename_ports_by_list,
    rename_ports_by_orientation,
    set_port_orientation,
)
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.placement.common_centroid_ab_ba import common_centroid_ab_ba
from glayout.primitives.fet import nmos, pmos
from glayout.primitives.guardring import tapring
from glayout.primitives.via_gen import via_stack
from glayout.routing.smart_route import smart_route
from glayout.spice import Netlist
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
from gdsfactory.components import text_freetype
try:
    from evaluator_wrapper import run_evaluation
except ImportError:
    print("Warning: evaluator_wrapper not found. Evaluation will be skipped.")
    run_evaluation = None


def sky130_add_df_labels(df_in: Component) -> Component:
	
    df_in.unlock()
    
    # define layers`
    met1_pin = (68,16)
    met1_label = (68,5)
    li1_pin = (67,16)
    li1_label = (67,5)
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    # vtail
    vtaillabel = rectangle(layer=met1_pin,size=(0.27,0.27),centered=True).copy()
    vtaillabel.add_label(text="VTAIL",layer=met1_label)
    move_info.append((vtaillabel,df_in.ports["bl_multiplier_0_source_S"],None))
    
    # vdd1
    vdd1label = rectangle(layer=met1_pin,size=(0.27,0.27),centered=True).copy()
    vdd1label.add_label(text="VDD1",layer=met1_label)
    move_info.append((vdd1label,df_in.ports["tl_multiplier_0_drain_N"],None))
    
    # vdd2
    vdd2label = rectangle(layer=met1_pin,size=(0.27,0.27),centered=True).copy()
    vdd2label.add_label(text="VDD2",layer=met1_label)
    move_info.append((vdd2label,df_in.ports["tr_multiplier_0_drain_N"],None))
    
    # VB
    vblabel = rectangle(layer=li1_pin,size=(0.5,0.5),centered=True).copy()
    vblabel.add_label(text="B",layer=li1_label)
    move_info.append((vblabel,df_in.ports["tap_N_top_met_S"], None))
    
    # VP
    vplabel = rectangle(layer=met1_pin,size=(0.27,0.27),centered=True).copy()
    vplabel.add_label(text="VP",layer=met1_label)
    move_info.append((vplabel,df_in.ports["br_multiplier_0_gate_S"], None))
    
    # VN
    vnlabel = rectangle(layer=met1_pin,size=(0.27,0.27),centered=True).copy()
    vnlabel.add_label(text="VN",layer=met1_label)
    move_info.append((vnlabel,df_in.ports["bl_multiplier_0_gate_S"], None))

    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        df_in.add(compref)
    return df_in.flatten() 

def diff_pair_netlist(fetL: Component, fetR: Component) -> Netlist:
	diff_pair_netlist = Netlist(circuit_name='DIFF_PAIR', nodes=['VP', 'VN', 'VDD1', 'VDD2', 'VTAIL', 'B'])
	
	# Handle fetL netlist - reconstruct if it's a string
	fetL_netlist = fetL.info['netlist']
	if isinstance(fetL_netlist, str):
		if 'netlist_data' in fetL.info:
			data = fetL.info['netlist_data']
			fetL_netlist = Netlist(circuit_name=data['circuit_name'], nodes=data['nodes'])
			fetL_netlist.source_netlist = data['source_netlist']
			if 'parameters' in data:
				fetL_netlist.parameters = data['parameters']
		else:
			raise ValueError("No netlist_data found for string netlist in fetL component.info")
	
	# Handle fetR netlist - reconstruct if it's a string
	fetR_netlist = fetR.info['netlist']
	if isinstance(fetR_netlist, str):
		if 'netlist_data' in fetR.info:
			data = fetR.info['netlist_data']
			fetR_netlist = Netlist(circuit_name=data['circuit_name'], nodes=data['nodes'])
			fetR_netlist.source_netlist = data['source_netlist']
			if 'parameters' in data:
				fetR_netlist.parameters = data['parameters']
		else:
			raise ValueError("No netlist_data found for string netlist in fetR component.info")
	
	diff_pair_netlist.connect_netlist(
		fetL_netlist,
		[('D', 'VDD1'), ('G', 'VP'), ('S', 'VTAIL'), ('B', 'B')]
	)
	diff_pair_netlist.connect_netlist(
		fetR_netlist,
		[('D', 'VDD2'), ('G', 'VN'), ('S', 'VTAIL'), ('B', 'B')]
	)
	return diff_pair_netlist

def sky130_add_diff_pair_labels(diff_pair_in: Component) -> Component:
    """
    Add labels to differential pair component for simulation and testing
    """
    diff_pair_in.unlock()
    # define layers
    met1_pin = (68,16)
    met1_label = (68,5)
    met2_pin = (69,16)
    met2_label = (69,5)
    # list that will contain all port/comp info
    move_info = list()
    
    # Positive input (VP)
    vp_label = rectangle(layer=met1_pin, size=(0.5,0.5), centered=True).copy()
    vp_label.add_label(text="VP", layer=met1_label)
    
    # Negative input (VN)
    vn_label = rectangle(layer=met1_pin, size=(0.5,0.5), centered=True).copy()
    vn_label.add_label(text="VN", layer=met1_label)
    
    # Positive output drain (VDD1)
    vdd1_label = rectangle(layer=met2_pin, size=(0.5,0.5), centered=True).copy()
    vdd1_label.add_label(text="VDD1", layer=met2_label)
    
    # Negative output drain (VDD2)
    vdd2_label = rectangle(layer=met2_pin, size=(0.5,0.5), centered=True).copy()
    vdd2_label.add_label(text="VDD2", layer=met2_label)
    
    # Tail current (VTAIL)
    vtail_label = rectangle(layer=met1_pin, size=(0.5,0.5), centered=True).copy()
    vtail_label.add_label(text="VTAIL", layer=met1_label)
    
    # Bulk/Body (B)
    b_label = rectangle(layer=met1_pin, size=(0.5,0.5), centered=True).copy()
    b_label.add_label(text="B", layer=met1_label)
    
    # Try to find appropriate ports and add labels
    try:
        # Look for gate ports for VP and VN
        plus_gate_ports = [p for p in diff_pair_in.ports.keys() if 'PLUSgate' in p and 'met' in p]
        minus_gate_ports = [p for p in diff_pair_in.ports.keys() if 'MINUSgate' in p and 'met' in p]
        
        # Look for drain ports for VDD1 and VDD2
        drain_ports = [p for p in diff_pair_in.ports.keys() if 'drain_route' in p and 'met' in p]
        
        # Look for source ports for VTAIL
        source_ports = [p for p in diff_pair_in.ports.keys() if 'source_route' in p and 'met' in p]
        
        # Look for bulk/tie ports
        bulk_ports = [p for p in diff_pair_in.ports.keys() if ('tie' in p or 'well' in p or 'tap' in p) and 'met' in p]
        
        if plus_gate_ports:
            move_info.append((vp_label, diff_pair_in.ports[plus_gate_ports[0]], None))
        if minus_gate_ports:
            move_info.append((vn_label, diff_pair_in.ports[minus_gate_ports[0]], None))
        if len(drain_ports) >= 2:
            move_info.append((vdd1_label, diff_pair_in.ports[drain_ports[0]], None))
            move_info.append((vdd2_label, diff_pair_in.ports[drain_ports[1]], None))
        elif len(drain_ports) == 1:
            move_info.append((vdd1_label, diff_pair_in.ports[drain_ports[0]], None))
        if source_ports:
            move_info.append((vtail_label, diff_pair_in.ports[source_ports[0]], None))
        if bulk_ports:
            move_info.append((b_label, diff_pair_in.ports[bulk_ports[0]], None))
            
    except (KeyError, IndexError):
        # Fallback - just add labels at component center
        print("Warning: Could not find specific ports for labels, using fallback positioning")
        move_info = [
            (vp_label, None, None),
            (vn_label, None, None), 
            (vdd1_label, None, None),
            (vdd2_label, None, None),
            (vtail_label, None, None),
            (b_label, None, None)
        ]
    
    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        if prt is not None:
            compref = align_comp_to_port(comp, prt, alignment=alignment)
        else:
            compref = comp
        diff_pair_in.add(compref)
    
    return diff_pair_in.flatten()

@cell
def diff_pair(
	pdk: MappedPDK,
	width: float = 3,
	fingers: int = 4,
	length: Optional[float] = None,
	n_or_p_fet: bool = True,
	plus_minus_seperation: float = 0,
	rmult: int = 1,
	dummy: Union[bool, tuple[bool, bool]] = True,
	substrate_tap: bool=True
) -> Component:
	"""create a diffpair with 2 transistors placed in two rows with common centroid place. Sources are shorted
	width = width of the transistors
	fingers = number of fingers in the transistors (must be 2 or more)
	length = length of the transistors, None or 0 means use min length
	short_source = if true connects source of both transistors
	n_or_p_fet = if true the diffpair is made of nfets else it is made of pfets
	substrate_tap: if true place a tapring around the diffpair (connects on met1)
	"""
	# TODO: error checking
	pdk.activate()
	diffpair = Component()
	# create transistors
	well = None
	if isinstance(dummy, bool):
		dummy = (dummy, dummy)
	if n_or_p_fet:
		fetL = nmos(pdk, width=width, fingers=fingers,length=length,multipliers=1,with_tie=False,with_dummy=(dummy[0], False),with_dnwell=False,with_substrate_tap=False,rmult=rmult)
		fetR = nmos(pdk, width=width, fingers=fingers,length=length,multipliers=1,with_tie=False,with_dummy=(False,dummy[1]),with_dnwell=False,with_substrate_tap=False,rmult=rmult)
		min_spacing_x = pdk.get_grule("n+s/d")["min_separation"] - 2*(fetL.xmax - fetL.ports["multiplier_0_plusdoped_E"].center[0])
		well = "pwell"
	else:
		fetL = pmos(pdk, width=width, fingers=fingers,length=length,multipliers=1,with_tie=False,with_dummy=(dummy[0], False),dnwell=False,with_substrate_tap=False,rmult=rmult)
		fetR = pmos(pdk, width=width, fingers=fingers,length=length,multipliers=1,with_tie=False,with_dummy=(False,dummy[1]),dnwell=False,with_substrate_tap=False,rmult=rmult)
		min_spacing_x = pdk.get_grule("p+s/d")["min_separation"] - 2*(fetL.xmax - fetL.ports["multiplier_0_plusdoped_E"].center[0])
		well = "nwell"
	# place transistors
	viam2m3 = via_stack(pdk,"met2","met3",centered=True)
	metal_min_dim = max(pdk.get_grule("met2")["min_width"],pdk.get_grule("met3")["min_width"])
	metal_space = max(pdk.get_grule("met2")["min_separation"],pdk.get_grule("met3")["min_separation"],metal_min_dim)
	gate_route_os = evaluate_bbox(viam2m3)[0] - fetL.ports["multiplier_0_gate_W"].width + metal_space
	min_spacing_y = metal_space + 2*gate_route_os
	min_spacing_y = min_spacing_y - 2*abs(fetL.ports["well_S"].center[1] - fetL.ports["multiplier_0_gate_S"].center[1])
	# TODO: fix spacing where you see +-0.5
	a_topl = (diffpair << fetL).movey(fetL.ymax+min_spacing_y/2+0.5).movex(0-fetL.xmax-min_spacing_x/2)
	b_topr = (diffpair << fetR).movey(fetR.ymax+min_spacing_y/2+0.5).movex(fetL.xmax+min_spacing_x/2)
	a_botr = (diffpair << fetR)
	a_botr.mirror_y()
	a_botr.movey(0-0.5-fetL.ymax-min_spacing_y/2).movex(fetL.xmax+min_spacing_x/2)
	b_botl = (diffpair << fetL)
	b_botl.mirror_y()
	b_botl.movey(0-0.5-fetR.ymax-min_spacing_y/2).movex(0-fetL.xmax-min_spacing_x/2)
	# if substrate tap place substrate tap
	if substrate_tap:
		tapref = diffpair << tapring(pdk,evaluate_bbox(diffpair,padding=1),horizontal_glayer="met1")
		diffpair.add_ports(tapref.get_ports_list(),prefix="tap_")
		try:
			diffpair<<straight_route(pdk,a_topl.ports["multiplier_0_dummy_L_gsdcon_top_met_W"],diffpair.ports["tap_W_top_met_W"],glayer2="met1")
		except KeyError:
			pass
		try:
			diffpair<<straight_route(pdk,b_topr.ports["multiplier_0_dummy_R_gsdcon_top_met_W"],diffpair.ports["tap_E_top_met_E"],glayer2="met1")
		except KeyError:
			pass
		try:
			diffpair<<straight_route(pdk,b_botl.ports["multiplier_0_dummy_L_gsdcon_top_met_W"],diffpair.ports["tap_W_top_met_W"],glayer2="met1")
		except KeyError:
			pass
		try:
			diffpair<<straight_route(pdk,a_botr.ports["multiplier_0_dummy_R_gsdcon_top_met_W"],diffpair.ports["tap_E_top_met_E"],glayer2="met1")
		except KeyError:
			pass
	# route sources (short sources)
	diffpair << route_quad(a_topl.ports["multiplier_0_source_E"], b_topr.ports["multiplier_0_source_W"], layer=pdk.get_glayer("met2"))
	diffpair << route_quad(b_botl.ports["multiplier_0_source_E"], a_botr.ports["multiplier_0_source_W"], layer=pdk.get_glayer("met2"))
	sextension = b_topr.ports["well_E"].center[0] - b_topr.ports["multiplier_0_source_E"].center[0]
	source_routeE = diffpair << c_route(pdk, b_topr.ports["multiplier_0_source_E"], a_botr.ports["multiplier_0_source_E"],extension=sextension)
	source_routeW = diffpair << c_route(pdk, a_topl.ports["multiplier_0_source_W"], b_botl.ports["multiplier_0_source_W"],extension=sextension)
	# route drains
	# place via at the drain
	drain_br_via = diffpair << viam2m3
	drain_bl_via = diffpair << viam2m3
	drain_br_via.move(a_botr.ports["multiplier_0_drain_N"].center).movey(viam2m3.ymin)
	drain_bl_via.move(b_botl.ports["multiplier_0_drain_N"].center).movey(viam2m3.ymin)
	drain_br_viatm = diffpair << viam2m3
	drain_bl_viatm = diffpair << viam2m3
	drain_br_viatm.move(a_botr.ports["multiplier_0_drain_N"].center).movey(viam2m3.ymin)
	drain_bl_viatm.move(b_botl.ports["multiplier_0_drain_N"].center).movey(-1.5 * evaluate_bbox(viam2m3)[1] - metal_space)
	# create route to drain via
	width_drain_route = b_topr.ports["multiplier_0_drain_E"].width
	dextension = source_routeE.xmax - b_topr.ports["multiplier_0_drain_E"].center[0] + metal_space
	bottom_extension = viam2m3.ymax + width_drain_route/2 + 2*metal_space
	drain_br_viatm.movey(0-bottom_extension - metal_space - width_drain_route/2 - viam2m3.ymax)
	diffpair << route_quad(drain_br_viatm.ports["top_met_N"], drain_br_via.ports["top_met_S"], layer=pdk.get_glayer("met3"))
	diffpair << route_quad(drain_bl_viatm.ports["top_met_N"], drain_bl_via.ports["top_met_S"], layer=pdk.get_glayer("met3"))
	floating_port_drain_bottom_L = set_port_orientation(movey(drain_bl_via.ports["bottom_met_W"],0-bottom_extension), get_orientation("E"))
	floating_port_drain_bottom_R = set_port_orientation(movey(drain_br_via.ports["bottom_met_E"],0-bottom_extension - metal_space - width_drain_route), get_orientation("W"))
	drain_routeTR_BL = diffpair << c_route(pdk, floating_port_drain_bottom_L, b_topr.ports["multiplier_0_drain_E"],extension=dextension, width1=width_drain_route,width2=width_drain_route)
	drain_routeTL_BR = diffpair << c_route(pdk, floating_port_drain_bottom_R, a_topl.ports["multiplier_0_drain_W"],extension=dextension, width1=width_drain_route,width2=width_drain_route)
	# cross gate route top with c_route. bar_minus ABOVE bar_plus
	get_left_extension = lambda bar, a_topl=a_topl, diffpair=diffpair, pdk=pdk : (abs(diffpair.xmin-min(a_topl.ports["multiplier_0_gate_W"].center[0],bar.ports["e1"].center[0])) + pdk.get_grule("met2")["min_separation"])
	get_right_extension = lambda bar, b_topr=b_topr, diffpair=diffpair, pdk=pdk : (abs(diffpair.xmax-max(b_topr.ports["multiplier_0_gate_E"].center[0],bar.ports["e3"].center[0])) + pdk.get_grule("met2")["min_separation"])
	# lay bar plus and PLUSgate_routeW
	bar_comp = rectangle(centered=True,size=(abs(b_topr.xmax-a_topl.xmin), b_topr.ports["multiplier_0_gate_E"].width),layer=pdk.get_glayer("met2"))
	bar_plus = (diffpair << bar_comp).movey(diffpair.ymax + bar_comp.ymax + pdk.get_grule("met2")["min_separation"])
	PLUSgate_routeW = diffpair << c_route(pdk, a_topl.ports["multiplier_0_gate_W"], bar_plus.ports["e1"], extension=get_left_extension(bar_plus))
	# lay bar minus and MINUSgate_routeE
	plus_minus_seperation = max(pdk.get_grule("met2")["min_separation"], plus_minus_seperation)
	bar_minus = (diffpair << bar_comp).movey(diffpair.ymax +bar_comp.ymax + plus_minus_seperation)
	MINUSgate_routeE = diffpair << c_route(pdk, b_topr.ports["multiplier_0_gate_E"], bar_minus.ports["e3"], extension=get_right_extension(bar_minus))
	# lay MINUSgate_routeW and PLUSgate_routeE
	MINUSgate_routeW = diffpair << c_route(pdk, set_port_orientation(b_botl.ports["multiplier_0_gate_E"],"W"), bar_minus.ports["e1"], extension=get_left_extension(bar_minus))
	PLUSgate_routeE = diffpair << c_route(pdk, set_port_orientation(a_botr.ports["multiplier_0_gate_W"],"E"), bar_plus.ports["e3"], extension=get_right_extension(bar_plus))
	# correct pwell place, add ports, flatten, and return
	diffpair.add_ports(a_topl.get_ports_list(),prefix="tl_")
	diffpair.add_ports(b_topr.get_ports_list(),prefix="tr_")
	diffpair.add_ports(b_botl.get_ports_list(),prefix="bl_")
	diffpair.add_ports(a_botr.get_ports_list(),prefix="br_")
	diffpair.add_ports(source_routeE.get_ports_list(),prefix="source_routeE_")
	diffpair.add_ports(source_routeW.get_ports_list(),prefix="source_routeW_")
	diffpair.add_ports(drain_routeTR_BL.get_ports_list(),prefix="drain_routeTR_BL_")
	diffpair.add_ports(drain_routeTL_BR.get_ports_list(),prefix="drain_routeTL_BR_")
	diffpair.add_ports(MINUSgate_routeW.get_ports_list(),prefix="MINUSgateroute_W_")
	diffpair.add_ports(MINUSgate_routeE.get_ports_list(),prefix="MINUSgateroute_E_")
	diffpair.add_ports(PLUSgate_routeW.get_ports_list(),prefix="PLUSgateroute_W_")
	diffpair.add_ports(PLUSgate_routeE.get_ports_list(),prefix="PLUSgateroute_E_")
	diffpair.add_padding(layers=(pdk.get_glayer(well),), default=0)

	component = component_snap_to_grid(rename_ports_by_orientation(diffpair))

	component.info['netlist'] = diff_pair_netlist(fetL, fetR)
	return component



@cell
def diff_pair_generic(
	pdk: MappedPDK,
	width: float = 3,
	fingers: int = 4,
	length: Optional[float] = None,
	n_or_p_fet: bool = True,
	plus_minus_seperation: float = 0,
	rmult: int = 1,
	dummy: Union[bool, tuple[bool, bool]] = True,
	substrate_tap: bool=True
) -> Component:
	diffpair = common_centroid_ab_ba(pdk,width,fingers,length,n_or_p_fet,rmult,dummy,substrate_tap)
	diffpair << smart_route(pdk,diffpair.ports["A_source_E"],diffpair.ports["B_source_E"],diffpair, diffpair)
	return diffpair


# Create and evaluate a differential pair instance
if __name__ == "__main__":
	# this is the old eval code

    # Create differential pair with labels
	comp =diff_pair(sky130)
	# comp.pprint_ports()
	comp=sky130_add_df_labels(comp)
	comp.name = "DiffPair"
	comp.show()
	#print(comp.info['netlist'].generate_netlist())
	print("...Running DRC...")
	drc_result = sky130.drc_magic(comp, "DiffPair")
	## Klayout DRC
	#drc_result = sky130.drc(comp)\n
	time.sleep(5)
	print("...Running LVS...")
	lvs_res=sky130.lvs_netgen(comp, "DiffPair")
	#print("...Saving GDS...")
	#comp.write_gds('out_Diffpair.gds')

	# This is the new eval code
	dp = sky130_add_diff_pair_labels(
		diff_pair(
			pdk=sky130, 
			width=3, 
			fingers=4, 
			length=None,
			n_or_p_fet=True,
			plus_minus_seperation=0,
			rmult=1,
			dummy=True,
			substrate_tap=True
		)
	)
	# Show the layout
	dp.show()
	dp.name = "diff_pair"
	# Write GDS file
	dp_gds = dp.write_gds("diff_pair.gds")
	# Run evaluation if available
	if run_evaluation is not None:
		result = run_evaluation("diff_pair.gds", dp.name, dp)
		print(result)
	else:
		print("Evaluation skipped - evaluator_wrapper not available")
