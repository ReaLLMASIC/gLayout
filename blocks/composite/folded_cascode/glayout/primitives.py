# Numerical functions
from decimal import Decimal
from typing import Literal, Optional, Union

# PDK functions

from glayout import MappedPDK, sky130, gf180


from gdsfactory.component import Component, copy

# Import custom functions (Matrix generator)
from custom_functions import macro_two_transistor_placement_Onchip
from custom_functions import pin_label_creation
from custom_functions import filtrar_puertos
from custom_functions import center_component_with_ports

# Glayout tools

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

# Routing functions
from glayout import via_stack
from glayout.routing import c_route, L_route, straight_route

# Porting functions
from gdsfactory.functions import transformed


#### 1ST LEVEL PRIMITIVES ####

### Mirror primitive ###

def mirror(pdk: MappedPDK, devices_info, matrix, with_pin: int = 0) -> Component:
    mirror = Component()
    """"
    pdk = pdk to use
    devices_info = the devices to place, usually formed as an array with all the information
    matrix = A full matrix with the placement organization
    with_pin = Makes the primitive have pins which don't have any electrical purpose

    Mirror primitive, can be used in its NMOS version or PMOS 
    """
    # Matrix placement

    config = macro_two_transistor_placement_Onchip(pdk=pdk, deviceA_and_B=devices_info['type'], with_substrate_tap=devices_info['with_substrate_tap'],
                                                              with_tie=devices_info['with_tie'], width1=devices_info['width'], length1=devices_info['length'],
                                                              fingers1=devices_info['fingers'], matriz=matrix, with_dummy=devices_info['with_dummy'],
                                                              width_route_mult=devices_info['width_route_mult'], with_lvt_layer=devices_info['lvt'])

    matrix = mirror << config
    mirror.add_ports(matrix.get_ports_list())
    
    # Evaluate the dimensions
    ################################
    size_component = evaluate_bbox(matrix)

    # Routing 
    #####################

    # Gate to Gate (A -> B) 
    route_Gate = mirror << straight_route(pdk, matrix.ports['A_gate_E'], matrix.ports['B_gate_W'])

    # Source to Source (A -> B)
    route_Src = mirror << L_route(pdk, matrix.ports['A_source_N'], matrix.ports['B_source_E'])

    # Gate to Drain (A -> A (B))
    route_gate_drain_A = mirror << L_route(pdk, matrix.ports['A_gate_S'], matrix.ports['A_drain_W'])

    # Bulk routing (Neglecting Body Effect)
    route_bulk_1 = mirror << straight_route(pdk, matrix.ports['A_source_N'], matrix.ports['bulk_down_S'], glayer1='met3', glayer2='met3')
    route_bulk_2 = mirror << straight_route(pdk, matrix.ports['B_source_N'], matrix.ports['bulk_down_S'], glayer1='met3', glayer2='met3')

    ## External o Internal device

    if with_pin == 1:
        # Pin creation
        pin_label_creation('A_drain', 'V_REF', 'met3', mirror)
        pin_label_creation('B_drain', 'V_OUT', 'met3', mirror)
        pin_label_creation('B_source', 'VS', 'met3', mirror)
        pin_label_creation('A_gate', 'VB', 'met3', mirror)

    

    component = Component()
    component << mirror

    filtrar_puertos(mirror, component, 'A_drain_', 'V_REF_')
    filtrar_puertos(mirror, component, 'B_drain_', 'V_OUT_')
    filtrar_puertos(mirror, component, 'B_source_', 'VS_')
    filtrar_puertos(mirror, component, 'A_gate_', 'VB_')

    return component

### Single transistor primitive ###

