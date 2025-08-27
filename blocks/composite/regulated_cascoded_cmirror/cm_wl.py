from glayout import MappedPDK, sky130,gf180
from glayout import nmos, pmos, tapring,via_stack

from glayout.spice.netlist import Netlist
from glayout.routing import c_route,L_route,straight_route

from gdsfactory.component import Component
from gdsfactory.component_reference import ComponentReference
from gdsfactory.cell import cell
from gdsfactory import Component
from gdsfactory.components import text_freetype, rectangle

from glayout.util.comp_utils import evaluate_bbox, prec_center, align_comp_to_port, prec_ref_center
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.util.port_utils import rename_ports_by_orientation
from glayout.util.port_utils import add_ports_perimeter

###### Only Required for IIC-OSIC Docker
import os
import subprocess
from pathlib import Path
# Run a shell, source .bashrc, then printenv
cmd = 'bash -c "source ~/.bashrc && printenv"'
result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
env_vars = {}
for line in result.stdout.splitlines():
    if '=' in line:
        key, value = line.split('=', 1)
        env_vars[key] = value

# Now, update os.environ with these
os.environ.update(env_vars)
###############################################################################
from typing import Optional
import time

def add_lvcm_labels(lvcm_in: Component,
                pdk: MappedPDK
                ) -> Component:
	
    lvcm_in.unlock()
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    # gnd
    gndlabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.5,0.5),centered=True).copy()
    gndlabel.add_label(text="GND",layer=pdk.get_glayer("met2_label"))
    move_info.append((gndlabel,lvcm_in.ports["M_1_B_tie_N_top_met_N"],None))
    
    #currentbias
    ibias1label = rectangle(layer=pdk.get_glayer("met3_pin"),size=(0.5,0.5),centered=True).copy()
    ibias1label.add_label(text="IBIAS1",layer=pdk.get_glayer("met3_label"))
    move_info.append((ibias1label,lvcm_in.ports["M_1_A_drain_bottom_met_N"],None))
    
    ibias2label = rectangle(layer=pdk.get_glayer("met3_pin"),size=(0.5,0.5),centered=True).copy()
    ibias2label.add_label(text="IBIAS2",layer=pdk.get_glayer("met3_label"))
    move_info.append((ibias2label,lvcm_in.ports["M_2_A_drain_bottom_met_N"],None))

    # output 
    output1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    output1label.add_label(text="IOUT1",layer=pdk.get_glayer("met2_label"))
    move_info.append((output1label,lvcm_in.ports["M_3_A_multiplier_0_drain_N"],None))
    
    output2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    output2label.add_label(text="IOUT2",layer=pdk.get_glayer("met2_label"))
    move_info.append((output2label,lvcm_in.ports["M_4_A_multiplier_0_drain_N"],None))

    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        lvcm_in.add(compref)
    return lvcm_in.flatten() 

def low_voltage_cmirr_netlist(bias_fvf: Component, cascode_fvf: Component, fet_1_ref: ComponentReference, fet_2_ref: ComponentReference, fet_3_ref: ComponentReference, fet_4_ref: ComponentReference) -> Netlist:
    
        netlist = Netlist(circuit_name='Low_voltage_current_mirror', nodes=['IBIAS1', 'IBIAS2', 'GND', 'IOUT1', 'IOUT2'])
        netlist.connect_netlist(bias_fvf.info['netlist'], [('VIN','IBIAS1'),('VBULK','GND'),('Ib','IBIAS1'),('VOUT','local_net_1')])
        netlist.connect_netlist(cascode_fvf.info['netlist'], [('VIN','IBIAS1'),('VBULK','GND'),('Ib', 'IBIAS2'),('VOUT','local_net_2')])
        fet_1A_ref=netlist.connect_netlist(fet_2_ref.info['netlist'], [('D', 'IOUT1'),('G','IBIAS1'),('B','GND')])
        fet_2A_ref=netlist.connect_netlist(fet_4_ref.info['netlist'], [('D', 'IOUT2'),('G','IBIAS1'),('B','GND')])
        fet_1B_ref=netlist.connect_netlist(fet_1_ref.info['netlist'], [('G','IBIAS2'),('S', 'GND'),('B','GND')])
        fet_2B_ref=netlist.connect_netlist(fet_3_ref.info['netlist'], [('G','IBIAS2'),('S', 'GND'),('B','GND')])
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
   
