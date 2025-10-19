
from glayout import MappedPDK, sky130 , gf180 , ihp130
#from gdsfactory.cell import cell
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

###### Only Required for IIC-OSIC Docker
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


def add_fvf_labels(
    fvf_in: Component,
    pdk: MappedPDK,
    ) -> Component:
    fvf_in.unlock()

    psize=(0.5,0.5)
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list

    # gnd
    gndlabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    gndlabel.add_label(text="VBULK",layer=pdk.get_glayer("met2_label"))
    move_info.append((gndlabel,fvf_in.ports["B_tie_N_top_met_N"],None))
    #gnd_ref = top_level << gndlabel;
    
    
    
    #currentbias
    ibiaslabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    ibiaslabel.add_label(text="Ib",layer=pdk.get_glayer("met3_pin"))
    move_info.append((ibiaslabel,fvf_in.ports["A_drain_top_met_N"],None))
    #ib_ref = top_level << ibiaslabel;
    
    
    # output
    outputlabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    outputlabel.add_label(text="VOUT",layer=pdk.get_glayer("met3_pin"))
    move_info.append((outputlabel,fvf_in.ports["A_source_top_met_N"],None))
    #op_ref = top_level << outputlabel;
    
    
    # input
    inputlabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=psize,centered=True).copy()
    inputlabel.add_label(text="VIN",layer=pdk.get_glayer("met2_pin"))
    move_info.append((inputlabel,fvf_in.ports["A_gate_top_met_N"], None))
    #ip_ref = top_level << inputlabel;
    
    
    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        fvf_in.add(compref)
        
    return fvf_in.flatten() 