def transistor(pdk, devices_info, matrix, with_pin: int = 0, with_b_effect: int = 0) -> Component:
    transistor = Component()
    """"
    pdk = pdk to use
    devices_info = The devices to place, usually formed as an array with all the information
    matrix = A full matrix with the placement organization
    with_pin = Makes the primitive have pins which don't have any electrical purpose
    with_b_effect = Allows to have or not to have a bulk port

    Transistor primitive, can be used in its NMOS version or PMOS, it already neglects the body effect
    """
    #Matrix placement

    config = macro_two_transistor_placement_Onchip(pdk=pdk, deviceA_and_B=devices_info['type'], with_substrate_tap=devices_info['with_substrate_tap'],
                                                              with_tie=devices_info['with_tie'], width1=devices_info['width'], length1=devices_info['length'],
                                                              fingers1=devices_info['fingers'], matriz=matrix, with_dummy=devices_info['with_dummy'],
                                                              width_route_mult=devices_info['width_route_mult'], with_lvt_layer=devices_info['lvt'])

    matrix = transistor << config
    transistor.add_ports(matrix.get_ports_list())

    # Evaluate the dimensions
    ################################
    size_component = evaluate_bbox(matrix)

    # Routing 
    #####################

    if with_b_effect == 0:

        # Bulk routing (Neglecting Body Effect)
        via_ref = via_stack(pdk, 'met2', 'met3')

        via_bulk = transistor << via_ref
        via_bulk.movex(matrix.ports['A_source_N'].center[0]).movey(matrix.ports['bulk_down_E'].center[1])
        
        route_bulk_1 = transistor << straight_route(pdk, matrix.ports['A_source_S'], via_bulk.ports['top_met_N'])

        ## External o Internal device

        if with_pin == 1:
            
            #Pin creation
            pin_label_creation('A_drain', 'VD', 'met3', transistor)
            pin_label_creation('A_gate', 'VG', 'met3', transistor)
            pin_label_creation('A_source', 'VS', 'met3', transistor)

    

        component = Component()
        component << transistor

        filtrar_puertos(transistor, component, 'A_drain_', 'VD_')
        filtrar_puertos(transistor, component, 'A_gate_', 'VG_')
        filtrar_puertos(transistor, component, 'A_source_', 'VS_')
        filtrar_puertos(transistor, component, 'bulk_down_', 'VBC_D_')
        filtrar_puertos(transistor, component, 'bulk_up_', 'VBC_U_')
    
    if with_b_effect == 1:
        if with_pin == 1:

        ## External o Internal device
 
            #Pin creation
            pin_label_creation('A_drain', 'VD', 'met3', transistor)
            pin_label_creation('A_gate', 'VG', 'met3', transistor)
            pin_label_creation('A_source', 'VS', 'met3', transistor)
            pin_label_creation('bulk_down', 'VB', 'met3', transistor)

        

        component = Component()
        component << transistor

        filtrar_puertos(transistor, component, 'A_drain_', 'VD_')
        filtrar_puertos(transistor, component, 'A_gate_', 'VG_')
        filtrar_puertos(transistor, component, 'A_source_', 'VS_')
        filtrar_puertos(transistor, component, 'bulk_down_', 'VBC_D_')
        filtrar_puertos(transistor, component, 'bulk_up_', 'VBC_U_')

    return component

### Single transistor diode primitive ###

