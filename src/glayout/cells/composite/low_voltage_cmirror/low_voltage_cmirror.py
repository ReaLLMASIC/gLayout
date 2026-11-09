from glayout.pdk.mappedpdk import MappedPDK
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
from glayout.backend import Component, ComponentReference, cell, rectangle
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.util.comp_utils import evaluate_bbox, prec_center, align_comp_to_port, prec_ref_center
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.util.port_utils import rename_ports_by_orientation
from glayout.routing.straight_route import straight_route
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import add_ports_perimeter
from glayout.spice.netlist import Netlist
from glayout.cells.elementary.FVF.fvf import fvf_netlist, flipped_voltage_follower  # Import from local ATLAS fvf.py
from glayout.primitives.via_gen import via_stack
from typing import Optional
from glayout.verification.evaluator_wrapper import run_evaluation


def add_lvcm_labels(lvcm_in: Component,
                pdk: MappedPDK
                ) -> Component:

    lvcm_in.unlock()

    # list that will contain all port/comp info
    move_info = list()

    # IBIAS1, IBIAS2 — top-met of the bias-via stacks (glayout met3).
    ibias1label = rectangle(layer=pdk.get_glayer("met3_pin"), size=(0.5,0.5), centered=True).copy()
    ibias1label.add_label(text="IBIAS1", layer=pdk.get_glayer("met3_label"))
    move_info.append((ibias1label, lvcm_in.ports["M_1_A_drain_bottom_met_N"], None))

    ibias2label = rectangle(layer=pdk.get_glayer("met3_pin"), size=(0.5,0.5), centered=True).copy()
    ibias2label.add_label(text="IBIAS2", layer=pdk.get_glayer("met3_label"))
    move_info.append((ibias2label, lvcm_in.ports["M_2_A_drain_bottom_met_N"], None))

    # IOUT1, IOUT2 — drain of the output-branch top fets (met2).
    output1label = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.27,0.27), centered=True).copy()
    output1label.add_label(text="IOUT1", layer=pdk.get_glayer("met2_label"))
    move_info.append((output1label, lvcm_in.ports["M_3_A_multiplier_0_drain_N"], None))

    output2label = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.27,0.27), centered=True).copy()
    output2label.add_label(text="IOUT2", layer=pdk.get_glayer("met2_label"))
    move_info.append((output2label, lvcm_in.ports["M_4_A_multiplier_0_drain_N"], None))

    # GND — stamp on EVERY welltie ring's metal so klayout's gf180 deck
    # binds all the per-fet substrate-tap pwells into a single GND net.
    # Without this, the cascoded bottom fets (fet_1, fet_3) end up with
    # their source on a per-fet floating net (the unlabeled welltie metal),
    # and the schematic's `S=GND` mapping doesn't match the layout. Also
    # GND-stamps the FVF sub-cells' tie rings so their dummies' G/S/D
    # (which physically merge into the welltie metal via parallel
    # diffusion contacts) likewise end up named GND.
    _gnd_tie_ports = [
        "M_1_A_tie_N_top_met_N",   # bias_fvf input fet welltie
        "M_1_B_tie_N_top_met_N",   # bias_fvf feedback fet welltie (was the only one before)
        "M_2_A_tie_N_top_met_N",   # cascode_fvf input fet welltie
        "M_2_B_tie_N_top_met_N",   # cascode_fvf feedback fet welltie
        "M_3_A_tie_N_top_met_N",   # out1 top fet welltie
        "M_3_B_tie_N_top_met_N",   # out1 bot fet welltie
        "M_4_A_tie_N_top_met_N",   # out2 top fet welltie
        "M_4_B_tie_N_top_met_N",   # out2 bot fet welltie
    ]
    for _portname in _gnd_tie_ports:
        if _portname not in lvcm_in.ports:
            continue
        gndlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.5,0.5), centered=True).copy()
        gndlabel.add_label(text="GND", layer=pdk.get_glayer("met2_label"))
        # ('c','c') keeps the label box overlapping the welltie metal
        # regardless of port orientation.
        move_info.append((gndlabel, lvcm_in.ports[_portname], ('c','c')))

    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        lvcm_in.add(compref)
    return lvcm_in.flatten()

