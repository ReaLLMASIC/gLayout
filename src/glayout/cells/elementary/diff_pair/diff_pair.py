from typing import Optional, Union

from glayout.backend import Component, cell, copy, rectangle, route_quad
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
from glayout.routing.c_route import c_route
from glayout.routing.smart_route import smart_route
from glayout.routing.straight_route import straight_route
from glayout.spice import Netlist
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
try:
    from glayout.verification.evaluator_wrapper import run_evaluation
except ImportError:
    print("Warning: evaluator_wrapper not found. Evaluation will be skipped.")
    run_evaluation = None


def add_df_labels(df_in: Component,
                        pdk: MappedPDK
                         ) -> Component:
	
	df_in.unlock()
	def _pin(met: str, text: str, size: float):
		"""Label marker sized to the routable metal's minimum width.

		The marker is aligned centre-to-centre on its port so it lands inside
		the metal the router already placed, instead of tangent to its edge.
		A marker that only carries the label layer floats: the extractor finds
		no conductor under the text, the net comes out unnamed, and LVS reports
		the pin as missing from the layout.
		"""
		min_w = pdk.get_grule(met)["min_width"]
		side = max(size, min_w)
		marker = rectangle(layer=pdk.get_glayer(met + "_label"), size=(side, side), centered=True).copy()
		marker.add_label(text=text, layer=pdk.get_glayer(met + "_label"))
		return marker
    # list that will contain all port/comp info
	move_info = list()
    # create labels and append to info list
    # vtail
	vtaillabel = _pin("met2", "VTAIL", 0.27)
	move_info.append((vtaillabel,df_in.ports["bl_multiplier_0_source_S"],None))
    
    # vdd1
	vdd1label = _pin("met2", "VDD1", 0.27)
	move_info.append((vdd1label,df_in.ports["tl_multiplier_0_drain_N"],None))
    
    # vdd2
	vdd2label = _pin("met2", "VDD2", 0.27)
	move_info.append((vdd2label,df_in.ports["tr_multiplier_0_drain_N"],None))
    
    # VB
	vblabel = _pin("met1", "B", 0.5)
	move_info.append((vblabel,df_in.ports["tap_N_top_met_S"], None))
    
    # VP
	vplabel = _pin("met2", "VP", 0.27)
	move_info.append((vplabel,df_in.ports["br_multiplier_0_gate_S"], None))
    
    # VN
	vnlabel = _pin("met2", "VN", 0.27)
	move_info.append((vnlabel,df_in.ports["bl_multiplier_0_gate_S"], None))

    # move everything to position
	for comp, prt, alignment in move_info:
		alignment = ('c','c') if alignment is None else alignment
		compref = align_comp_to_port(comp, prt, alignment=alignment)
		df_in.add(compref)
	return df_in.flatten() 

def diff_pair_netlist(fetL: Component, fetR: Component, pdk: Optional[MappedPDK] = None, dum_net: Optional[str] = None, substrate_tap: bool = True) -> Netlist:
	diff_pair_netlist = Netlist(circuit_name='DIFF_PAIR', nodes=['VP', 'VN', 'VDD1', 'VDD2', 'VTAIL', 'B'])

	# The physical layout uses an AB/BA common-centroid placement with four
	# mirrored device references (two copies of the left device and two copies of
	# the right device). Model that explicitly in the reference netlist so LVS
	# compares against the same effective device count/width.
	#
	# DUM maps to the dummies' G/S/D net, and which net that is follows the
	# layout rather than the PDK. When a substrate tap is placed, the four
	# dummies are routed to the tap ring (the
	# `multiplier_0_dummy_*_gsdcon_top_met_W` -> `tap_*` routes below), so both
	# extractors report them on the bulk: gf180 klayout merges the four parallel
	# fingers into a single B-tied device, and sky130 magic+netgen absorbs them
	# into the bulk during parallel-device merging. Declaring a separate `dum`
	# net in that case adds a net the layout does not have and trips LVS.
	# Without the tap ring there is nothing tying them down, so they stay on a
	# floating subckt-level net.
	# `dum_net` lets a caller override this when the surrounding layout context
	# forces the dummies onto a different net than the standalone extraction.
	if dum_net is None:
		dum_net = 'B' if substrate_tap else 'dum'
	for net, fet in (('VDD1', fetL), ('VDD1', fetL), ('VDD2', fetR), ('VDD2', fetR)):
		gate = 'VP' if net == 'VDD1' else 'VN'
		diff_pair_netlist.connect_netlist(
			fet.info['netlist'],
			[('D', net), ('G', gate), ('S', 'VTAIL'), ('B', 'B'), ('DUM', dum_net)],
		)
	return diff_pair_netlist


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
	substrate_tap: bool=True,
	dum_net: Optional[str] = None,
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
	a_botr = a_botr.mirror_y()
	a_botr.movey(0-0.5-fetL.ymax-min_spacing_y/2).movex(fetL.xmax+min_spacing_x/2)
	b_botl = (diffpair << fetL)
	b_botl = b_botl.mirror_y()
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
	source_routeE = diffpair << c_route(pdk, b_topr.ports["multiplier_0_source_E"], a_botr.ports["multiplier_0_source_E"],extension=sextension, viaoffset=False)
	source_routeW = diffpair << c_route(pdk, a_topl.ports["multiplier_0_source_W"], b_botl.ports["multiplier_0_source_W"],extension=sextension, viaoffset=False)
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
	# Add an rmult-scaled margin so the drain c-bar clears the source c-bar
	# even at higher rmult (where both bars get wider). The original
	# `+ metal_space` left only 0.05um at rmult=2 and 0.1um at rmult=3 on
	# gf180 (M3.2a slivers); scaling with rmult keeps a full met3 spacing.
	dextension = source_routeE.xmax - b_topr.ports["multiplier_0_drain_E"].center[0] + (1 + rmult) * metal_space
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

	component.info['netlist'] = diff_pair_netlist(fetL, fetR, pdk=pdk, dum_net=dum_net, substrate_tap=substrate_tap)

	# gf180 LVS uses klayout's official deck which strictly requires named
	# pin labels on met*_label layers — without them, klayout extracts the
	# cell with only an implicit substrate port and LVS fails. sky130 LVS
	# via magic+netgen tolerates missing labels, so only emit the labels
	# for gf180. The B (bulk) label needs `substrate_tap=True` since it
	# anchors on `tap_N_top_met_S`, which only exists when the diffpair's
	# tap ring is drawn. Composite cells suppress this via GLAYOUT_NO_PIN_LABELS
	# so inner labels don't leak into the parent cell's GDS.
	import os
	if pdk.name.lower() == "gf180" and substrate_tap and not os.environ.get("GLAYOUT_NO_PIN_LABELS"):
		component = add_df_labels(component, pdk)
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

if __name__=="__main__":
	diff_pair = add_df_labels(diff_pair(sky130_mapped_pdk),sky130_mapped_pdk)
	#diff_pair = diff_pair(sky130_mapped_pdk)
	diff_pair.show()
	diff_pair.name = "DIFF_PAIR"
	#magic_drc_result = sky130_mapped_pdk.drc_magic(diff_pair, diff_pair.name)
	#netgen_lvs_result = sky130_mapped_pdk.lvs_netgen(diff_pair, diff_pair.name)
	diff_pair_gds = diff_pair.write_gds("diff_pair.gds")
	res = run_evaluation("diff_pair.gds", diff_pair.name, diff_pair)
