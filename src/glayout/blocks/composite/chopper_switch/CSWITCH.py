
from glayout import MappedPDK, sky130 , gf180
#from gdsfactory.cell import cell
from gdsfactory import Component
from gdsfactory.components import text_freetype, rectangle
from glayout import nmos, pmos
from glayout import via_stack, via_array
from glayout import rename_ports_by_orientation
from glayout import tapring
from glayout.util.comp_utils import evaluate_bbox, prec_center, prec_ref_center, align_comp_to_port
from glayout.util.port_utils import add_ports_perimeter,print_ports
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.spice.netlist import Netlist
from glayout.routing.straight_route import straight_route
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route

import os
import subprocess

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

import sys
from pathlib import Path
sys.path.append(os.path.abspath("../elementary/TGSW"))

from TGSW import tgswitch

def add_cswitch_labels(
    cswitch_in: Component,
    pdk: MappedPDK,
    ) -> Component:
    
    cswitch_in.unlock()

    psize=(0.5,0.5)
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list

    # VSS
    vsslabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    vsslabel.add_label(text="VSS",layer=pdk.get_glayer("met3_label"))
    move_info.append((vsslabel,cswitch_in.ports["VSS_TOP_top_met_N"],None))
    move_info.append((vsslabel,cswitch_in.ports["VSS_BOTTOM_top_met_N"],None))
    #gnd_ref = top_level << gndlabel;

    #suply
    vddlabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    vddlabel.add_label(text="VDD",layer=pdk.get_glayer("met3_pin"))
    move_info.append((vddlabel,cswitch_in.ports["VDD_TOPL_top_met_N"],None))
    move_info.append((vddlabel,cswitch_in.ports["VDD_TOPR_top_met_N"],None))
    move_info.append((vddlabel,cswitch_in.ports["VDD_BOTTOML_top_met_S"],None))
    move_info.append((vddlabel,cswitch_in.ports["VDD_BOTTOMR_top_met_S"],None))
    #sup_ref = top_level << suplabel;

    # output
    outputplabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    outputplabel.add_label(text="VOUTP",layer=pdk.get_glayer("met2_pin"))
    move_info.append((outputplabel,cswitch_in.ports["OUTP_top_met_E"],None))
    outputnlabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    outputnlabel.add_label(text="VOUTN",layer=pdk.get_glayer("met2_pin"))
    move_info.append((outputnlabel,cswitch_in.ports["OUTN_top_met_E"],None))
    #op_ref = top_level << outputlabel;

    # input
    inputplabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    inputplabel.add_label(text="VINN",layer=pdk.get_glayer("met2_pin"))
    move_info.append((inputplabel,cswitch_in.ports["INP_top_met_W"], None))
    inputnlabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    inputnlabel.add_label(text="VINP",layer=pdk.get_glayer("met2_pin"))
    move_info.append((inputnlabel,cswitch_in.ports["INN_top_met_W"], None))
    #ip_ref = top_level << inputlabel;

    # CLK
    clklabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    clklabel.add_label(text="CLK",layer=pdk.get_glayer("met3_pin"))
    move_info.append((clklabel,cswitch_in.ports["CLK_TOP_top_met_N"], None))
    move_info.append((clklabel,cswitch_in.ports["CLK_BOTTOM_top_met_S"], None))
    clkinvlabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    clkinvlabel.add_label(text="CLKINV",layer=pdk.get_glayer("met3_pin"))
    move_info.append((clkinvlabel,cswitch_in.ports["CLKINV_TOP_top_met_N"], None))
    move_info.append((clkinvlabel,cswitch_in.ports["CLKINV_BOTTOM_top_met_S"], None))
    #clk_ref = top_level << clklabel;

    for comp, prt, alignment in move_info:
            alignment = ('c','b') if alignment is None else alignment
            compref = align_comp_to_port(comp, prt, alignment=alignment)
            cswitch_in.add(compref)
    
    return cswitch_in.flatten()