def low_voltage_cmirr_netlist(bias_fvf: Component, cascode_fvf: Component, fet_1_ref: ComponentReference, fet_2_ref: ComponentReference, fet_3_ref: ComponentReference, fet_4_ref: ComponentReference) -> Netlist:

        netlist = Netlist(circuit_name='Low_voltage_current_mirror', nodes=['IBIAS1', 'IBIAS2', 'GND', 'IOUT1', 'IOUT2'])
        # Map the 4 output-branch fets' DUM ports to GND on both PDKs. On
        # sky130 magic absorbs floating dummies into the bulk anyway. On
        # gf180 add_lvcm_labels now stamps GND on every fet's welltie
        # ring (M_3_*, M_4_*), so klayout extracts the dummies' diffusion
        # nets as GND too — DUM=GND keeps schematic and layout in sync.
        dum = 'GND'
        # Use netlist_obj for hierarchical netlist building
        netlist.connect_netlist(bias_fvf.info['netlist_obj'], [('VIN','IBIAS1'),('VBULK','GND'),('Ib','IBIAS1'),('VOUT','local_net_1')])
        netlist.connect_netlist(cascode_fvf.info['netlist_obj'], [('VIN','IBIAS1'),('VBULK','GND'),('Ib', 'IBIAS2'),('VOUT','local_net_2')])
        fet_1A_ref=netlist.connect_netlist(fet_2_ref.info['netlist'], [('D', 'IOUT1'),('G','IBIAS1'),('B','GND'),('DUM', dum)])
        fet_2A_ref=netlist.connect_netlist(fet_4_ref.info['netlist'], [('D', 'IOUT2'),('G','IBIAS1'),('B','GND'),('DUM', dum)])
        fet_1B_ref=netlist.connect_netlist(fet_1_ref.info['netlist'], [('G','IBIAS2'),('S', 'GND'),('B','GND'),('DUM', dum)])
        fet_2B_ref=netlist.connect_netlist(fet_3_ref.info['netlist'], [('G','IBIAS2'),('S', 'GND'),('B','GND'),('DUM', dum)])
        netlist.connect_subnets(
                fet_1A_ref,
                fet_1B_ref,
                [('S', 'D')]
                )
        netlist.connect_subnets(
                fet_2A_ref,
                fet_2B_ref,
                [('S', 'D')]
                )

        return netlist


   