def diode(pdk, devices_info, matrix, with_pin: int = 0) -> Component:
    diode = Component()
    """"
    pdk = pdk to use
    devices_info = The devices to place, usually formed as an array with all the information
    matrix = A full matrix with the placement organization
    with_pin = Makes the primitive have pins which don't have any electrical purpose

    Diode primitive, can be used in its NMOS version or PMOS
    """
    #Matrix placement

    config = macro_two_transistor_placement_Onchip(pdk=pdk, deviceA_and_B=devices_info['type'], with_substrate_tap=devices_info['with_substrate_tap'],
                                                              with_tie=devices_info['with_tie'], width1=devices_info['width'], length1=devices_info['length'],
                                                              fingers1=devices_info['fingers'], matriz=matrix, with_dummy=devices_info['with_dummy'],
                                                              width_route_mult=devices_info['width_route_mult'], with_lvt_layer=devices_info['lvt'])
    matrix = diode << config
    diode.add_ports(matrix.get_ports_list())

    # Evaluate the dimensions
    ################################
    size_component = evaluate_bbox(matrix)

    # Routing 
    #####################

    # Gate to Drain (A -> A)
    route_gate_drain_A = diode << L_route(pdk, matrix.ports['A_gate_S'], matrix.ports['A_drain_W'])

    # Bulk routing (Neglecting Body Effect)
    route_bulk_1 = diode << straight_route(pdk, matrix.ports['A_source_N'], matrix.ports['bulk_down_S'], glayer1='met3', glayer2='met3')

    if with_pin == 1:
        #Pin creation
        pin_label_creation('A_drain', 'VD', 'met3', diode)
        pin_label_creation('A_source', 'VS', 'met3', diode)
    

    component = Component()
    component << diode

    filtrar_puertos(diode, component, 'A_drain_', 'VD_')
    filtrar_puertos(diode, component, 'A_source_', 'VS_')

    return component

### Current source primitive ###

def current_source(pdk,devices_info,matrix, with_pin: int = 0, with_b_effect: int = 0) -> Component:
    """"
    pdk = pdk to use
    devices_info = The devices to place, usually formed as an array with all the information
    matrix = A full matrix with the placement organization
    with_pin = Makes the primitive have pins which don't have any electrical purpose
    with_b_effect = Allows to have or not to have a bulk port

    Current source primitive, can be used in its NMOS version or PMOS
    """
    current_source = Component()

    #Matrix placement
    config = macro_two_transistor_placement_Onchip(pdk=pdk, deviceA_and_B=devices_info['type'], with_substrate_tap=devices_info['with_substrate_tap'],
                                                              with_tie=devices_info['with_tie'], width1=devices_info['width'], length1=devices_info['length'],
                                                              fingers1=devices_info['fingers'], matriz=matrix, with_dummy=devices_info['with_dummy'],
                                                              width_route_mult=devices_info['width_route_mult'], with_lvt_layer=devices_info['lvt'])
    matrix = current_source << config
    current_source.add_ports(matrix.get_ports_list())

    # Evaluate the dimensions
    ################################
    size_component = evaluate_bbox(matrix)

    # Routing 
    #####################

    #Gate routing (Gate (A) -> Gate (B))
    route_Gate = current_source << straight_route(pdk, matrix.ports['A_gate_E'], matrix.ports['B_gate_W'])

    if with_b_effect == 0:

        # Bulk routing (Neglecting Body Effect)
        via_ref = via_stack(pdk, 'met2', 'met3')

        via_A_bulk = current_source << via_ref
        via_A_bulk.movex(matrix.ports['A_source_N'].center[0]).movey(matrix.ports['bulk_down_E'].center[1])

        via_B_bulk = current_source << via_ref
        via_B_bulk.movex(matrix.ports['B_source_N'].center[0]).movey(matrix.ports['bulk_down_E'].center[1])

        Route_bulk_1 = current_source << straight_route(pdk, matrix.ports['A_source_N'], via_A_bulk.ports['top_met_N'])
        Route_bulk_2 = current_source << straight_route(pdk, matrix.ports['B_source_N'], via_B_bulk.ports['top_met_N'])

        ## External o Internal device

        if with_pin == 1:
            #Pin creation
            pin_label_creation('A_gate', 'VBIAS', 'met3', current_source)
            pin_label_creation('B_gate', 'VBIAS2', 'met3', current_source)
            pin_label_creation('A_source', 'VS1', 'met3', current_source)
            pin_label_creation('B_source', 'VS2', 'met3', current_source)
            pin_label_creation('A_drain', 'VD1', 'met3', current_source)
            pin_label_creation('B_drain', 'VD2', 'met3', current_source)
            pin_label_creation('bulk_up', 'VBC_U', 'met3',current_source)
            pin_label_creation('bulk_down', 'VBC_D', 'met3',current_source)


        component = Component()
        component << current_source

        filtrar_puertos(current_source, component, 'A_gate_', 'VBIAS_')
        filtrar_puertos(current_source, component, 'B_gate_', 'VBIAS2_')
        filtrar_puertos(current_source, component, 'A_source_', 'VS1_')
        filtrar_puertos(current_source, component, 'B_source_', 'VS2_')
        filtrar_puertos(current_source, component, 'A_drain_', 'VD1_')
        filtrar_puertos(current_source, component, 'B_drain_', 'VD2_')
        filtrar_puertos(current_source, component, 'bulk_up_', 'VBC_U_')
        filtrar_puertos(current_source, component, 'bulk_down_', 'VBC_D_')

    if with_b_effect == 1:

        ## External o Internal device

        if with_pin == 1:
            #Pin creation
            pin_label_creation('A_gate', 'VBIAS', 'met3', current_source)
            pin_label_creation('B_gate', 'VBIAS2', 'met3', current_source)
            pin_label_creation('A_source', 'VS1', 'met3', current_source)
            pin_label_creation('B_source', 'VS2', 'met3', current_source)
            pin_label_creation('A_drain', 'VD1', 'met3', current_source)
            pin_label_creation('B_drain', 'VD2', 'met3', current_source)
            pin_label_creation('bulk_down', 'VB', 'met3', current_source)

        
        component = Component()
        component << current_source

        filtrar_puertos(current_source, component, 'A_gate_', 'VBIAS_')
        filtrar_puertos(current_source, component, 'B_gate_', 'VBIAS2_')
        filtrar_puertos(current_source, component, 'A_source_', 'VS1_')
        filtrar_puertos(current_source, component, 'B_source_', 'VS2_')
        filtrar_puertos(current_source, component, 'A_drain_', 'VD1_')
        filtrar_puertos(current_source, component, 'B_drain_', 'VD2_')
        filtrar_puertos(current_source, component, 'bulk_down_', 'VBC_D_')
        filtrar_puertos(current_source, component, 'bulk_up_', 'VBC_U_')
    
    return component

