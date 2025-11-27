
from glayout import MappedPDK, sky130 , gf180
from gdsfactory.cell import cell
from gdsfactory import Component
from gdsfactory.components import text_freetype, rectangle

from glayout import nmos, pmos
from glayout import via_stack
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

def add_tgswitch_labels(
    tgswitch_in: Component,
    pdk: MappedPDK,
    ) -> Component:
    
    tgswitch_in.unlock()

    psize=(0.5,0.5)
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list

    # VSS
    vsslabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    vsslabel.add_label(text="VSS",layer=pdk.get_glayer("met2_label"))
    move_info.append((vsslabel,component.ports["N_tie_N_top_met_W"],None))
    #gnd_ref = top_level << gndlabel;

    #suply
    vddlabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    vddlabel.add_label(text="VDD",layer=pdk.get_glayer("met2_label"))
    move_info.append((vddlabel,component.ports["P_tie_N_top_met_W"],None))
    #sup_ref = top_level << suplabel;

    # output
    outputlabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    outputlabel.add_label(text="VOUT",layer=pdk.get_glayer("met3_label"))
    move_info.append((outputlabel,component.ports["P_drain_top_met_N"],None))
    #op_ref = top_level << outputlabel;

    # input
    inputlabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    inputlabel.add_label(text="VIN",layer=pdk.get_glayer("met3_label"))
    move_info.append((inputlabel,component.ports["P_source_top_met_N"], None))
    #ip_ref = top_level << inputlabel;

    # CLK
    clklabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    clklabel.add_label(text="CLK",layer=pdk.get_glayer("met2_label"))
    move_info.append((clklabel,component.ports["N_gate_S"], None))

    # CLK_INV
    clkinvlabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    clkinvlabel.add_label(text="CLKinv",layer=pdk.get_glayer("met2_label"))
    move_info.append((clkinvlabel,component.ports["P_gate_N"], None))

    for comp, prt, alignment in move_info:
            alignment = ('c','b') if alignment is None else alignment
            compref = align_comp_to_port(comp, prt, alignment=alignment)
            tgswitch_in.add(compref)
    
    return tgswitch_in.flatten()
@cell
def tgswitch(
        pdk: MappedPDK,
        placement: str = "vertical",
        width: tuple[float,float] = (12,12),
        length: tuple[float,float] = (0.5,0.5),
        fingers: tuple[int,int] = (5,5),
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
    top_level = Component(name="tgswitch")

    #two fets
    fet_P = pmos(pdk, width=width[0], fingers=fingers[0], multipliers=multipliers[0], with_dummy=dummy_1, with_substrate_tap=False, length=length[0], tie_layers=tie_layers1, sd_rmult=sd_rmult, **kwargs )
    fet_N = nmos(pdk, width=width[1], fingers=fingers[1], multipliers=multipliers[1], with_dummy=dummy_2, with_substrate_tap=False, length=length[1], tie_layers=tie_layers2, sd_rmult=sd_rmult, with_dnwell=False, **kwargs)
    
    fet_P_ref = top_level << fet_P
    fet_N_ref = top_level << fet_N 
    fet_P_ref.name = "fet_P"
    fet_N_ref.name = "fet_N"

    #Relative move
    ref_dimensions = evaluate_bbox(fet_N)
    if placement == "vertical":
    #    display_component(top_level, scale = 2,path="../../")
        fet_N_ref.mirror_y()
        fet_N_ref.movey(fet_P_ref.ymin - ref_dimensions[1]/2 - pdk.util_max_metal_seperation()-0.5)
    elif placement == "vertical_inv":
    #    display_component(top_level, scale = 2,path="../../")
        fet_P_ref.mirror_y()
        fet_P_ref.movey(fet_N_ref.ymin - ref_dimensions[1]/2 - pdk.util_max_metal_seperation()-0.5)
    elif placement == "horizontal":
    #    display_component(top_level, scale = 2,path="../../")
        fet_N_ref.movex(fet_P_ref.xmax + ref_dimensions[0]/2 + pdk.util_max_metal_seperation()+1)
    else:
            raise ValueError("Placement must be either 'vertical', 'vertical _inv', or 'horizontal'")

    #Routing
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True) #met2 is the bottom layer. met3 is the top layer.
    
    #via for input and output
    drain_P_via = top_level << viam2m3
    source_P_via = top_level << viam2m3

    if placement == "vertical":
        drain_P_via.move(fet_P_ref.ports["multiplier_0_source_W"].center).movex(-0.75).movey((fet_N_ref.ymin-fet_N_ref.ymax)/1.7)
        source_P_via.move(fet_P_ref.ports["multiplier_0_drain_E"].center).movex(0.75).movey((fet_N_ref.ymin-fet_N_ref.ymax)/1.7)
        top_level << c_route(pdk, fet_P_ref.ports["multiplier_0_source_W"], fet_N_ref.ports["multiplier_0_source_W"])
        top_level << c_route(pdk, fet_P_ref.ports["multiplier_0_drain_E"], fet_N_ref.ports["multiplier_0_drain_E"])
    elif placement == "vertical_inv":
        drain_P_via.move(fet_N_ref.ports["multiplier_0_source_W"].center).movex(-0.75).movey((fet_P_ref.ymin-fet_P_ref.ymax)/1.7)
        source_P_via.move(fet_N_ref.ports["multiplier_0_drain_E"].center).movex(0.75).movey((fet_P_ref.ymin-fet_P_ref.ymax)/1.7)
        top_level << c_route(pdk, fet_P_ref.ports["multiplier_0_source_W"], fet_N_ref.ports["multiplier_0_source_W"])
        top_level << c_route(pdk, fet_P_ref.ports["multiplier_0_drain_E"], fet_N_ref.ports["multiplier_0_drain_E"])
    elif placement == "horizontal":
        source_P_via.move(fet_P_ref.ports["multiplier_0_source_W"].center).movex(ref_dimensions[0]*0.9)
        drain_P_via.move(fet_P_ref.ports["multiplier_0_drain_E"].center).movex(ref_dimensions[0]*0.15)
        top_level << straight_route(pdk, fet_P_ref.ports["multiplier_0_source_E"], fet_N_ref.ports["multiplier_0_source_W"])
        top_level << straight_route(pdk, fet_P_ref.ports["multiplier_0_drain_E"], fet_N_ref.ports["multiplier_0_drain_W"])
    else:
            raise ValueError("Placement must be either 'vertical', 'vertical_inv', or 'horizontal'.")

    top_level.add_ports(fet_P_ref.get_ports_list(), prefix="P_")
    top_level.add_ports(fet_N_ref.get_ports_list(), prefix="N_")
    top_level.add_ports(drain_P_via.get_ports_list(), prefix="P_drain_")
    top_level.add_ports(source_P_via.get_ports_list(), prefix="P_source_")

    return component_snap_to_grid(rename_ports_by_orientation(top_level))

if __name__ == "__main__":
	comp = tgswitch(gf180)

	# comp.pprint_ports()

	comp = add_tgswitch_labels(comp, gf180)

	comp.name = "TGSW"

	comp.write_gds('out_TGSW.gds')

	comp.show()

	print("...Running DRC...")

	drc_result = gf180.drc_magic(comp, "TGSW")

	drc_result = gf180.drc(comp)