# @cell
def  flipped_voltage_follower(
        pdk: MappedPDK,
        device_type: str = "nmos", 
        placement: str = "horizontal",
        width: tuple[float,float] = (3,3),
        length: tuple[float,float] = (None,None),
        fingers: tuple[int,int] = (1,1),
        multipliers: tuple[int,int] = (1,1),
        with_substrate_tap: bool = False,
        dummy_1: tuple[bool,bool] = (True,True),
        dummy_2: tuple[bool,bool] = (True,True),
        tie_layers1: tuple[str,str] = ("met2","met1"),
        tie_layers2: tuple[str,str] = ("met2","met1"),
        sd_rmult: int=1,
        **kwargs
        ) -> Component:

    pdk.activate()
    
    #top level component
    top_level = Component(name="flipped_voltage_follower")

    #two fets
    device_map = {
            "nmos": nmos,
            "pmos":pmos,
            }
    device = device_map.get(device_type)
    if device_type == "nmos":
    	kwargs["with_dnwell"] = False  

    fet_1 = device(pdk, width=width[0], fingers=fingers[0], multipliers=multipliers[0], with_dummy=dummy_1, with_substrate_tap=False, length=length[0], tie_layers=tie_layers1, sd_rmult=sd_rmult, **kwargs)
    fet_2 = device(pdk, width=width[1], fingers=fingers[1], multipliers=multipliers[1], with_dummy=dummy_2, with_substrate_tap=False, length=length[1], tie_layers=tie_layers2, sd_rmult=sd_rmult, **kwargs)
    well = "pwell" if device == nmos else "nwell" 
    top_level.info.update({"fet_1": fet_1, "fet_2": fet_2}) #for later access in other functions

    fet_1_ref = top_level << fet_1
    fet_2_ref = top_level << fet_2 
    fet_1_ref.name = "fet1_ref"
    fet_2_ref.name = "fet2_ref"

    #Relative move
    ref_dimensions = evaluate_bbox(fet_2)
    if placement == "horizontal":
        fet_2_ref.movex(fet_1_ref.xmax + ref_dimensions[0]/2 + pdk.util_max_metal_seperation()+1)
    elif placement == "vertical":
        fet_2_ref.movey(fet_1_ref.ymin - ref_dimensions[1]/2 - pdk.util_max_metal_seperation()-1)
        
    else:
        raise ValueError("Placement must be either 'horizontal' or 'vertical'.")
    
    #Routing
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    drain_1_via = top_level << viam2m3
    source_1_via = top_level << viam2m3
    gate_1_via = top_level << viam2m3

    drain_2_via = top_level << viam2m3
    gate_2_via = top_level << viam2m3
    
    drain_1_via.move(fet_1_ref.ports["multiplier_0_drain_W"].center).movex(-0.5*evaluate_bbox(fet_1)[1])
    source_1_via.move(fet_1_ref.ports["multiplier_0_source_E"].center).movex(1.5)
    gate_1_via.move(fet_1_ref.ports["multiplier_0_gate_E"].center)

    drain_2_via.move(fet_2_ref.ports["multiplier_0_drain_W"].center).movex(-1.5)
    gate_2_via.move(fet_2_ref.ports["multiplier_0_gate_E"].center).movex(1)

    top_level << straight_route(pdk, fet_1_ref.ports["multiplier_0_source_E"], source_1_via.ports["bottom_met_W"])
    top_level << straight_route(pdk, fet_1_ref.ports["multiplier_0_gate_S"], gate_1_via.ports["bottom_met_N"])
    top_level << straight_route(pdk, fet_2_ref.ports["multiplier_0_drain_W"], drain_2_via.ports["bottom_met_E"])
    top_level << c_route(pdk, source_1_via.ports["top_met_N"], drain_2_via.ports["top_met_N"], extension=1.2*max(width[0],width[1]), width1=0.32, width2=0.32, cwidth=0.32, e1glayer="met3", e2glayer="met3", cglayer="met2")
    top_level << straight_route(pdk, fet_1_ref.ports["multiplier_0_drain_W"], drain_1_via.ports["bottom_met_E"])
    top_level << c_route(pdk, drain_1_via.ports["top_met_S"], gate_2_via.ports["top_met_S"], extension=1.2*max(width[0],width[1]), cglayer="met2")
    top_level << straight_route(pdk, fet_2_ref.ports["multiplier_0_gate_E"], gate_2_via.ports["bottom_met_W"])
    try:
	    top_level << straight_route(pdk, fet_2_ref.ports["multiplier_0_source_W"], fet_2_ref.ports["tie_W_top_met_W"], glayer1=tie_layers2[1], fullbottom=True)
    except:
	    pass
    #Renaming Ports
    top_level.add_ports(fet_1_ref.get_ports_list(), prefix="A_")
    top_level.add_ports(fet_2_ref.get_ports_list(), prefix="B_")
    top_level.add_ports(drain_1_via.get_ports_list(), prefix="A_drain_")
    top_level.add_ports(source_1_via.get_ports_list(), prefix="A_source_")
    top_level.add_ports(gate_1_via.get_ports_list(), prefix="A_gate_")
    top_level.add_ports(drain_2_via.get_ports_list(), prefix="B_drain_")
    top_level.add_ports(gate_2_via.get_ports_list(), prefix="B_gate_")
    #add nwell
    if well == "nwell": 
        top_level.add_padding(layers=(pdk.get_glayer("nwell"),),default= 1 )
    #add tapring
    if with_substrate_tap:
        shift_amount = -prec_center(top_level.flatten())[0];
        tap_ring = tapring(pdk, enclosed_rectangle=evaluate_bbox(top_level.flatten(), padding=pdk.get_grule("nwell")['min_separation']));
        tring_ref = top_level << tap_ring;
        tring_ref.movex(destination=shift_amount);
    
    return component_snap_to_grid(rename_ports_by_orientation(top_level))



if __name__ == "__main__":
	comp = flipped_voltage_follower(ihp130, device_type='nmos')

	# comp.pprint_ports()

	comp = add_fvf_labels(comp, ihp130)

	comp.name = "FVF"

	comp.write_gds('out_FVF.gds')

	comp.show()

	print("...Running DRC...")

	drc_result = ihp130.drc(comp,comp.name)