### Differential pair ###

def differential_pair(pdk,devices_info,matrix, with_pin: int = 0, with_b_effect: int = 0) -> Component:
    """"
    pdk = pdk to use
    devices_info = The devices to place, usually formed as an array with all the information
    matrix = A full matrix with the placement organization
    with_pin = Makes the primitive have pins which don't have any electrical purpose
    with_b_effect = Allows to have or not to have a bulk port

    Differential pair primitive, can be used in its NMOS version or PMOS
    """
    differential_pair = Component()

    #Matrix placement
    config = macro_two_transistor_placement_Onchip(pdk=pdk, deviceA_and_B=devices_info['type'], with_substrate_tap=devices_info['with_substrate_tap'],
                                                              with_tie=devices_info['with_tie'], width1=devices_info['width'], length1=devices_info['length'],
                                                              fingers1=devices_info['fingers'], matriz=matrix, with_dummy=devices_info['with_dummy'],
                                                              width_route_mult=devices_info['width_route_mult'], with_lvt_layer=devices_info['lvt'])
    matrix = differential_pair << config
    differential_pair.add_ports(matrix.get_ports_list())

    # Evaluate the dimensions
    ################################
    size_component = evaluate_bbox(matrix)

    # Routing 
    #####################

    #Routing from Source(A -> B)
    route_source_A_source_B = differential_pair << L_route(pdk, matrix.ports['A_source_N'], matrix.ports['B_source_E'])

    if with_b_effect == 0:
        # Bulk routing (Neglecting Body Effect)
        via_ref = via_stack(pdk, 'met2', 'met3')

        via_A_bulk = differential_pair << via_ref
        via_A_bulk.movex(matrix.ports['A_source_N'].center[0]).movey(matrix.ports['bulk_down_E'].center[1])

        via_B_bulk = differential_pair << via_ref
        via_B_bulk.movex(matrix.ports['B_source_N'].center[0]).movey(matrix.ports['bulk_down_E'].center[1])

        ruta_bulk_1 = differential_pair << straight_route(pdk, matrix.ports['A_source_S'], via_A_bulk.ports['top_met_N'])
        ruta_bulk_2 = differential_pair << straight_route(pdk, matrix.ports['B_source_S'], via_B_bulk.ports['top_met_N'])

        ## External o Internal device

        if with_pin == 1:
            #Pin creation
            pin_label_creation('A_gate', 'VGP', 'met3', differential_pair)
            pin_label_creation('B_gate', 'VGN', 'met3', differential_pair)
            pin_label_creation('A_source', 'VS', 'met3', differential_pair)
            pin_label_creation('A_drain', 'VD1', 'met3', differential_pair)
            pin_label_creation('B_drain', 'VD2', 'met3', differential_pair)

        

        component = Component()
        component << differential_pair
        filtrar_puertos(differential_pair, component, 'A_gate_', 'VGP_')
        filtrar_puertos(differential_pair, component, 'B_gate_', 'VGN_')
        filtrar_puertos(differential_pair, component, 'B_source_', 'VS_')
        filtrar_puertos(differential_pair, component, 'A_drain_', 'VD1_')
        filtrar_puertos(differential_pair, component, 'B_drain_', 'VD2_')
        filtrar_puertos(differential_pair, component, 'bulk_down_', 'VBC_D_')
        filtrar_puertos(differential_pair, component, 'bulk_up_', 'VBC_U_')
    
    if with_b_effect == 1:

        ## External o Internal device

        if with_pin == 1:
            #Pin creation
            pin_label_creation('A_gate', 'VGP', 'met3', differential_pair)
            pin_label_creation('B_gate', 'VGN', 'met3', differential_pair)
            pin_label_creation('A_source', 'VS', 'met3', differential_pair)
            pin_label_creation('A_drain', 'VD1', 'met3', differential_pair)
            pin_label_creation('B_drain', 'VD2', 'met3', differential_pair)
            pin_label_creation('bulk_down', 'VB', 'met3', differential_pair)

        

        component = Component()
        component << differential_pair
        filtrar_puertos(differential_pair, component, 'A_gate_', 'VGP_')
        filtrar_puertos(differential_pair, component, 'B_gate_', 'VGN_')
        filtrar_puertos(differential_pair, component, 'B_source_', 'VS_')
        filtrar_puertos(differential_pair, component, 'A_drain_', 'VD1_')
        filtrar_puertos(differential_pair, component, 'B_drain_', 'VD2_')
        filtrar_puertos(differential_pair, component, 'bulk_down_', 'VBC_D_')
        filtrar_puertos(differential_pair, component, 'bulk_up_', 'VBC_U_')


    return component

