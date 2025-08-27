from glayout import MappedPDK, sky130, gf180
from glayout import nmos, pmos, multiplier, tapring, via_stack, via_array

from glayout.spice.netlist import Netlist
from glayout.routing import c_route, L_route, straight_route

from gdsfactory.cell import cell
from gdsfactory.component import Component, copy
from gdsfactory.components.rectangle import rectangle
from gdsfactory.routing.route_quad import route_quad
from gdsfactory.routing.route_sharp import route_sharp

from glayout.util.comp_utils import (
    align_comp_to_port,
    evaluate_bbox,
    movex,
    movey,
    prec_ref_center,
    prec_array,
)
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

from gdsfactory.functions import transformed
from gdsfactory.components import text_freetype
from gdsfactory.components.rectangular_ring import rectangular_ring
from typing import Optional, Union, Literal
import time
import copy

# Import custom functions (Matrix generator)
from custom_functions import macro_two_transistor_placement_Onchip
from custom_functions import pin_label_creation
from custom_functions import center_component_with_ports
from custom_functions import filtrar_puertos
from primitives import diode, transistor
from custom_functions import interdigitado_placement_Onchip
from custom_functions import interdigitado_cascode_placement_Onchip
from custom_functions import layer_pin_and_label, Boundary_layer, rails
import gdsfactory as gf

