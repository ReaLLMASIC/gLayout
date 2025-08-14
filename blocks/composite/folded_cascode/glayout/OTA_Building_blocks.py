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
from primitives import (mirror, Cascode, current_source, transistor, diode, differential_pair, Bi_current_source, Pair_bias)
from custom_functions import filtrar_puertos, pin_label_creation, interdigitado_placement_Onchip, macro_two_transistor_placement_Onchip 
from custom_functions import center_component_with_ports
from custom_functions import Boundary_layer


def place_cascode(pdk: MappedPDK) -> Component:
    place_cascode = Component()

    # Use of second order primitive
    # We define the parameters of our primitive

    m1 = {'type':'pfet', 'name':'M3_M4', 'width':1, 'length':1.5, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':True}
    m2 = {'type':'pfet', 'name':'M5_M6', 'width':1, 'length':3, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':True}

    array = [[[2,1,2,1,1,2,1,2,1,2],[1,2,1,2,2,1,2,1,2,1]],[[1,2,2,1,1,2],[2,1,1,2,2,1]]]

    devices_info = [m1,m2]

    # We call the cascode primitive 
    Cascode_call = Cascode(pdk,devices_info,array)

    
    Cascode_component = place_cascode << Cascode_call

    place_cascode.add_ports(Cascode_component.get_ports_list(),prefix='CASC_')

    #component = Component()
    #component << place_cascode

    place_cascode_centered = center_component_with_ports(place_cascode)
    component = Component()
    component << place_cascode_centered

    filtrar_puertos(place_cascode_centered, component, 'CASC_VREF_', 'VREF_')
    filtrar_puertos(place_cascode_centered, component, 'CASC_VIP_', 'VIP_')
    filtrar_puertos(place_cascode_centered, component, 'CASC_VIN_', 'VIN_')
    filtrar_puertos(place_cascode_centered, component, 'CASC_VB1_', 'VB1_')
    filtrar_puertos(place_cascode_centered, component, 'CASC_VB2_', 'VB2_')
    filtrar_puertos(place_cascode_centered, component, 'CASC_VD1_', 'VD1_')
    filtrar_puertos(place_cascode_centered, component, 'CASC_VOUT_', 'VOUT_')

    return component

def place_bi_current(pdk: MappedPDK) -> Component:
    place_bi_current = Component()

    # Use of second order primitive
    m1 = {'type':'nfet', 'name':'M9_M10', 'width':0.5, 'length':6.5, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':False}
    m2 = {'type':'nfet', 'name':'M7_M8', 'width':1, 'length':3, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':False}

    array = [[[1,2,1,2,1],[2,1,2,1,2]],[[1,2,1,2,1],[2,1,2,1,2]]]

    devices_info = [m1,m2]

    # We call the Bi_current primitive 
    Bi_current_call = Bi_current_source(pdk,devices_info,array)

    Bi_current_component = place_bi_current << Bi_current_call

    place_bi_current.add_ports(Bi_current_component.get_ports_list(),prefix='BIC_')

    #component = Component()
    #component << place_bi_current

    place_bi_current_centered = center_component_with_ports(place_bi_current)
    component = Component()
    component << place_bi_current_centered

    filtrar_puertos(place_bi_current_centered, component, 'BIC_VOUT_', 'VOUT_')
    filtrar_puertos(place_bi_current_centered, component, 'BIC_VD1_', 'VD1_')
    filtrar_puertos(place_bi_current_centered, component, 'BIC_VB2_', 'VB2_')
    filtrar_puertos(place_bi_current_centered, component, 'BIC_VB2R_', 'VB2R_')
    filtrar_puertos(place_bi_current_centered, component, 'BIC_VB3_', 'VB3_')
    filtrar_puertos(place_bi_current_centered, component, 'BIC_VREF_', 'VREF_')
    filtrar_puertos(place_bi_current_centered, component, 'BIC_VCOMM_', 'VCOMM_')

    return component

def place_par_bias(pdk: MappedPDK) -> Component:
    place_par_bias = Component()

    # Use of second order primitive
    m1 = {'type':'nfet', 'name':'M1_M2', 'width':1, 'length':1, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':False}
    m2 = {'type':'nfet', 'name':'M11', 'width':0.5, 'length':6.5, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':False}

    array = [[[1, 2, 1, 2, 1, 1, 2, 1, 2, 1],  # Row 1:    ABABA ABABA 
              [2, 1, 2, 1, 2, 2, 1, 2, 1, 2],  # Row 2:    BABAB BABAB 
              [2, 1, 2, 1, 2, 2, 1, 2, 1, 2],  # Row 3:    BABAB BABAB 
              [1, 2, 1, 2, 1, 1, 2, 1, 2, 1],  # Row 4:    ABABA ABABA 
              ]
            ,[[1,1],[1,1],[1,1],[1,1],[1,1]]] #

    devices_info = [m1,m2]

    # We call the Bi_current primitive 
    Par_bias_call = Pair_bias(pdk,devices_info,array)

    Par_bias_component = place_par_bias << Par_bias_call

    place_par_bias.add_ports(Par_bias_component.get_ports_list(),prefix='PBI_')

    #routing bulks
    pos_der = (place_par_bias.ports['PBI_P_VBC_D_N'].center[0]-place_par_bias.ports['PBI_P_VBC_D_W'].center[0])/2
    pos_iz = (place_par_bias.ports['PBI_P_VBC_D_N'].center[0]-place_par_bias.ports['PBI_P_VBC_D_E'].center[0])/2
    via_ref = via_array(pdk, 'met2', 'met3', (pos_der/2, 0.5))

    bulk_par_1 = place_par_bias << via_ref
    bulk_par_1.movex(pos_der).movey(place_par_bias.ports['PBI_P_VBC_D_E'].center[1])

    bulk_par_2 = place_par_bias << via_ref
    bulk_par_2.movex(pos_iz).movey(place_par_bias.ports['PBI_P_VBC_D_E'].center[1])

    bulk_tail_1 = place_par_bias << via_ref
    bulk_tail_1.movex(pos_der).movey(place_par_bias.ports['PBI_T_VBC_U_E'].center[1])

    bulk_tail_2 = place_par_bias << via_ref
    bulk_tail_2.movex(pos_iz).movey(place_par_bias.ports['PBI_T_VBC_U_E'].center[1])

    place_par_bias << straight_route(pdk, bulk_par_1.ports['top_met_N'], bulk_tail_1.ports['top_met_S'])
    place_par_bias << straight_route(pdk, bulk_par_2.ports['top_met_N'], bulk_tail_2.ports['top_met_S'])

    #component = Component()
    #component << place_par_bias

    place_par_bias_centered = center_component_with_ports(place_par_bias)
    component = Component()
    component << place_par_bias_centered

    filtrar_puertos(place_par_bias_centered, component, 'PBI_VGP_', 'VGP_')
    filtrar_puertos(place_par_bias_centered, component, 'PBI_VGN_', 'VGN_')
    filtrar_puertos(place_par_bias_centered, component, 'PBI_VDP_', 'VDP_')
    filtrar_puertos(place_par_bias_centered, component, 'PBI_VDN_', 'VDN_')
    filtrar_puertos(place_par_bias_centered, component, 'PBI_VBIAS_', 'VBIAS_')
    filtrar_puertos(place_par_bias_centered, component, 'PBI_VREF_', 'VREF_')

    return component, devices_info
'''
def nmos_bot(pdk: MappedPDK, 
             width_route: float = None)-> Component:
    nmos_bot = Component()
    m = {'type':'nfet', 'name':'M9_10_11', 'width':0.5, 'length':6.5, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':False}
    array = [[1,1,1,2,2,3,3,3,1,1,1,1,3,3,2,2,2,1,1,1]]
    # Width configuration
    if width_route == None or width_route == 0:
        separation_interdigitado = 0
        width_horizontal = evaluate_bbox(via_stack(pdk,'met2','met3'))[1]
    else:
        separation_interdigitado = width_route
        width_horizontal = width_route
    nmos_ref = interdigitado_placement_Onchip(pdk, output='via', output_separation=separation_interdigitado, deviceA_and_B=m['type'], width=m['width'], length=m['length'], 
                                                  fingers=m['fingers'], with_dummy=m['with_dummy'], array=array, with_tie=m['with_tie'], with_lvt_layer=m['lvt'], common_route=(False, True))
    nmos = nmos_bot << nmos_ref
    #Common routes
    nmos_bot << straight_route(pdk, nmos.ports['source_1_1_0_W'], nmos.ports['source_20_1_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    nmos_bot << straight_route(pdk, nmos.ports['drain_1_1_0_W'], nmos.ports['drain_20_1_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)
    
    nmos_bot << straight_route(pdk, nmos.ports['drain_4_2_0_W'], nmos.ports['drain_17_2_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)

    nmos_bot << straight_route(pdk, nmos.ports['drain_6_3_0_W'], nmos.ports['drain_14_3_0_E'], glayer1='met2', glayer2='met2', via1_alignment_layer='met3', width=width_horizontal)

    #Bulk routes
    for i in range(len(array[0])):
        if array[0][i] == 1:
            nmos_bot << straight_route(pdk, nmos.ports['source_'+str(i+1)+'_1_0_N'], nmos.ports['bulk_down_S'], via2_alignment_layer='met2')
        elif array[0][i] == 2:
            nmos_bot << straight_route(pdk, nmos.ports['source_'+str(i+1)+'_2_0_N'], nmos.ports['bulk_down_S'], via2_alignment_layer='met2')
        elif array[0][i] == 3:
            nmos_bot << straight_route(pdk, nmos.ports['source_'+str(i+1)+'_3_0_N'], nmos.ports['bulk_down_S'], via2_alignment_layer='met2')

    return nmos_bot

def currents_mirrors(pdk: MappedPDK,
                     width_route: float = None) -> Component:
    
    currents_mirrors = Component()
    m7_8_data = {'type':'nfet', 'name':'M7_8', 'width':1, 'length':3, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':False}
    m5_m6_data = {'type':'pfet', 'name':'M5_6', 'width':1, 'length':1.5, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':True}
    m3_m4_data = {'type':'pfet', 'name':'M3_4', 'width':1, 'length':3, 'fingers':1, 'with_substrate_tap':False, 'with_tie':True, 'with_dummy':True, 'width_route_mult':1, 'lvt':True}
    array_m7_8 = [[1,2,1,2,1],[2,1,2,1,2]]
    array_m5_6 = [[1,2,1,2,1,2,1,2,1,2],[2,1,2,1,2,1,2,1,2,1]]
    array_m3_4 = [[1,1,2,2,1,1],[2,2,1,1,2,2]]

    m7_8_ref = macro_two_transistor_placement_Onchip(pdk=pdk, deviceA_and_B=m7_8_data['type'], with_substrate_tap=m7_8_data['with_substrate_tap'],
                                                              with_tie=m7_8_data['with_tie'], width1=m7_8_data['width'], length1=m7_8_data['length'],
                                                              fingers1=m7_8_data['fingers'], matriz=array_m7_8, with_dummy=m7_8_data['with_dummy'],
                                                              width_route_mult=m7_8_data['width_route_mult'], with_lvt_layer=m7_8_data['lvt'])
    m5_6_ref = macro_two_transistor_placement_Onchip(pdk=pdk, deviceA_and_B=m5_m6_data['type'], with_substrate_tap=m5_m6_data['with_substrate_tap'],
                                                              with_tie=m5_m6_data['with_tie'], width1=m5_m6_data['width'], length1=m5_m6_data['length'],
                                                              fingers1=m5_m6_data['fingers'], matriz=array_m5_6, with_dummy=m5_m6_data['with_dummy'],
                                                              width_route_mult=m5_m6_data['width_route_mult'], with_lvt_layer=m5_m6_data['lvt'])
    m3_4_ref = macro_two_transistor_placement_Onchip(pdk=pdk, deviceA_and_B=m3_m4_data['type'], with_substrate_tap=m3_m4_data['with_substrate_tap'],
                                                              with_tie=m3_m4_data['with_tie'], width1=m3_m4_data['width'], length1=m3_m4_data['length'],
                                                              fingers1=m3_m4_data['fingers'], matriz=array_m3_4, with_dummy=m3_m4_data['with_dummy'],
                                                              width_route_mult=m3_m4_data['width_route_mult'], with_lvt_layer=m3_m4_data['lvt'])
'''
def OTA_Core(pdk: MappedPDK) -> Component:
    OTA_core = Component()

    #nmos = nmos_bot(pdk)
    BI1 = place_bi_current(pdk)
    CAS1= place_cascode(pdk)
    PB1, type_par = place_par_bias(pdk)

    #M9_10_11 = OTA << nmos
    TOP_BI1 = OTA_core << BI1
    TOP_CAS1 = OTA_core << CAS1
    TOP_PB1 = OTA_core << PB1

    size_BI1 = evaluate_bbox(TOP_BI1)
    size_CAS1 = evaluate_bbox(TOP_CAS1)
    size_PB1 = evaluate_bbox(TOP_PB1)

    max_size_y = pdk.snap_to_2xgrid((size_BI1[1] + size_CAS1[1])/2)
    max_size_x = pdk.snap_to_2xgrid((size_BI1[0] + size_PB1[0])/2)
    mov_par_tail = pdk.snap_to_2xgrid((size_PB1[1] - size_BI1[1])/2)

    if type_par[0]['type']=='nfet':
    
        TOP_CAS1.movey(max_size_y +pdk.get_grule('met4')['min_separation'])
        TOP_PB1.movey(mov_par_tail)
        TOP_PB1.movex(-(max_size_x+5*pdk.get_grule('met4')['min_separation']))

        OTA_core.add_ports(TOP_BI1.get_ports_list(),prefix='BI_')
        OTA_core.add_ports(TOP_CAS1.get_ports_list(),prefix='CAS_')
        OTA_core.add_ports(TOP_PB1.get_ports_list(),prefix='PB_')
        
        #Routing
        Route_VDS1 = OTA_core << L_route(pdk, TOP_BI1.ports['VD1_E'], TOP_CAS1.ports['VD1_S'])
        Route_VDS2 = OTA_core << L_route(pdk, TOP_BI1.ports['VOUT_E'], TOP_CAS1.ports['VOUT_S'])

        Route_CN = OTA_core << L_route(pdk, TOP_PB1.ports['VDN_S'], TOP_CAS1.ports['VIN_W'], hwidth=1)
        Route_CP = OTA_core << L_route(pdk, TOP_PB1.ports['VDP_S'], TOP_CAS1.ports['VIP_W'], hwidth=1)
        Route_Bias = OTA_core << c_route(pdk, TOP_PB1.ports['VBIAS_S'],TOP_BI1.ports['VB2_S'], extension=2*pdk.get_grule('met4')['min_separation'])
        Route_VSS = OTA_core << c_route(pdk, TOP_PB1.ports['VREF_S'], TOP_BI1.ports['VREF_S'], extension=3*pdk.get_grule('met4')['min_separation'])

    else:
        TOP_PB1.mirror((1,0))
        TOP_CAS1.movey(max_size_y +pdk.get_grule('met4')['min_separation'])
        TOP_PB1.movey((max_size_y +pdk.get_grule('met4')['min_separation'])-(pdk.snap_to_2xgrid((size_PB1[1] - size_CAS1[1])/2)))
        TOP_PB1.movex(-(max_size_x+5*pdk.get_grule('met4')['min_separation']))

        OTA_core.add_ports(TOP_BI1.get_ports_list(),prefix='BI_')
        OTA_core.add_ports(TOP_CAS1.get_ports_list(),prefix='CAS_')
        OTA_core.add_ports(TOP_PB1.get_ports_list(),prefix='PB_')

        #Routing
        Route_VDS1 = OTA_core << L_route(pdk, TOP_BI1.ports['VD1_E'], TOP_CAS1.ports['VD1_S'])
        Route_VDS2 = OTA_core << L_route(pdk, TOP_BI1.ports['VOUT_E'], TOP_CAS1.ports['VOUT_S'])

        Route_D1Par_D1M9 = OTA_core << L_route(pdk, TOP_PB1.ports['VDN_S'], TOP_BI1.ports['VD1_E'], hwidth=1)
        Route_D2Par_D2M10 = OTA_core << L_route(pdk, TOP_PB1.ports['VDP_S'], TOP_BI1.ports['VOUT_E'], hwidth=1)
        #Route_Bias = OTA_core << c_route(pdk, TOP_PB1.ports['VBIAS_S'],TOP_BI1.ports['VB2_S'], extension=2*pdk.get_grule('met4')['min_separation'])
        Route_VDD = OTA_core << c_route(pdk, TOP_PB1.ports['VREF_S'], TOP_CAS1.ports['VREF_S'], extension=3*pdk.get_grule('met4')['min_separation'])
    
    

    #Add via for output
    via_ref = via_stack(pdk,'met3', 'met4')

    VSS_out = OTA_core << via_ref
    align_comp_to_port(VSS_out, OTA_core.ports['BI_VREF_W'])
    VSS_out.movex(pdk.get_grule('met4')['min_separation'] + evaluate_bbox(TOP_BI1)[0]/2)
    OTA_core << straight_route(pdk, VSS_out.ports['top_met_E'], TOP_BI1.ports['VREF_W'], glayer1='met4', glayer2='met4', via1_alignment_layer='met3')
    OTA_core.add_ports(VSS_out.get_ports_list(), prefix='VSS_')

    VDD_out = OTA_core << via_ref
    align_comp_to_port(VDD_out, OTA_core.ports['CAS_VREF_W'])
    VDD_out.movex(pdk.get_grule('met4')['min_separation'] + evaluate_bbox(TOP_CAS1)[0]/2)
    OTA_core << straight_route(pdk, VDD_out.ports['top_met_E'], TOP_CAS1.ports['VREF_W'], glayer1='met4', glayer2='met4', via1_alignment_layer='met3')
    OTA_core.add_ports(VDD_out.get_ports_list(), prefix='VDD_')
 

    #component = Component()
    #component << OTA_core

    #Guardar ports
    component = Component()
    component << OTA_core
    
    OTA_core_centered = center_component_with_ports(OTA_core)
    component = Component()
    component << OTA_core_centered

    boundary = Boundary_layer(pdk, component)
    boundary_dim = evaluate_bbox(boundary)
    
    filtrar_puertos(OTA_core_centered, component, 'PB_VGP_', 'P_V+_', True)
    filtrar_puertos(OTA_core_centered, component, 'PB_VGN_', 'P_V-_', True)
    filtrar_puertos(OTA_core_centered, component, 'BI_VB2R_', 'P_VbiasN1_', True) #
    filtrar_puertos(OTA_core_centered, component, 'VDD_top_met_', 'P_VDD_', True)
    filtrar_puertos(OTA_core_centered, component, 'CAS_VOUT_', 'P_Vout_', True)
    filtrar_puertos(OTA_core_centered, component, 'CAS_VB2_', 'P_VbiasP1_', True) #
    filtrar_puertos(OTA_core_centered, component, 'CAS_VB1_', 'P_VbiasP2_', True) #
    filtrar_puertos(OTA_core_centered, component, 'BI_VB3_', 'P_VbiasN2_', True)  # 
    filtrar_puertos(OTA_core_centered, component, 'VSS_top_met_', 'P_VSS_', True)
    filtrar_puertos(OTA_core_centered, component, 'BI_VCOMM_', 'P_Vcomn_', True)
    
    pin_label_creation(pdk, 'P_V+','V+','met3',component, True)
    pin_label_creation(pdk, 'P_V-','V-','met3',component, True)
    pin_label_creation(pdk, 'P_VbiasN1','VbiasN1','met3',component, True)
    pin_label_creation(pdk, 'P_VDD','VDD','met3',component, True)
    pin_label_creation(pdk, 'P_Vout','Vout','met3',component, True)
    pin_label_creation(pdk, 'P_VbiasP1','VbiasP1','met3',component, True)
    pin_label_creation(pdk, 'P_VbiasP2','VbiasP2','met3',component, True)
    pin_label_creation(pdk, 'P_VbiasN2','VbiasN2','met3',component, True)
    pin_label_creation(pdk, 'P_VSS','VSS','met3',component, True)
    pin_label_creation(pdk, 'P_Vcomn', 'Vcomn', 'met3',component, True)

    rename_ports_by_orientation(component)

    return component

Test = OTA_Core(gf180)
#Test.name = "folded_cascode_core"
#Test.write_gds("folded_cascode_core_pcells.gds")
Test.show()
ports_name = [name for name in Test.ports if '_' in name]
print(ports_name)