#### 2ND LEVEL PRIMITIVES ####

### Cascode ###

def Cascode(pdk, devices_info, array, with_pin: int = 0) -> Component:
    """"
    pdk = pdk to use
    devices_info = The devices to place, usually formed as an array with all the information
    array = A full matrix with the placement organization
    with_pin = Makes the primitive have pins which don't have any electrical purpose

    Cascode primitive, can be used in its NMOS version or PMOS
    """
    Cascode = Component()

    # Use of 1st order primitive

    CS1 = current_source(pdk, devices_info[0], array[0], 0, 1)
    CS2 = current_source(pdk, devices_info[1], array[1], 0, 0) 

    Current_Source_1 = Cascode << CS1
    Current_Source_2 = Cascode << CS2


    # Placement and size of the current source
    ####################

    size_CS_2 = evaluate_bbox(Current_Source_2)
    size_CS_1 = evaluate_bbox(Current_Source_1)
    max_size = pdk.snap_to_2xgrid(pdk.get_grule('met4')['min_separation'] + (size_CS_1[1]+size_CS_2[1])/2)
    Current_Source_1.movey(sky130.get_grule('met4')['min_separation']+max_size)
    
    Current_Source_1.mirror(p1=(0, 0), p2=(1, 0))
    Current_Source_2.mirror(p1=(0, 0), p2=(1, 0))

    # Centering

    ### Porting ###

    Cascode.add_ports(Current_Source_1.get_ports_list(),prefix='CS1_')
    Cascode.add_ports(Current_Source_2.get_ports_list(),prefix='CS2_')

    # Routing 
    ###################

    ### Diode routing ###
    diode_route = Cascode << c_route(pdk, Current_Source_1.ports['VD1_W'], Current_Source_2.ports['VBIAS_W'], cglayer = 'met3', cwidth = (Current_Source_2.ports['VS2_E'].width)/2)

    ### Between transistors routing ###
    Route_DS1 = Cascode << straight_route(pdk, Current_Source_1.ports['VS1_N'], Current_Source_2.ports['VD1_S'])
    Route_DS2 = Cascode << straight_route(pdk, Current_Source_1.ports['VS2_N'], Current_Source_2.ports['VD2_S'])

    ### Source connections ###

    Route_Ref = Cascode << L_route(pdk, Current_Source_2.ports['VS1_N'], Current_Source_2.ports['VS2_E'])

    ### Bulk connection ###
    
    via_ref = via_stack(pdk, 'met2', 'met3')
    via_cs1 = Cascode << via_ref
    via_cs1.movex(Current_Source_1.ports['VBC_D_N'].center[0]).movey(Current_Source_1.ports['VBC_D_E'].center[1])

    via_cs2 = Cascode << via_ref
    via_cs2.movex(Current_Source_2.ports['VBC_U_N'].center[0]).movey(Current_Source_2.ports['VBC_U_E'].center[1])
    Route_bulk = Cascode << straight_route(pdk, via_cs1.ports['top_met_N'], via_cs2.ports['top_met_S'])
    ## External o Internal device

    if with_pin == 1:

        pin_label_creation('CS2_VS1', 'VREF', 'met3', Cascode)
        pin_label_creation('CS2_VD1', 'VIP', 'met3', Cascode)
        pin_label_creation('CS2_VD2', 'VIN', 'met3', Cascode)
        pin_label_creation('CS1_VBIAS', 'VB1', 'met3', Cascode)
        pin_label_creation('CS1_VD1', 'VD1', 'met3', Cascode)
        pin_label_creation('CS1_VD2', 'VOUT', 'met3', Cascode)

    component = Component()
    component << Cascode

    filtrar_puertos(Cascode, component, 'CS2_VS2_', 'VREF_')
    filtrar_puertos(Cascode, component, 'CS2_VD1_', 'VIP_')
    filtrar_puertos(Cascode, component, 'CS2_VD2_', 'VIN_')
    filtrar_puertos(Cascode, component, 'CS1_VBIAS2_', 'VB1_')
    filtrar_puertos(Cascode, component, 'CS2_VBIAS2_', 'VB2_')
    filtrar_puertos(Cascode, component, 'CS1_VD1_', 'VD1_')
    filtrar_puertos(Cascode, component, 'CS1_VD2_', 'VOUT_')

    component_centered = center_component_with_ports(component)

    return component_centered