def Component_Biasing(pdk: MappedPDK,
                       devices_info, 
                       arrays_info,
                        width_route: float = None) -> Component:
    """
    This function creates transistors needed for the biasing generator
    """
    # Width configuration
    if width_route == None or width_route == 0:
        separation_interdigitado = 0
        width_horizontal = evaluate_bbox(via_stack(pdk,'met2','met3'))[1]
    else:
        separation_interdigitado = width_route
        width_horizontal = width_route
    # Create the component
    min_separation_met3 = pdk.get_grule('met3')['min_separation']
    biasing = Component()
    pmirrors = interdigitado_placement_Onchip(pdk, output='via', common_route=(False, True), output_separation=(separation_interdigitado, 2*separation_interdigitado + min_separation_met3), deviceA_and_B='pfet', width=devices_info[2]['width'], length=devices_info[2]['length'], fingers=devices_info[2]['fingers'], with_dummy=True, array=arrays_info[2], with_tie=True, with_lvt_layer=devices_info[2]['lvt'])
    transistor_vref = interdigitado_placement_Onchip(pdk, output='via', output_separation=(separation_interdigitado, separation_interdigitado), deviceA_and_B=devices_info[0]['type'], width=devices_info[0]['width'], length=devices_info[0]['length'], fingers=devices_info[0]['fingers'], 
                                                     with_dummy=devices_info[0]['with_dummy'], array=arrays_info[0], with_tie=devices_info[0]['with_tie'], with_substrate_tap=devices_info[0]['with_substrate_tap'], with_lvt_layer=devices_info[0]['lvt'])
    
    transistor_p_18_12 = interdigitado_placement_Onchip(pdk, output='via', output_separation=(separation_interdigitado, separation_interdigitado), deviceA_and_B=devices_info[1]['type'], width=devices_info[1]['width'], length=devices_info[1]['length'], fingers=devices_info[1]['fingers'],
                                                     with_dummy=devices_info[1]['with_dummy'], array=arrays_info[1], with_tie=devices_info[1]['with_tie'], with_substrate_tap=devices_info[1]['with_substrate_tap'], with_lvt_layer=devices_info[1]['lvt'])
    transistors_p_13_14 = interdigitado_placement_Onchip(pdk, output='via', output_separation=(separation_interdigitado, separation_interdigitado), gate_common=False, deviceA_and_B=devices_info[1]['type'], width=devices_info[1]['width'], length=devices_info[1]['length'], fingers=devices_info[1]['fingers'],
                                                     with_dummy=devices_info[1]['with_dummy'], array=arrays_info[3], with_tie=devices_info[1]['with_tie'], with_substrate_tap=devices_info[1]['with_substrate_tap'], with_lvt_layer=devices_info[1]['lvt'])

    #Add the components to the biasing component
    pmirrors_ref = biasing << pmirrors 
    m1_m15 = biasing << transistor_vref
    m2_m16 = biasing << transistor_vref
    m12_m18 = biasing << transistor_p_18_12
    m13_m14 = biasing << transistors_p_13_14
    #x reflection
    pmirrors_ref.mirror(p1=(0,0), p2=(1,0))
    m1_m15.mirror(p1=(0,0), p2=(1,0))
    m2_m16.mirror(p1=(0,0), p2=(1,0))
    m12_m18.mirror(p1=(0,0), p2=(1,0))
    m13_m14.mirror(p1=(0,0), p2=(1,0))

    #Components size
    pmirrors_size = evaluate_bbox(pmirrors_ref)
    m1_m15_size = evaluate_bbox(m1_m15)
    m2_m16_size = evaluate_bbox(m2_m16)
    m12_m18_size = evaluate_bbox(m12_m18)
    m13_m14_size = evaluate_bbox(m13_m14)
    #min separation between components
    min_separation = pdk.get_grule('nwell')['min_separation']
    size_via = evaluate_bbox(via_stack(pdk, 'met2', 'met3'))
    #amount of movement
    pmirrors_movement = [0]
    m1_m15_movement = [(pmirrors_size[0] + m1_m15_size[0])/2 + min_separation]
    m2_m16_movement = [(pmirrors_size[0] + m2_m16_size[0])/2 + min_separation]
    m12_m18_movement = [(m1_m15_size[0] + m12_m18_size[0])/2 + m1_m15_movement[0] + min_separation]
    m13_m14_movement = [(m12_m18_size[0] + m13_m14_size[0])/2 + m12_m18_movement[0] + min_separation]
    #move the componentes
    pmirrors_ref.movex(pdk.snap_to_2xgrid(pmirrors_movement[0]))
    m1_m15.movex(pdk.snap_to_2xgrid(m1_m15_movement[0]))
    m2_m16.movex(pdk.snap_to_2xgrid(-m2_m16_movement[0]))
    m12_m18.movex(pdk.snap_to_2xgrid(m12_m18_movement[0]))
    m13_m14.movex(pdk.snap_to_2xgrid(m13_m14_movement[0])).movey(pdk.snap_to_2xgrid(size_via[1]))
    #Total size
    size_biasing = evaluate_bbox(biasing)
    #Extension
    size_via = evaluate_bbox(via_stack(pdk, 'met2', 'met3'))[1] + pdk.get_grule("met3")["min_separation"]*2
    #Vias
    via_3_4 = via_stack(pdk, 'met3', 'met4')
    #Routing the components
    #Pmirrors
    #Source routes

    VDD1 = biasing << straight_route(pdk, pmirrors_ref.ports['source_1_2_0_W'], pmirrors_ref.ports['source_3_3_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width = width_horizontal)
    via_pmirror1 = biasing << via_3_4
    via_pmirror2 = biasing << via_3_4
    via_pmirror3 = biasing << via_3_4

    via_pmirror1.movex(pdk.snap_to_2xgrid(pmirrors_ref.ports['source_1_2_0_N'].center[0])).movey(pdk.snap_to_2xgrid(pmirrors_ref.ports['source_1_2_0_E'].center[1]))
    via_pmirror2.movex(pdk.snap_to_2xgrid(pmirrors_ref.ports['source_2_1_0_N'].center[0])).movey(pdk.snap_to_2xgrid(pmirrors_ref.ports['source_2_1_0_E'].center[1]))
    via_pmirror3.movex(pdk.snap_to_2xgrid(pmirrors_ref.ports['source_3_3_0_N'].center[0])).movey(pdk.snap_to_2xgrid(pmirrors_ref.ports['source_3_3_0_E'].center[1]))
    biasing << straight_route(pdk, via_pmirror1.ports['top_met_W'], via_pmirror3.ports['top_met_E'], width = width_horizontal)

    biasing << c_route(pdk, pmirrors_ref.ports['source_3_3_0_S'], m12_m18.ports['source_2_2_0_S'], cglayer='met2', cwidth = width_horizontal)

    #Bulk route
    biasing << straight_route(pdk, pmirrors_ref.ports['source_2_1_0_S'], pmirrors_ref.ports['bulk_down_N'])
    #Drain route
    biasing << L_route(pdk, pmirrors_ref.ports['drain_2_1_0_E'], pmirrors_ref.ports['gate1_S'], hglayer='met2', vglayer='met3', vwidth = width_horizontal)
    biasing << L_route(pdk, pmirrors_ref.ports['drain_2_1_0_E'], pmirrors_ref.ports['gate2_S'], hglayer='met2', vglayer='met3', vwidth = width_horizontal)
    biasing << straight_route(pdk, pmirrors_ref.ports['drain_1_2_0_E'], m2_m16.ports['drain_2_2_0_W'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width = width_horizontal)
    biasing << straight_route(pdk, pmirrors_ref.ports['drain_2_1_0_W'], m1_m15.ports['drain_1_1_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width = width_horizontal)
    
    ############################################
    #Falta la conexión con transistores 3 5 y 7
    ############################################
    
    #M1-M15
    #Bulk route
    biasing << straight_route(pdk, m1_m15.ports['source_2_2_0_S'], m1_m15.ports['bulk_down_N'])
    #Drain route
    biasing << L_route(pdk, m1_m15.ports['source_1_1_0_E'], m1_m15.ports['drain_2_2_0_N'], hglayer='met2')
    #Source route
    VSS1 = biasing << c_route(pdk, m1_m15.ports['source_2_2_0_S'], m2_m16.ports['source_1_1_0_S'], cglayer='met4', extension=size_via+width_horizontal, cwidth = width_horizontal)

    #M2-16
    #Gate route
    biasing << L_route(pdk, m2_m16.ports['gate2_S'], m2_m16.ports['drain_2_2_0_E'], vglayer='met3', hglayer='met2', vwidth = width_horizontal)
    biasing << L_route(pdk, m2_m16.ports['gate1_S'], m2_m16.ports['drain_2_2_0_E'], vglayer='met3', hglayer='met2', vwidth = width_horizontal)

    #Bulk route
    biasing << straight_route(pdk, m2_m16.ports['source_1_1_0_S'], m2_m16.ports['bulk_down_N'])
    #drain route
    biasing << L_route(pdk, m2_m16.ports['source_2_2_0_S'], m2_m16.ports['drain_1_1_0_W'], hglayer='met2', vwidth = width_horizontal)
    
    ############################################
    #Falta la conexión con transistores 3 5 y 7
    ############################################

    #M12-M18
    #Source route
    if width_route == None or width_route == 0:
        biasing << straight_route(pdk, m13_m14.ports['source_5_1_0_W'], m12_m18.ports['source_2_2_0_W'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width = width_horizontal)
    else:
        biasing << L_route(pdk, m13_m14.ports['source_5_1_0_E'], m12_m18.ports['source_2_2_0_S'], vglayer='met3', hglayer='met2', vwidth = 0.75*width_horizontal)

    #Bulk route
    biasing << straight_route(pdk, m12_m18.ports['source_2_2_0_S'], m12_m18.ports['bulk_down_N'])
    #Gate route
    biasing << L_route(pdk, m12_m18.ports['gate1_S'], m12_m18.ports['drain_1_1_0_W'], vglayer='met3', hglayer='met2', vwidth = width_horizontal)
    biasing << L_route(pdk, m12_m18.ports['gate2_S'], m12_m18.ports['drain_1_1_0_W'], vglayer='met3', hglayer='met2', vwidth = width_horizontal)
    #drain route
    biasing << L_route(pdk, m12_m18.ports['drain_2_2_0_E'], m12_m18.ports['source_1_1_0_S'], hglayer='met2')
    ############################################
    #Falta la conexión con transistores 3 5 y 7
    ############################################

    #M13-M14
    #Bulk route
    biasing << straight_route(pdk, m13_m14.ports['source_1_1_0_S'], m12_m18.ports['bulk_down_S'], via2_alignment_layer='met2')
    biasing << straight_route(pdk, m13_m14.ports['source_3_1_0_S'], m12_m18.ports['bulk_down_S'], via2_alignment_layer='met2')
    biasing << straight_route(pdk, m13_m14.ports['source_5_1_0_S'], m12_m18.ports['bulk_down_S'], via2_alignment_layer='met2')
    #Common route
    biasing << straight_route(pdk, m13_m14.ports['source_2_2_0_W'], m13_m14.ports['source_4_2_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width = width_horizontal)
    VDD2 = biasing << straight_route(pdk, m13_m14.ports['source_1_1_0_W'], m13_m14.ports['source_5_1_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width = width_horizontal)
    via_m13_1 = biasing << via_3_4
    via_m13_2 = biasing << via_3_4
    via_m13_3 = biasing << via_3_4
    via_m13_1.movex(pdk.snap_to_2xgrid(m13_m14.ports['source_1_1_0_N'].center[0])).movey(pdk.snap_to_2xgrid(m13_m14.ports['source_1_1_0_E'].center[1]))
    via_m13_2.movex(pdk.snap_to_2xgrid(m13_m14.ports['source_3_1_0_N'].center[0])).movey(pdk.snap_to_2xgrid(m13_m14.ports['source_3_1_0_E'].center[1]))
    via_m13_3.movex(pdk.snap_to_2xgrid(m13_m14.ports['source_5_1_0_N'].center[0])).movey(pdk.snap_to_2xgrid(m13_m14.ports['source_5_1_0_E'].center[1]))
    biasing << straight_route(pdk, via_m13_1.ports['top_met_W'], via_m13_3.ports['top_met_E'], width = width_horizontal)
    
    biasing << straight_route(pdk, m13_m14.ports['drain_1_1_0_W'], m13_m14.ports['drain_5_1_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width = width_horizontal)
    biasing << straight_route(pdk, m13_m14.ports['drain_2_2_0_W'], m13_m14.ports['drain_4_2_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width = width_horizontal)
    #drain route
    biasing << L_route(pdk, m13_m14.ports['source_2_2_0_S'], m13_m14.ports['drain_1_1_0_E'], hglayer='met2', vwidth = width_horizontal)
    biasing << L_route(pdk, m13_m14.ports['source_4_2_0_S'], m13_m14.ports['drain_1_1_0_E'], hglayer='met2', vwidth = width_horizontal)
    #gate route
    biasing << straight_route(pdk, m13_m14.ports['1_1_gate_W'], m13_m14.ports['5_1_gate_E'])
    biasing << L_route(pdk, m13_m14.ports['drain_2_2_0_S'], m13_m14.ports['1_1_gate_W'])
    biasing << L_route(pdk, m13_m14.ports['drain_4_2_0_S'], m13_m14.ports['1_1_gate_W'])
    biasing << L_route(pdk, m13_m14.ports['4_2_gate_W'], m12_m18.ports['gate2_N'])

    ############################################
    #Falta la conexión con transistores 3 5 y 7 y puentear los gates comunes
    ############################################
    min_separation = pdk.get_grule('met3')['min_separation']

    #input port
    via_ref = via_stack(pdk, 'met2', 'met3')
    
    V_ref = biasing << via_ref
    align_comp_to_port(V_ref, m1_m15.ports['source_2_2_0_S'])
    V_ref.movey(pdk.snap_to_2xgrid(size_via+2*min_separation+2*width_horizontal)).movex(pdk.snap_to_2xgrid(-evaluate_bbox(m1_m15)[0]/4))
    biasing << L_route(pdk, m1_m15.ports['gate1_N'], V_ref.ports['bottom_met_E'], vwidth = width_horizontal)
    biasing << L_route(pdk, m1_m15.ports['gate2_N'], V_ref.ports['bottom_met_W'], vwidth = width_horizontal)

    V_dd = biasing << via_ref
    align_comp_to_port(V_dd, m13_m14.ports['source_5_1_0_W'])
    V_dd.movex(pdk.snap_to_2xgrid(evaluate_bbox(m13_m14)[0]/5))
    biasing << straight_route(pdk, m13_m14.ports['source_5_1_0_W'], V_dd.ports['bottom_met_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width = width_horizontal)

    #Output port
    V_biasp = biasing << via_ref
    V_biasp.movex(pdk.snap_to_2xgrid(pmirrors_ref.ports['drain_2_1_0_S'].center[0])).movey(pdk.snap_to_2xgrid(-size_biasing[1]/2 - evaluate_bbox(via_ref)[1] - min_separation))
    biasing << straight_route(pdk, pmirrors_ref.ports['drain_2_1_0_S'], V_biasp['top_met_S'])

    V_biasp2 = biasing << via_ref
    align_comp_to_port(V_biasp2, m13_m14.ports['4_2_gate_E'])
    V_biasp2.movex(pdk.snap_to_2xgrid(2*evaluate_bbox(m1_m15)[0]/7))
    biasing << straight_route(pdk, m13_m14.ports['4_2_gate_E'], V_biasp2['bottom_met_E'])

    #Add the ports to the component
    biasing.add_ports(pmirrors_ref.ports, prefix='pmirror_')
    biasing.add_ports(m1_m15.ports, prefix='m1_')
    biasing.add_ports(m2_m16.ports, prefix='m2_')
    biasing.add_ports(m12_m18.ports, prefix='m12_')
    biasing.add_ports(m13_m14.ports, prefix='m13_')
    biasing.add_ports(V_ref.ports, prefix = 'Vref_')
    biasing.add_ports(V_dd.ports, prefix = 'Vdd_')
    biasing.add_ports(V_biasp.ports, prefix = 'VbiasP1_')
    biasing.add_ports(V_biasp2.ports, prefix = 'VbiasP2_')

    biasing.add_ports(VDD1.ports, prefix = 'VDD1_')
    biasing.add_ports(VDD2.ports, prefix = 'VDD2_')
    biasing.add_ports(VSS1.ports, prefix = 'VSS1_')

    #Center the component
    component_centered = center_component_with_ports(biasing)

    #component_centered = component_centered.flatten()
    return component_centered

def Biasing_generator(pdk, 
                      devices_info, 
                      arrays_info, 
                      width_route: float = None) -> Component:
    """
    This function creates a biasing circuit using the MappedPDK and the custom functions
    """
    # Width configuration
    if width_route == None or width_route == 0:
        separation_interdigitado = 0
        width_horizontal = evaluate_bbox(via_stack(pdk,'met2','met3'))[1]
    else:
        separation_interdigitado = width_route
        width_horizontal = width_route
    # Division devices info
    devices_info_top = [devices_info[0], devices_info[1], devices_info[2]]
    devices_info_ntop = [devices_info[3]]
    devices_info_nbot = [devices_info[4]]
    arrays_info_top = [arrays_info[0], arrays_info[1], arrays_info[2], arrays_info[3]]   
    array_nmirrors_top = arrays_info[4]
    array_nmirrors_bot = arrays_info[5]
    min_separation_met3 = pdk.get_grule('met3')['min_separation']
    # Create the component
    biasing = Component()

    nmirrors_top = interdigitado_placement_Onchip(pdk, output='via', output_separation=(separation_interdigitado, separation_interdigitado+min_separation_met3), deviceA_and_B=devices_info_ntop[0]['type'], width=devices_info_ntop[0]['width'], length=devices_info_ntop[0]['length'], 
                                                  fingers=devices_info_ntop[0]['fingers'], with_dummy=devices_info_ntop[0]['with_dummy'], array=array_nmirrors_top, with_tie=devices_info_ntop[0]['with_tie'], with_lvt_layer=devices_info_ntop[0]['lvt'])

    nmirrors_bot = interdigitado_cascode_placement_Onchip(pdk, output='via', common_route=(False, True), output_separation=separation_interdigitado, deviceA_and_B=devices_info_nbot[0]['type'], width=devices_info_nbot[0]['width'], length=devices_info_nbot[0]['length'], 
                                                          fingers=devices_info_nbot[0]['fingers'], with_dummy=devices_info_nbot[0]['with_dummy'], array=array_nmirrors_bot, with_tie=devices_info_nbot[0]['with_tie'], with_lvt_layer=devices_info_nbot[0]['lvt'])

    top_components = Component_Biasing(pdk, devices_info_top, arrays_info_top, width_route)
    # Add the components to the biasing component
    nmirrors_top_ref = biasing << nmirrors_top
    nmirrors_bot_ref_1 = biasing << nmirrors_bot
    top_components_ref = biasing << top_components
    #Components size
    nmirrors_top_size = evaluate_bbox(nmirrors_top_ref)
    nmirrors_bot_size = evaluate_bbox(nmirrors_bot_ref_1)
    top_components_size = evaluate_bbox(top_components_ref)
    #min separation between components
    min_separation = pdk.get_grule('nwell')['min_separation']
    #amount of movement
    nmirror_top_movement = [0,0]
    nmirror_bot_1_movement = [0, (nmirrors_top_size[1] + nmirrors_bot_size[1])/2 + min_separation + separation_interdigitado]
    top_components_movement = [0, (nmirrors_top_size[1] + top_components_size[1])/2 + min_separation + separation_interdigitado]
    # move the componentes
    nmirrors_top_ref.movey(pdk.snap_to_2xgrid(nmirror_top_movement[1]))
    nmirrors_bot_ref_1.movey(pdk.snap_to_2xgrid(-nmirror_bot_1_movement[1]))
    top_components_ref.movey(pdk.snap_to_2xgrid(top_components_movement[1]))
    #Add ports
    biasing.add_ports(nmirrors_top_ref.get_ports_list(), prefix='nmirror_top_')
    biasing.add_ports(nmirrors_bot_ref_1.get_ports_list(), prefix='nmirror_bot_')
    biasing.add_ports(top_components_ref.get_ports_list(), prefix='top_ref_')
    #Vias aux
    via_3_4 = via_stack(pdk, 'met3', 'met4')
    #Routing
    #Common nodes
    biasing << straight_route(pdk, nmirrors_top_ref.ports['source_6_1_0_W'], nmirrors_top_ref.ports['source_10_1_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    biasing << straight_route(pdk, nmirrors_top_ref.ports['drain_6_1_0_W'], nmirrors_top_ref.ports['drain_10_1_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)

    biasing << straight_route(pdk, nmirrors_top_ref.ports['source_1_2_0_W'], nmirrors_top_ref.ports['source_15_2_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    biasing << straight_route(pdk, nmirrors_top_ref.ports['drain_1_2_0_W'], nmirrors_top_ref.ports['drain_15_2_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)

    biasing << straight_route(pdk, nmirrors_top_ref.ports['source_3_3_0_W'], nmirrors_top_ref.ports['source_12_3_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    biasing << straight_route(pdk, nmirrors_top_ref.ports['drain_3_3_0_W'], nmirrors_top_ref.ports['drain_12_3_0_W'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    #Cascode nmos
    #biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['source_15_1_0_W'], nmirrors_bot_ref_1.ports['source_18_1_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', via2_alignment_layer='met3', width=width_horizontal)
    biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['drain_25_1_0_W'], nmirrors_bot_ref_1.ports['drain_28_1_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', via2_alignment_layer='met3', width=width_horizontal)

    VSS1 = biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['source_11_2_0_W'], nmirrors_bot_ref_1.ports['source_112_2_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    vias_nmirror = list()
    for i in range(12):
        vias_nmirror.append(biasing << via_3_4)
        vias_nmirror[-1].movex(pdk.snap_to_2xgrid(nmirrors_bot_ref_1.ports['source_1'+str(i+1)+'_'+str(array_nmirrors_bot[0][i])+'_0_N'].center[0])).movey(pdk.snap_to_2xgrid(nmirrors_bot_ref_1.ports['source_1'+str(i+1)+'_'+str(array_nmirrors_bot[0][i])+'_0_E'].center[1]))
    biasing << straight_route(pdk, vias_nmirror[0].ports['top_met_W'], vias_nmirror[-1].ports['top_met_E'], width = width_horizontal)

    biasing.add_ports(VSS1.ports, prefix = 'VSS1_')
    biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['drain_21_2_0_W'], nmirrors_bot_ref_1.ports['drain_212_2_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    
    #biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['source_12_3_0_W'], nmirrors_bot_ref_1.ports['source_111_3_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['drain_22_3_0_W'], nmirrors_bot_ref_1.ports['drain_211_3_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    
    #nmirror top
    #source route
    for i in range(len(array_nmirrors_top[0])):
        if array_nmirrors_top[0][i] == 1:
            biasing << L_route(pdk, nmirrors_top_ref.ports['source_'+str(i+1)+'_1_0_S'], nmirrors_bot_ref_1.ports['drain_25_1_0_E'], hglayer='met2', vglayer = 'met3', vwidth = width_horizontal)
        elif array_nmirrors_top[0][i] == 2:
            biasing << L_route(pdk, nmirrors_top_ref.ports['source_'+str(i+1)+'_2_0_S'], nmirrors_bot_ref_1.ports['drain_21_2_0_E'], hglayer='met2', vglayer = 'met3', vwidth = width_horizontal)
        elif array_nmirrors_top[0][i] == 3:
            biasing << L_route(pdk, nmirrors_top_ref.ports['source_'+str(i+1)+'_3_0_S'], nmirrors_bot_ref_1.ports['drain_22_3_0_E'], hglayer='met2', vglayer = 'met3', vwidth = width_horizontal)

    # Bulk route
    biasing << c_route(pdk, nmirrors_bot_ref_1.ports['bulk_up_E'], nmirrors_top_ref.ports['bulk_down_E'])
    biasing << c_route(pdk, nmirrors_bot_ref_1.ports['bulk_up_W'], nmirrors_top_ref.ports['bulk_down_W'])

    for i in range(len(array_nmirrors_bot[0])):
        if array_nmirrors_bot[0][i] == 1:
            biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['source_1'+str(i+1)+'_1_0_N'], nmirrors_bot_ref_1.ports['bulk_down_S'], via2_alignment_layer='met2')
        elif array_nmirrors_bot[0][i] == 2:
            biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['source_1'+str(i+1)+'_2_0_N'], nmirrors_bot_ref_1.ports['bulk_down_S'], via2_alignment_layer='met2')
        elif array_nmirrors_bot[0][i] == 3:
            biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['source_1'+str(i+1)+'_3_0_N'], nmirrors_bot_ref_1.ports['bulk_down_S'], via2_alignment_layer='met2')

    # gate route
    biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['gate_1_l_S'], nmirrors_bot_ref_1.ports['gate_2_l_N'], glayer1='met3', glayer2='met3', via2_alignment_layer='met2')
    biasing << straight_route(pdk, nmirrors_bot_ref_1.ports['gate_1_r_S'], nmirrors_bot_ref_1.ports['gate_2_r_N'], glayer1='met3', glayer2='met3', via2_alignment_layer='met2')

    for i in range(len(array_nmirrors_top[0])):
        if array_nmirrors_top[0][i] == 1:
            biasing << L_route(pdk, nmirrors_top_ref.ports['drain_'+str(i+1)+'_1_0_S'], nmirrors_bot_ref_1.ports['gate_2_l_E'], hglayer='met2')

    #M1 connection
    #biasing << L_route(pdk, top_components_ref.ports['m1_source_2_2_0_S'], nmirrors_bot_ref_1.ports['source_18_1_0_E'], hglayer='met2', vwidth = width_horizontal)

    #M2 connection
    #biasing << c_route(pdk, top_components_ref.ports['m2_source_1_1_0_W'], nmirrors_bot_ref_1.ports['source_15_1_0_W'], e1glayer = 'met2', cglayer = 'met3', e2glayer = 'met2',  width1=width_horizontal, width2=width_horizontal)

    biasing << L_route(pdk, top_components_ref.ports['m2_gate1_S'], nmirrors_top_ref.ports['gate1_E'], hglayer = 'met2')

    #Pmirror connection
    biasing << L_route(pdk, top_components_ref.ports['pmirror_drain_3_3_0_S'], nmirrors_top_ref.ports['drain_10_1_0_E'], hglayer = 'met2', vwidth = width_horizontal)

    #M12 connection
    biasing << L_route(pdk, top_components_ref.ports['m12_drain_1_1_0_S'], nmirrors_top_ref.ports['drain_1_2_0_E'], hglayer = 'met2', vwidth = width_horizontal)
    biasing << L_route(pdk, top_components_ref.ports['m12_gate1_S'], nmirrors_top_ref.ports['drain_1_2_0_E'], hglayer = 'met2', vwidth = width_horizontal)
    biasing << c_route(pdk, top_components_ref.ports['m12_gate2_E'], nmirrors_top_ref.ports['drain_1_2_0_E'], e1glayer = 'met2', cglayer = 'met3', e2glayer = 'met2', width2=width_horizontal)

    #M13 connection
    biasing << L_route(pdk, top_components_ref.ports['m13_drain_2_2_0_S'], nmirrors_top_ref.ports['drain_12_3_0_W'], hglayer='met2', vwidth = width_horizontal)
    biasing << L_route(pdk, top_components_ref.ports['m13_drain_4_2_0_S'], nmirrors_top_ref.ports['drain_12_3_0_W'], hglayer='met2', vwidth = width_horizontal)

    min_separation = pdk.get_grule('met3')['min_separation']
    
    biasing_centered = center_component_with_ports(biasing)

    boundary = Boundary_layer(pdk, biasing_centered)
    boundary_dim = evaluate_bbox(boundary)

    #Input Port
    rectangle_ref = rectangle((0.5,0.5), layer=pdk.get_glayer('met2'), centered=True)

    Vref = biasing_centered << rectangle_ref
    Vref.movey(pdk.snap_to_2xgrid(biasing_centered.ports['top_ref_Vref_bottom_met_W'].center[1]))
    Vref.movex(pdk.snap_to_2xgrid(-boundary_dim[0]/2+evaluate_bbox(rectangle_ref)[0]/2))
    biasing_centered << straight_route(pdk, Vref.ports['e1'], biasing_centered.ports['top_ref_Vref_bottom_met_W'], width=width_horizontal)
    biasing_centered.add_ports(Vref.get_ports_list(), prefix='V_REF_')

    #Output port
    V_bias_N1 = biasing_centered << rectangle_ref
    V_bias_N1.movey(pdk.snap_to_2xgrid(biasing_centered.ports['nmirror_bot_gate_2_r_E'].center[1]))
    V_bias_N1.movex(pdk.snap_to_2xgrid(boundary_dim[0]/2-evaluate_bbox(rectangle_ref)[0]/2)).movey(pdk.snap_to_2xgrid((biasing_centered.ports['nmirror_bot_gate_1_r_E'].center[1]-biasing_centered.ports['nmirror_bot_gate_2_r_E'].center[1])/2))
    biasing_centered << L_route(pdk, biasing_centered.ports['nmirror_bot_gate_2_r_N'], V_bias_N1.ports['e1'])
    biasing_centered.add_ports(V_bias_N1.get_ports_list(), prefix='V_BIASN1_')

    V_bias_N2 = biasing_centered << rectangle_ref
    V_bias_N2.movey(pdk.snap_to_2xgrid(biasing_centered.ports['nmirror_top_gate2_E'].center[1]))
    V_bias_N2.movex(pdk.snap_to_2xgrid(boundary_dim[0]/2-evaluate_bbox(rectangle_ref)[0]/2))
    biasing_centered << straight_route(pdk, V_bias_N2.ports['e1'], biasing_centered.ports['nmirror_top_gate2_W'], glayer1='met2', glayer2='met2')
    biasing_centered.add_ports(V_bias_N2.get_ports_list(), prefix='V_BIASN2_')

    V_bias_P1 = biasing_centered << rectangle_ref
    V_bias_P1.movey(pdk.snap_to_2xgrid(biasing_centered.ports['top_ref_VbiasP1_top_met_E'].center[1]))
    V_bias_P1.movex(pdk.snap_to_2xgrid(boundary_dim[0]/2-evaluate_bbox(rectangle_ref)[0]/2))
    biasing_centered << straight_route(pdk, V_bias_P1.ports['e3'], biasing_centered.ports['top_ref_VbiasP1_bottom_met_W'], glayer1='met2', glayer2='met2')
    biasing_centered.add_ports(V_bias_P1.get_ports_list(), prefix='V_BIASP1_')

    biasing_centered = center_component_with_ports(biasing_centered)
    rename_ports_by_orientation(biasing_centered)
    #name = [name for name in biasing_centered.ports if 'bulk' in name]
    #print(name)
    route_list = [['VSS1_route_', 'VSS'], ['top_ref_VSS1_con_', 'VSS'], ['nmirror_bot_bulk_down_', 'VSS'], ['nmirror_bot_bulk_up_', 'VSS'], ['nmirror_top_bulk_down_', 'VSS'],
                  ['nmirror_top_bulk_up_', 'VSS'], ['top_ref_m1_bulk_up_', 'VSS'], ['top_ref_m1_bulk_down_', 'VSS'], ['top_ref_m2_bulk_up_', 'VSS'], ['top_ref_m2_bulk_down_', 'VSS'],
                  ['top_ref_VDD1_route_', 'VDD'], ['top_ref_VDD2_route_', 'VDD'], ['top_ref_pmirror_bulk_up_', 'VDD'], ['top_ref_pmirror_bulk_down_', 'VDD'],
                  ['top_ref_m12_bulk_up_', 'VDD'], ['top_ref_m12_bulk_down_', 'VDD'], ['top_ref_m13_bulk_up_', 'VDD'], ['top_ref_m13_bulk_down_', 'VDD']]

    rails(pdk, biasing_centered, 1, route_list)

    component = Component()
    component << biasing_centered


    filtrar_puertos(biasing_centered, component, 'V_REF_', 'VREF_')
    #filtrar_puertos(biasing_centered, component, 'top_ref_Vdd_bottom_met_', 'Vdd_')
    #filtrar_puertos(biasing_centered, component, 'VSS_bottom_met_', 'Vss_')
    filtrar_puertos(biasing_centered, component, 'V_BIASN1_', 'VBIASN1_')
    filtrar_puertos(biasing_centered, component, 'V_BIASN2_', 'VBIASN2_')
    filtrar_puertos(biasing_centered, component, 'V_BIASP1_', 'VBIASP1_')
    filtrar_puertos(biasing_centered, component, 'top_ref_VbiasP2_bottom_met_', 'VBIASP2_')

    # add the pin and label
    #pin_label_creation('Vss', 'VSS', 'met3', component)
    pin_label_creation(pdk, 'VBIASN1', 'VbiasN1', 'met2', component)
    pin_label_creation(pdk, 'VBIASN2', 'VbiasN2', 'met2', component)
    pin_label_creation(pdk, 'VREF', 'Vref', 'met2', component)    
    #pin_label_creation(pdk, 'Vdd', 'VDD', 'met3', component)
    pin_label_creation(pdk, 'VBIASP1', 'VbiasP1', 'met2', component)
    pin_label_creation(pdk, 'VBIASP2', 'VbiasP2', 'met2', component)

    rename_ports_by_orientation(component)

    return component

# Information of the transistors
array_m1_m15 = [[1,2]]
array_m13_m14 = [[1,2,1,2,1]]
array_m12_m18 = [[1,2]]
array_pmirrors = [[2,1,3]]
array_nmirrors_top = [[2,2,3,3,3,1,1,1,1,1,3,3,2,2,2]]
array_nmirrors_bot = [[2,3,2,3,1,1,1,1,3,2,3,2]]


devices_info_m1_m15 = {'type':'nfet', 'name':'M1', 'width':0.5, 'length':6, 'width_route_mult':1, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'lvt':False}
devices_info_m12_m18 = {'type':'pfet', 'name':'M12', 'width':0.5, 'length':2, 'width_route_mult':1, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'lvt':False}
devices_info_pmirrors = {'type':'pfet', 'name':'Pmirrors', 'width':0.5, 'length':2, 'width_route_mult':1, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'lvt':False}
devices_info_ntop = {'type':'nfet', 'name':'nmirror_top', 'width':0.5, 'length':6, 'width_route_mult':1, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'lvt':False}
devices_info_nbot = {'type':'nfet', 'name':'nmirror_bot', 'width':0.5, 'length':6, 'width_route_mult':1, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'lvt':False}
devices_info = [devices_info_m1_m15, devices_info_m12_m18, devices_info_pmirrors, devices_info_ntop, devices_info_nbot]
arrays_info = [array_m1_m15, array_m12_m18, array_pmirrors, array_m13_m14, array_nmirrors_top, array_nmirrors_bot]

Test = Biasing_generator(gf180, devices_info, arrays_info, width_route=1)
Test.name = "folded_cascode_bias"
Test.write_gds("folded_cascode_bias_pcells.gds")
#ports = [name for name in Test.ports if 'V' in name]
#print(ports)
Test.show()