def cswitch(
        pdk: MappedPDK,
        width: tuple[float,float] = (10,10),
        length: tuple[float,float] = (0.5,0.5),
        fingers: tuple[int,int] = (6,6),
        multipliers: tuple[int,int] = (1,1),
        dummy_1: tuple[bool,bool] = (True,True),
        dummy_2: tuple[bool,bool] = (True,True),
        tie_layers1: tuple[str,str] = ("met2","met1"),
        tie_layers2: tuple[str,str] = ("met2","met1"),
        sd_rmult: int=1,
        **kwargs
        ) -> Component:

    pdk.activate()
    
    #top level component
    top_level = Component(name="cswitch")

    #four TG Switch
    SW1 = tgswitch(pdk, "vertical",(width[0],width[1]),(length[0],length[1]),(fingers[0],fingers[1]),(multipliers[0],multipliers[1]))
    SW2 = tgswitch(pdk, "vertical_inv",(width[0],width[1]),(length[0],length[1]),(fingers[0],fingers[1]),(multipliers[0],multipliers[1]))
    SW3 = tgswitch(pdk, "vertical",(width[0],width[1]),(length[0],length[1]),(fingers[0],fingers[1]),(multipliers[0],multipliers[1]))
    SW4 = tgswitch(pdk, "vertical_inv",(width[0],width[1]),(length[0],length[1]),(fingers[0],fingers[1]),(multipliers[0],multipliers[1]))

    SW1_ref = top_level << SW1
    SW2_ref = top_level << SW2
    SW3_ref = top_level << SW3
    SW4_ref = top_level << SW4

    SW1_ref.name = "SW1"
    SW2_ref.name = "SW2"
    SW3_ref.name = "SW3"
    SW4_ref.name = "SW4"

    x_distance = 15
    y_distance = 14.5
    ref_dimensions = evaluate_bbox(SW1_ref)

    SW2_ref.movex(SW1_ref.xmax + x_distance)
    SW3_ref.movey(SW1_ref.ymin - y_distance)
    SW4_ref.movex(SW1_ref.xmax + x_distance).movey(SW1_ref.ymin - y_distance)

    viam2m3 = via_stack(pdk, "met2", "met3", centered=True) #met2 is the bottom layer. met3 is the top layer.

    #via for input and output
    vinp_start_via = top_level << viam2m3
    vinp_end_via = top_level << viam2m3
    vinn_start_via = top_level << viam2m3
    vinn_end_via = top_level << viam2m3

    voutp_start_via = top_level << viam2m3
    voutp_end_via = top_level << viam2m3
    voutn_start_via = top_level << viam2m3
    voutn_end_via = top_level << viam2m3

    #via for CLK and CLKinv
    clk_top_via = top_level << viam2m3
    clk_bottom_via = top_level << viam2m3
    clkinv_top_via = top_level << viam2m3
    clkinv_bottom_via = top_level << viam2m3


    top_level << straight_route(pdk, SW1_ref.ports["P_gate_E"], SW2_ref.ports["N_gate_W"])
    top_level << straight_route(pdk, SW1_ref.ports["N_gate_E"], SW2_ref.ports["P_gate_W"])
    top_level << straight_route(pdk, SW3_ref.ports["P_gate_E"], SW4_ref.ports["N_gate_W"])
    top_level << straight_route(pdk, SW3_ref.ports["N_gate_E"], SW4_ref.ports["P_gate_W"])

    vinp_start_via.move(SW1_ref.ports["P_source_top_met_W"].center).movey(SW1_ref.ymin - pdk.util_max_metal_seperation()).movex(-ref_dimensions[0]/1.55)
    vinn_start_via.move(vinp_start_via.center).movey(- 0.75 - pdk.util_max_metal_seperation())
    vinp_end_via.move(vinp_start_via.center).movex(SW2_ref.xmax - x_distance/2)
    vinn_end_via.move(vinn_start_via.center).movex(SW2_ref.xmax - x_distance/2 - 1)

    voutp_start_via.move(vinp_start_via.center).movey(pdk.util_max_metal_seperation()+0.75).movex(SW2_ref.xmin - 4)
    voutn_start_via.move(vinn_start_via.center).movey(-pdk.util_max_metal_seperation()-0.75).movex(SW2_ref.xmin - 4)
    voutp_end_via.move(voutp_start_via.center).movex(SW2_ref.xmax-6)
    voutn_end_via.move(voutn_start_via.center).movex(SW2_ref.xmax-7)

    clk_top_via.move(SW1_ref.ports["P_gate_E"].center).movex(SW1_ref.xmax-1.5)
    clkinv_top_via.move(SW2_ref.ports["P_gate_W"].center).movex(SW1_ref.xmin+1.5)
    clk_bottom_via.move(SW3_ref.ports["P_gate_E"].center).movex(SW1_ref.xmax-1.5)
    clkinv_bottom_via.move(SW4_ref.ports["P_gate_W"].center).movex(SW1_ref.xmin+1.5)

    #input routes
    top_level << L_route(pdk, SW1_ref.ports["P_drain_top_met_W"], vinp_start_via.ports["top_met_N"])
    top_level << L_route(pdk, SW3_ref.ports["P_drain_top_met_W"], vinn_start_via.ports["top_met_S"])
    top_level << L_route(pdk, SW4_ref.ports["P_drain_top_met_W"], vinn_end_via.ports["top_met_N"])
    top_level << L_route(pdk, SW2_ref.ports["P_drain_top_met_W"], vinp_end_via.ports["top_met_S"])
    top_level << straight_route(pdk, vinp_start_via.ports["bottom_met_E"], vinp_end_via.ports["bottom_met_W"])
    top_level << straight_route(pdk, vinn_start_via.ports["bottom_met_E"], vinn_end_via.ports["bottom_met_W"])

    #output routes
    top_level << L_route(pdk, SW1_ref.ports["P_source_top_met_E"], voutp_start_via.ports["top_met_N"])
    top_level << L_route(pdk, SW3_ref.ports["P_source_top_met_E"], voutn_start_via.ports["top_met_S"])
    top_level << L_route(pdk, SW2_ref.ports["P_source_top_met_E"], voutn_end_via.ports["top_met_N"])
    top_level << L_route(pdk, SW4_ref.ports["P_source_top_met_E"], voutp_end_via.ports["top_met_S"])
    top_level << straight_route(pdk, voutp_start_via.ports["bottom_met_E"], voutp_end_via.ports["bottom_met_W"])
    top_level << straight_route(pdk, voutn_start_via.ports["bottom_met_E"], voutn_end_via.ports["bottom_met_W"])

    #CLK routes
    top_level << straight_route(pdk, clk_top_via.ports["top_met_S"], clk_bottom_via.ports["top_met_N"])
    top_level << straight_route(pdk, clkinv_top_via.ports["top_met_S"], clkinv_bottom_via.ports["top_met_N"])

    # Add tapring
    tap_ring = tapring(pdk, enclosed_rectangle=evaluate_bbox(top_level.flatten(), padding=pdk.get_grule("nwell", "active_diff")["min_enclosure"]+pdk.util_max_metal_seperation()))
    shift_amount = -prec_center(top_level.flatten())[0]
    shifty_amount = prec_center(top_level.flatten())[1]
    tring_ref = top_level << tap_ring
    tring_ref.movex(destination=shift_amount).movey(destination=-shifty_amount)

    #VDD Rails
    viaarray = via_array(pdk, "met2", "met3", (2,1)) 

    VDD1_via = top_level << viaarray
    VDD2_via = top_level << viaarray
    VDD3_via = top_level << viaarray
    VDD4_via = top_level << viaarray
    VDD5_via = top_level << viaarray
    VDD6_via = top_level << viaarray
    VDD7_via = top_level << viaarray
    VDD8_via = top_level << viaarray

    VDD1_via.move(SW1_ref.ports["P_tie_N_top_met_E"].center).movex(SW1_ref.xmin+0.75)
    VDD2_via.move(SW1_ref.ports["P_tie_S_top_met_E"].center).movex(SW1_ref.xmin+0.75)
    VDD3_via.move(SW2_ref.ports["P_tie_N_top_met_E"].center).movex(SW1_ref.xmin+0.75)
    VDD4_via.move(SW2_ref.ports["P_tie_S_top_met_E"].center).movex(SW1_ref.xmin+0.75)
    VDD5_via.move(SW3_ref.ports["P_tie_N_top_met_E"].center).movex(SW1_ref.xmin+0.75)
    VDD6_via.move(SW3_ref.ports["P_tie_S_top_met_E"].center).movex(SW1_ref.xmin+0.75)
    VDD7_via.move(SW4_ref.ports["P_tie_N_top_met_E"].center).movex(SW1_ref.xmin+0.75)
    VDD8_via.move(SW4_ref.ports["P_tie_S_top_met_E"].center).movex(SW1_ref.xmin+0.75)

    top_level << straight_route(pdk, VDD1_via.ports["top_met_S"], VDD6_via.ports["top_met_N"])
    top_level << straight_route(pdk, VDD4_via.ports["top_met_S"], VDD7_via.ports["top_met_N"])
    
    # VSS Rails
    VSS1_via = top_level << viaarray
    VSS2_via = top_level << viaarray
    VSS1_via.move(tring_ref.ports["N_top_met_E"].center).movex(tring_ref.xmin*2.25)
    VSS2_via.move(tring_ref.ports["S_top_met_E"].center).movex(tring_ref.xmin*2.25)

    top_level << straight_route(pdk, VSS1_via.ports["top_met_N"], VSS2_via.ports["top_met_S"], width=2)

    top_level << straight_route(pdk, SW2_ref.ports["N_tie_N_top_met_W"], VSS1_via.ports["top_met_N"])
    top_level << straight_route(pdk, SW2_ref.ports["N_tie_S_top_met_W"], VSS1_via.ports["top_met_N"])
    top_level << straight_route(pdk, SW1_ref.ports["N_tie_N_top_met_E"], VSS1_via.ports["top_met_N"])
    top_level << straight_route(pdk, SW1_ref.ports["N_tie_S_top_met_E"], VSS1_via.ports["top_met_N"])
    top_level << straight_route(pdk, SW4_ref.ports["N_tie_N_top_met_W"], VSS1_via.ports["top_met_N"])
    top_level << straight_route(pdk, SW4_ref.ports["N_tie_S_top_met_W"], VSS1_via.ports["top_met_N"])
    top_level << straight_route(pdk, SW3_ref.ports["N_tie_N_top_met_E"], VSS1_via.ports["top_met_N"])
    top_level << straight_route(pdk, SW3_ref.ports["N_tie_S_top_met_E"], VSS1_via.ports["top_met_N"])

    viam1m2 = via_stack(pdk, "met1", "met2", centered=True) #met2 is the bottom layer. met3 is the top layer.

    # tapring - bulk pmos
    SW1_tapring = top_level << viam1m2
    SW2_tapring = top_level << viam1m2
    SW3_tapring = top_level << viam1m2
    SW4_tapring = top_level << viam1m2

    SW1_tapring.move(SW1_ref.ports["N_tie_W_array_row23_col0_top_met_W"].center).movex(-1.2)
    SW2_tapring.move(SW2_ref.ports["N_tie_E_array_row23_col0_top_met_W"].center).movex(1.6)
    SW3_tapring.move(SW3_ref.ports["N_tie_W_array_row23_col0_top_met_W"].center).movex(-1.2)
    SW4_tapring.move(SW4_ref.ports["N_tie_E_array_row23_col0_top_met_W"].center).movex(1.6)

    top_level << straight_route(pdk, SW1_tapring.ports["top_met_W"], SW1_ref.ports["N_tie_W_array_row23_col0_top_met_E"])
    top_level << straight_route(pdk, SW2_tapring.ports["top_met_E"], SW2_ref.ports["N_tie_E_array_row23_col0_top_met_W"])
    top_level << straight_route(pdk, SW3_tapring.ports["top_met_W"], SW3_ref.ports["N_tie_W_array_row23_col0_top_met_E"])
    top_level << straight_route(pdk, SW4_tapring.ports["top_met_E"], SW4_ref.ports["N_tie_E_array_row23_col0_top_met_W"])
    
    top_level.add_ports(SW1_ref.get_ports_list(), prefix="SW1_")
    top_level.add_ports(SW2_ref.get_ports_list(), prefix="SW2_")
    top_level.add_ports(SW3_ref.get_ports_list(), prefix="SW3_")
    top_level.add_ports(SW4_ref.get_ports_list(), prefix="SW4_")

    top_level.add_ports(vinp_start_via.get_ports_list(), prefix="INP_")
    top_level.add_ports(vinn_start_via.get_ports_list(), prefix="INN_")
    top_level.add_ports(voutp_end_via.get_ports_list(), prefix="OUTP_")
    top_level.add_ports(voutn_end_via.get_ports_list(), prefix="OUTN_")

    top_level.add_ports(clk_top_via.get_ports_list(), prefix="CLK_TOP_")
    top_level.add_ports(clkinv_top_via.get_ports_list(), prefix="CLKINV_TOP_")
    top_level.add_ports(clk_bottom_via.get_ports_list(), prefix="CLK_BOTTOM_")
    top_level.add_ports(clkinv_bottom_via.get_ports_list(), prefix="CLKINV_BOTTOM_")

    top_level.add_ports(VDD1_via.get_ports_list(), prefix="VDD_TOPL_")
    top_level.add_ports(VDD3_via.get_ports_list(), prefix="VDD_TOPR_")
    top_level.add_ports(VDD6_via.get_ports_list(), prefix="VDD_BOTTOML_")
    top_level.add_ports(VDD8_via.get_ports_list(), prefix="VDD_BOTTOMR_")

    top_level.add_ports(VSS1_via.get_ports_list(), prefix="VSS_TOP_")
    top_level.add_ports(VSS2_via.get_ports_list(), prefix="VSS_BOTTOM_")

    return component_snap_to_grid(rename_ports_by_orientation(top_level))

if __name__ == "__main__":
	comp = cswitch(gf180)

	# comp.pprint_ports()

	comp = add_cswitch_labels(comp, gf180)

	comp.name = "CSWITCH"

	comp.write_gds('out_CSWITCH.gds')

	comp.show()

	print("...Running DRC...")

	drc_result = gf180.drc_magic(comp, "CSWITCH")

	drc_result = gf180.drc(comp)