### Bi current source ###

def Bi_current_source(pdk, devices_info, array, with_pin: int = 0) -> Component:
    """"
    pdk = pdk to use
    devices_info = The devices to place, usually formed as an array with all the information
    array = A full matrix with the placement organization
    with_pin = Makes the primitive have pins which don't have any electrical purpose

    Bi_current_source primitive, can be used in its NMOS version or PMOS
    """
    Bi_current_source = Component()

    # Use of 1st order primitive

    CS1 = current_source(pdk, devices_info[0], array[0], 0, 0)
    CS2 = current_source(pdk, devices_info[1], array[1], 0, 1)

    Current_Source_1 = Bi_current_source << CS1
    Current_Source_2 = Bi_current_source << CS2


    # Placement and size of the current source
    ####################

    size_CS_2 = evaluate_bbox(Current_Source_2)
    size_CS_1 = evaluate_bbox(Current_Source_1)
    max_size = (size_CS_1[1]+size_CS_2[1])/2

    Current_Source_2.movey(sky130.get_grule('met4')['min_separation']+max_size)

    ### Porting ###

    Bi_current_source.add_ports(Current_Source_1.get_ports_list(),prefix='CS1_')
    Bi_current_source.add_ports(Current_Source_2.get_ports_list(),prefix='CS2_')

    # Routing 
    ###################

    ### Between transistors routing ###
    Route_DS1 = Bi_current_source << straight_route(pdk, Current_Source_1.ports['VD1_N'], Current_Source_2.ports['VS1_S'])
    Route_DS2 = Bi_current_source << straight_route(pdk, Current_Source_1.ports['VD2_N'], Current_Source_2.ports['VS2_S'])

    ### Source connections ###

    Route_Ref = Bi_current_source << L_route(pdk, Current_Source_1.ports['VS1_N'], Current_Source_1.ports['VS2_E'])

    ### Bulk connection ###
    via_ref = via_stack(pdk, 'met2', 'met3')
    via_cs1 = Bi_current_source << via_ref
    via_cs1.movex(Current_Source_1.ports['VBC_U_N'].center[0]).movey(Current_Source_1.ports['VBC_U_E'].center[1])

    via_cs2 = Bi_current_source << via_ref
    via_cs2.movex(Current_Source_2.ports['VBC_D_N'].center[0]).movey(Current_Source_2.ports['VBC_D_E'].center[1])
    Route_bulk = Bi_current_source << straight_route(pdk, via_cs1.ports['top_met_N'], via_cs2.ports['top_met_S'])

    #Route_bulk = Bi_current_source << L_route(pdk, Current_Source_1.ports['VS2_E'], Current_Source_2.ports['VB_S'], 
    #                                        vglayer = 'met3', hwidth = (Current_Source_1.ports['VS2_N'].width)/2)
    ## External o Internal device

    if with_pin == 1:

        pin_label_creation('CS1_VD2', 'VOUT', 'met3', Bi_current_source)
        pin_label_creation('CS1_VD1', 'VD1', 'met3', Bi_current_source)
        pin_label_creation('CS2_VD2', 'VCOMM', 'met3', Bi_current_source)
        pin_label_creation('CS1_VBIAS', 'VB2', 'met3', Bi_current_source)
        pin_label_creation('CS2_VBIAS2', 'VB3', 'met3', Bi_current_source)
        pin_label_creation('CS2_VS2', 'VREF', 'met3', Bi_current_source)

    component = Component()
    component << Bi_current_source

    filtrar_puertos(Bi_current_source, component, 'CS2_VD2_', 'VOUT_')
    filtrar_puertos(Bi_current_source, component, 'CS2_VD1_', 'VD1_')
    filtrar_puertos(Bi_current_source, component, 'CS1_VBIAS_', 'VB2_')
    filtrar_puertos(Bi_current_source, component, 'CS1_VBIAS2_', 'VB2R_')
    filtrar_puertos(Bi_current_source, component, 'CS2_VBIAS2_', 'VB3_')
    filtrar_puertos(Bi_current_source, component, 'CS1_VS2_', 'VREF_')
    filtrar_puertos(Bi_current_source, component, 'CS1_VD2_', 'VCOMM_')


    component_centered = center_component_with_ports(component)

    return component_centered