@cell
def  low_voltage_cmirror(
        pdk: MappedPDK,
        width:  tuple[float,float] = (4.15,1.42),
        length: float = 2,
        fingers: tuple[int,int] = (2,1),
        multipliers: tuple[int,int] = (1,1),
        ) -> Component:
    """
    A low voltage N type current mirror. It has two input brnaches and two output branches. It consists of total 8 nfets, 7 of them have the same W/L. One nfet has width of w' = w/3(theoretcially)
    The default values are used to mirror 10uA.
    """
    #top level component
    top_level = Component("Low_voltage_N-type_current_mirror")

    # Suppress sub-cell pin labels for gf180 so the inner FVF VBULK/VIN/Ib/VOUT
    # labels don't leak into the LVCM GDS (klayout would extract them as extra
    # top-level pins, breaking LVS).
    import os as _os
    _prev_labels = _os.environ.get("GLAYOUT_NO_PIN_LABELS")
    _os.environ["GLAYOUT_NO_PIN_LABELS"] = "1"
    try:
        #input branch 2
        cascode_fvf = flipped_voltage_follower(pdk, width=(width[0],width[0]), length=(length,length), fingers=(fingers[0],fingers[0]), multipliers=(multipliers[0],multipliers[0]), with_dnwell=False)
        #input branch 1
        bias_fvf = flipped_voltage_follower(pdk, width=(width[0],width[1]), length=(length,length), fingers=(fingers[0],fingers[1]), multipliers=(multipliers[0],multipliers[1]), placement="vertical", with_dnwell=False)
    finally:
        if _prev_labels is None:
            _os.environ.pop("GLAYOUT_NO_PIN_LABELS", None)
        else:
            _os.environ["GLAYOUT_NO_PIN_LABELS"] = _prev_labels

    cascode_fvf_ref = prec_ref_center(cascode_fvf)
    top_level.add(cascode_fvf_ref)

    bias_fvf_ref = prec_ref_center(bias_fvf)
    bias_fvf_ref.movey(cascode_fvf_ref.ymin - 2 - (evaluate_bbox(bias_fvf)[1]/2))
    top_level.add(bias_fvf_ref)

    #creating fets for output branches
    fet_1 = nmos(pdk, width=width[0], fingers=fingers[0], multipliers=multipliers[0], with_dummy=True, with_dnwell=False,  with_substrate_tap=False, length=length)
    fet_1_ref = prec_ref_center(fet_1)
    fet_2_ref = prec_ref_center(fet_1) 
    fet_3_ref = prec_ref_center(fet_1)
    fet_4_ref = prec_ref_center(fet_1)

    # Use max(metal_sep, pwell_min_separation) so gf180 LVPWELL spacing rule
    # (LPW.2a/b: 0.86um) isn't violated by under-spaced subcells. sky130's
    # pwell self-rule is empty (raises NotImplementedError), so fall back to 0.
    try:
        _pwell_sep = pdk.get_grule("pwell").get("min_separation", 0)
    except NotImplementedError:
        _pwell_sep = 0
    _xclear = max(pdk.util_max_metal_seperation(), _pwell_sep)
    fet_1_ref.movex(cascode_fvf_ref.xmin - (evaluate_bbox(fet_1)[0]/2) - _xclear)
    fet_2_ref.movex(cascode_fvf_ref.xmin - (3*evaluate_bbox(fet_1)[0]/2) - 2*_xclear)
    fet_3_ref.movex(cascode_fvf_ref.xmax + (evaluate_bbox(fet_1)[0]/2) + _xclear)
    fet_4_ref.movex(cascode_fvf_ref.xmax + (3*evaluate_bbox(fet_1)[0]/2) + 2*_xclear)

    top_level.add(fet_1_ref)
    top_level.add(fet_2_ref)
    top_level.add(fet_3_ref)
    top_level.add(fet_4_ref)
 
    top_level << c_route(pdk, bias_fvf_ref.ports["A_multiplier_0_gate_E"], bias_fvf_ref.ports["B_gate_bottom_met_E"])
    top_level << c_route(pdk, cascode_fvf_ref.ports["A_multiplier_0_gate_W"], bias_fvf_ref.ports["A_multiplier_0_gate_W"])
    top_level << straight_route(pdk, cascode_fvf_ref.ports["B_gate_bottom_met_E"], fet_3_ref.ports["multiplier_0_gate_W"])
    
    #creating vias for routing
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    gate_1_via = top_level << viam2m3 
    gate_1_via.move(fet_1_ref.ports["multiplier_0_gate_W"].center).movex(-1)
    gate_2_via = top_level << viam2m3                                         
    gate_2_via.move(fet_2_ref.ports["multiplier_0_gate_W"].center).movex(-1)
    gate_3_via = top_level << viam2m3 
    gate_3_via.move(fet_3_ref.ports["multiplier_0_gate_E"].center).movex(1)
    gate_4_via = top_level << viam2m3 
    gate_4_via.move(fet_4_ref.ports["multiplier_0_gate_E"].center).movex(1)

    source_2_via = top_level << viam2m3
    drain_1_via = top_level << viam2m3
    source_2_via.move(fet_2_ref.ports["multiplier_0_source_E"].center).movex(1.5)
    drain_1_via.move(fet_1_ref.ports["multiplier_0_drain_W"].center).movex(-1)

    source_4_via = top_level << viam2m3
    drain_3_via = top_level << viam2m3
    source_4_via.move(fet_4_ref.ports["multiplier_0_source_W"].center).movex(-1)
    drain_3_via.move(fet_3_ref.ports["multiplier_0_drain_E"].center).movex(1.5)
    
    #routing
    top_level << straight_route(pdk, fet_2_ref.ports["multiplier_0_source_E"], source_2_via.ports["bottom_met_W"])
    top_level << straight_route(pdk, fet_1_ref.ports["multiplier_0_drain_W"], drain_1_via.ports["bottom_met_E"])
    top_level << straight_route(pdk, fet_4_ref.ports["multiplier_0_source_W"], source_4_via.ports["bottom_met_E"])
    top_level << straight_route(pdk, fet_3_ref.ports["multiplier_0_drain_E"], drain_3_via.ports["bottom_met_W"])
    top_level << c_route(pdk, source_2_via.ports["top_met_N"], drain_1_via.ports["top_met_N"], extension=0.5*evaluate_bbox(fet_1)[1], width1=0.32, width2=0.32, cwidth=0.32, e1glayer="met3", e2glayer="met3", cglayer="met2")
    top_level << c_route(pdk, source_4_via.ports["top_met_N"], drain_3_via.ports["top_met_N"], extension=0.5*evaluate_bbox(fet_1)[1], width1=0.32, width2=0.32, cwidth=0.32, e1glayer="met3", e2glayer="met3", cglayer="met2")
    top_level << c_route(pdk, bias_fvf_ref.ports["A_multiplier_0_gate_E"], gate_4_via.ports["bottom_met_E"], width1=0.32, width2=0.32, cwidth=0.32) 

 
    top_level << straight_route(pdk, fet_1_ref.ports["multiplier_0_gate_W"], gate_1_via.ports["bottom_met_E"])
    top_level << straight_route(pdk, fet_2_ref.ports["multiplier_0_gate_W"], gate_2_via.ports["bottom_met_E"])    
    top_level << straight_route(pdk, fet_3_ref.ports["multiplier_0_gate_E"], gate_3_via.ports["bottom_met_W"])
    top_level << straight_route(pdk, fet_4_ref.ports["multiplier_0_gate_E"], gate_4_via.ports["bottom_met_W"])

    # Spread the two south-going gate c_routes wider so their horizontal
    # met2 strokes respect gf180 M2.2a (0.28um). Bumping the offset from
    # ±0.6 to ±1.0 gives ~0.4um center-to-center spacing on top of the
    # 0.5um stroke width — clear of the rule on either PDK.
    top_level << c_route(pdk, gate_1_via.ports["top_met_S"], gate_3_via.ports["top_met_S"], extension=(1.2*width[0]+1.0), cglayer='met2')
    top_level << c_route(pdk, gate_2_via.ports["top_met_S"], gate_4_via.ports["top_met_S"], extension=(1.2*width[0]-1.0), cglayer='met2')
    
    # Tie source to substrate. The via_stack(met1,met2) the route drops at
    # edge1=source_W has its bottom layer (li1) at 0.17um (mcon-sized, no
    # enclosure padding); the default 'r','c' alignment lands the mcon 0.06um
    # to the LEFT of the fet's existing gate-top mcon, tripping sky130 ct.1.
    # Aligning by the via's met1 (sky130) layer instead — which is 0.29um wide
    # because of the via1↔met1 enclosure rule — shifts the mcon by exactly the
    # 0.06um needed to coincide with the fet's gate mcon (they merge into a
    # single 0.17x0.17 polygon, no violation).
    _tie_w = max(0.2, pdk.get_grule("met1")["min_width"])
    for fet_ref in (fet_1_ref, fet_3_ref):
        top_level << straight_route(
            pdk,
            fet_ref.ports["multiplier_0_source_W"],
            fet_ref.ports["tie_W_top_met_W"],
            glayer1='met1', width=_tie_w,
            via1_alignment_layer='met2',
        )
    

    top_level.add_ports(bias_fvf_ref.get_ports_list(), prefix="M_1_")
    top_level.add_ports(cascode_fvf_ref.get_ports_list(), prefix="M_2_")
    top_level.add_ports(fet_1_ref.get_ports_list(), prefix="M_3_B_")
    top_level.add_ports(fet_2_ref.get_ports_list(), prefix="M_3_A_")
    top_level.add_ports(fet_3_ref.get_ports_list(), prefix="M_4_B_")
    top_level.add_ports(fet_4_ref.get_ports_list(), prefix="M_4_A_")
    
    component = component_snap_to_grid(rename_ports_by_orientation(top_level))
    netlist_obj = low_voltage_cmirr_netlist(bias_fvf, cascode_fvf, fet_1_ref, fet_2_ref, fet_3_ref, fet_4_ref)
    component.info['netlist'] = netlist_obj.generate_netlist()

    # gf180 LVS uses klayout's official deck which strictly requires named
    # pin labels on met*_label layers. sky130 magic+netgen tolerates missing
    # labels, so we only stamp them for gf180.
    import os
    if pdk.name.lower() in ("gf180", "openrpdk28") and not os.environ.get("GLAYOUT_NO_PIN_LABELS"):
        try:
            component = add_lvcm_labels(component, pdk)
        except KeyError:
            pass

    return component

if __name__=="__main__":
    #low_voltage_current_mirror = low_voltage_current_mirror(sky130_mapped_pdk)
    low_voltage_current_mirror = add_lvcm_labels(low_voltage_cmirror(sky130_mapped_pdk),sky130_mapped_pdk)
    low_voltage_current_mirror.show()
    low_voltage_current_mirror.name = "Low_voltage_current_mirror"
    #magic_drc_result = sky130_mapped_pdk.drc_magic(low_voltage_current_mirror, low_voltage_current_mirror.name)
    #netgen_lvs_result = sky130_mapped_pdk.lvs_netgen(low_voltage_current_mirror, low_voltage_current_mirror.name)
    low_voltage_current_mirror_gds = low_voltage_current_mirror.write_gds("low_voltage_current_mirror.gds")
    res = run_evaluation("low_voltage_current_mirror.gds", low_voltage_current_mirror.name, low_voltage_current_mirror)