# @cell
def  current_mirror_WL(
        pdk: MappedPDK,
        width:  float = 4.15,
        length: float = 2,
        fingers: int = 2,
        multipliers: int = 1,
        ) -> Component:
    """
    A low voltage P type current mirror. It has one input brnaches and three output branches. 
    """
    #top level component
    cmwl = Component("current_mirror_WL")
    cmwl_ref = prec_ref_center(cmwl)
    
    #creating fets for output branches
    fet = pmos(pdk, width=width,  length=length, fingers=fingers, multipliers=multipliers, with_dummy=True, dnwell=False,  with_substrate_tap=False)
    fet_1_ref = prec_ref_center(fet)
    fet_2_ref = prec_ref_center(fet) 
    fet_3_ref = prec_ref_center(fet)
    fet_4_ref = prec_ref_center(fet)

    fet_1_ref.move(cmwl_ref.center).movex(- (evaluate_bbox(fet)[0]/2) - pdk.util_max_metal_seperation())
    fet_2_ref.move(cmwl_ref.center).movex(- (3*evaluate_bbox(fet)[0]/2) - 2*pdk.util_max_metal_seperation())
    fet_3_ref.move(cmwl_ref.center).movex( (evaluate_bbox(fet)[0]/2) + pdk.util_max_metal_seperation())
    fet_4_ref.move(cmwl_ref.center).movex( (3*evaluate_bbox(fet)[0]/2) + 2*pdk.util_max_metal_seperation())

    cmwl.add(fet_1_ref)
    cmwl.add(fet_2_ref)
    cmwl.add(fet_3_ref)
    cmwl.add(fet_4_ref)
 
    # top_level << c_route(pdk, bias_fvf_ref.ports["A_multiplier_0_gate_E"], bias_fvf_ref.ports["B_gate_bottom_met_E"])
    # top_level << c_route(pdk, cascode_fvf_ref.ports["A_multiplier_0_gate_W"], bias_fvf_ref.ports["A_multiplier_0_gate_W"])
    # top_level << straight_route(pdk, cascode_fvf_ref.ports["B_gate_bottom_met_E"], fet_3_ref.ports["multiplier_0_gate_W"])
    
    #creating vias for routing
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    gate_1_via = cmwl << viam2m3 
    gate_1_via.move(fet_1_ref.ports["multiplier_0_gate_W"].center).movex(-1)
    gate_2_via = cmwl << viam2m3                                         
    gate_2_via.move(fet_2_ref.ports["multiplier_0_gate_W"].center).movex(-1)
    gate_3_via = cmwl << viam2m3 
    gate_3_via.move(fet_3_ref.ports["multiplier_0_gate_E"].center).movex(1)
    gate_4_via = cmwl << viam2m3 
    gate_4_via.move(fet_4_ref.ports["multiplier_0_gate_E"].center).movex(1)

    source_2_via = cmwl << viam2m3
    drain_1_via = cmwl << viam2m3
    source_2_via.move(fet_2_ref.ports["multiplier_0_source_E"].center).movex(1.5)
    drain_1_via.move(fet_1_ref.ports["multiplier_0_drain_W"].center).movex(-1)

    source_4_via = cmwl << viam2m3
    drain_3_via = cmwl << viam2m3
    source_4_via.move(fet_4_ref.ports["multiplier_0_source_W"].center).movex(-1)
    drain_3_via.move(fet_3_ref.ports["multiplier_0_drain_E"].center).movex(1.5)
    
    #routing
    cmwl << straight_route(pdk, fet_2_ref.ports["multiplier_0_source_E"], source_2_via.ports["bottom_met_W"])
    cmwl << straight_route(pdk, fet_1_ref.ports["multiplier_0_drain_W"], drain_1_via.ports["bottom_met_E"])
    cmwl << straight_route(pdk, fet_4_ref.ports["multiplier_0_source_W"], source_4_via.ports["bottom_met_E"])
    cmwl << straight_route(pdk, fet_3_ref.ports["multiplier_0_drain_E"], drain_3_via.ports["bottom_met_W"])
    cmwl << c_route(pdk, source_2_via.ports["top_met_N"], drain_1_via.ports["top_met_N"], extension=0.5*evaluate_bbox(fet)[1], width1=0.32, width2=0.32, cwidth=0.32, e1glayer="met3", e2glayer="met3", cglayer="met2")
    cmwl << c_route(pdk, source_4_via.ports["top_met_N"], drain_3_via.ports["top_met_N"], extension=0.5*evaluate_bbox(fet)[1], width1=0.32, width2=0.32, cwidth=0.32, e1glayer="met3", e2glayer="met3", cglayer="met2")

    cmwl << straight_route(pdk, fet_1_ref.ports["multiplier_0_gate_W"], gate_1_via.ports["bottom_met_E"])
    cmwl << straight_route(pdk, fet_2_ref.ports["multiplier_0_gate_W"], gate_2_via.ports["bottom_met_E"])    
    cmwl << straight_route(pdk, fet_3_ref.ports["multiplier_0_gate_E"], gate_3_via.ports["bottom_met_W"])
    cmwl << straight_route(pdk, fet_4_ref.ports["multiplier_0_gate_E"], gate_4_via.ports["bottom_met_W"])

    cmwl << c_route(pdk, gate_1_via.ports["top_met_S"], gate_3_via.ports["top_met_S"], extension=(1.2*width+0.6), cglayer='met2')
    cmwl << c_route(pdk, gate_2_via.ports["top_met_S"], gate_4_via.ports["top_met_S"], extension=(1.2*width-0.6), cglayer='met2')
    
    cmwl << straight_route(pdk, fet_1_ref.ports["multiplier_0_source_W"], fet_1_ref.ports["tie_W_top_met_W"], glayer1='met1', width=0.2)
    cmwl << straight_route(pdk, fet_3_ref.ports["multiplier_0_source_W"], fet_3_ref.ports["tie_W_top_met_W"], glayer1='met1', width=0.2)
    
    cmwl.add_ports(fet_1_ref.get_ports_list(), prefix="M_3_B_")
    cmwl.add_ports(fet_2_ref.get_ports_list(), prefix="M_3_A_")
    cmwl.add_ports(fet_3_ref.get_ports_list(), prefix="M_4_B_")
    cmwl.add_ports(fet_4_ref.get_ports_list(), prefix="M_4_A_")
    
    component = component_snap_to_grid(rename_ports_by_orientation(cmwl))
    #component.info['netlist'] = low_voltage_cmirr_netlist(bias_fvf, cascode_fvf, fet_1_ref, fet_2_ref, fet_3_ref, fet_4_ref)
    
    return component

if __name__ == "__main__":
    comp =current_mirror_WL(gf180)
    # comp.pprint_ports()
    #comp =add_lvcm_labels(comp,sky130)
    comp.name = "CMWL"
    comp.show()
    #print(comp.info['netlist'].generate_netlist())
    #print("...Running DRC...")
    #drc_result = sky130.drc_magic(comp, "LVCM")
    ## Klayout DRC
    #drc_result = sky130.drc(comp)
    
    #time.sleep(5)
        
    #print("...Running LVS...")
    #lvs_res=sky130.lvs_netgen(comp, "LVCM")
    #print("...Saving GDS...")
    #comp.write_gds('out_LVCM.gds')