### Pair bias ###

def Pair_bias(pdk, devices_info, array, with_pin: int = 0) -> Component:
    """"
    pdk = pdk to use
    devices_info = The devices to place, usually formed as an array with all the information
    array = A full matrix with the placement organization
    with_pin = Makes the primitive have pins which don't have any electrical purpose

    Pair_bias primitive, can be used in its NMOS version or PMOS
    """
    Pair_bias = Component()

    # Use of 1st order primitive

    P1 = differential_pair(pdk, devices_info[0], array[0], 0, 1)
    T1 = transistor(pdk, devices_info[1], array[1], 0, 0)

    Pair = Pair_bias << P1
    Tail = Pair_bias << T1

    # Placement and size of pair and tail
    ####################

    size_P1 = evaluate_bbox(Pair)
    size_T1 = evaluate_bbox(Tail)
    max_size = (size_P1[1] + size_T1[1])/2

    Pair.movey(sky130.get_grule('met4')['min_separation']+max_size)

    ### Porting ###

    Pair_bias.add_ports(Pair.get_ports_list(),prefix='P1_')
    Pair_bias.add_ports(Tail.get_ports_list(),prefix='T1_')

    # Routing 
    ###################

    ### Source to drain 

    Route_SD = Pair_bias << L_route(pdk, Pair.ports['VS_S'], Tail.ports['VD_E'])

    if with_pin == 1:

        pin_label_creation('P1_VGP', 'VGP', 'met3', Pair_bias)
        pin_label_creation('P1_VGN', 'VGN', 'met3', Pair_bias)
        pin_label_creation('P1_VD1', 'VDP', 'met3', Pair_bias)
        pin_label_creation('P1_VD2', 'VDN', 'met3', Pair_bias)
        pin_label_creation('T1_VG', 'VBIAS', 'met3', Pair_bias)
        pin_label_creation('T1_VS', 'VREF', 'met3', Pair_bias)

    

    component = Component()
    component << Pair_bias

    filtrar_puertos(Pair_bias, component, 'P1_VGP_', 'VGP_')
    filtrar_puertos(Pair_bias, component, 'P1_VGN_', 'VGN_')
    filtrar_puertos(Pair_bias, component, 'P1_VD1_', 'VDP_')
    filtrar_puertos(Pair_bias, component, 'P1_VD2_', 'VDN_')
    filtrar_puertos(Pair_bias, component, 'P1_VBC_D_', 'P_VBC_D_')
    filtrar_puertos(Pair_bias, component, 'P1_VBC_U_', 'P_VBC_U_')
    filtrar_puertos(Pair_bias, component, 'T1_VG_', 'VBIAS_')
    filtrar_puertos(Pair_bias, component, 'T1_VS_', 'VREF_')
    filtrar_puertos(Pair_bias, component, 'T1_VBC_D_', 'T_VBC_D_')
    filtrar_puertos(Pair_bias, component, 'T1_VBC_U_', 'T_VBC_U_')

    component_centered = center_component_with_ports(component)
    return component_centered

def moscap(pdk,devices_info, matrix):
    moscap = Component()
    """"
    description
    """

    #Matrix placement
    config = macro_two_transistor_placement_Onchip(pdk=pdk, deviceA_and_B=devices_info['type'], with_substrate_tap=devices_info['with_substrate_tap'],
                                                              with_tie=devices_info['with_tie'], width1=devices_info['width'], length1=devices_info['length'],
                                                              fingers1=devices_info['fingers'], matriz=matrix, with_dummy=devices_info['with_dummy'],
                                                              width_route_mult=devices_info['width_route_mult'], with_lvt_layer=devices_info['lvt'])

    matrix = moscap << config
    moscap.add_ports(matrix.get_ports_list())

    # Routing 
    #####################

    # Bulk to source connection

    # route_bulk_1 = moscap << L_route(pdk, matrix.ports['A_source_N'], matrix.ports['bulk_down_E'])
    route_drain_source = moscap << straight_route(pdk, matrix.ports['A_drain_N'], matrix.ports['A_source_S'])

    component = Component()
    component << moscap

    filtrar_puertos(moscap, component, 'A_drain_', 'VD_')
    filtrar_puertos(moscap, component, 'A_source_', 'VS_')
    filtrar_puertos(moscap, component, 'A_gate_', 'VG_')

    return component

    ## External o Internal device