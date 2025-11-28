#!/headless/conda-env/miniconda3/envs/GLdev/bin/python3
from glayout import MappedPDK, sky130,gf180
from glayout import nmos, pmos, tapring,via_stack

from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory.components import text_freetype, rectangle

#from glayout.routing import c_route,L_route,straight_route
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.routing.straight_route import straight_route
from glayout.spice.netlist import Netlist

from glayout.util.port_utils import add_ports_perimeter,rename_ports_by_orientation
from glayout.util.comp_utils import evaluate_bbox, prec_center, prec_ref_center, align_comp_to_port
from glayout.util.snap_to_grid import component_snap_to_grid
from typing import Optional, Union 

###### Only Required for IIC-OSIC Docker
import os
import subprocess
from pathlib import Path
import contextlib

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


def display_component(component,path,scale = 3):
  # Save to a GDS file
  with hide:
    component.write_gds(os.path.join(path,'out.gds'))
  display_gds(os.path.join(path,'out.gds'),path,scale)

def regulated_cascode_current_mirror(
        pdk: MappedPDK,
        Width: float = 1,
        Length: Optional[float] = None,
        num_cols: int = 2,
        fingers: int = 1,
        type: Optional[str] = 'nfet',
        with_substrate_tap: Optional[bool] = False,
        with_tie: Optional[bool] = True,
        with_dummy: Optional[bool] = True,
        tie_layers: tuple[str,str]=("met2","met1"),
        show_netlist: Optional[bool] = False,
        **kwargs
    ) -> Component:
    """An instantiable regulated cascode current mirror that returns a Component object."""
    
    pdk.activate()
    maxmet_sep = pdk.util_max_metal_seperation()
    psize=(0.35,0.35)

    # Create the regulated cascoded current mirror component
    RegulatedCM = Component(name="RegulatedCM")
    Length = Length if Length is not None else pdk.get_grule('poly')['min_width']

    # Define transistor parameters
    # Add the NMOS devices
    nmos_width = 4
    nmos_length = 1
    nmos_mult = 1
    XMB10 = nmos(pdk,
                width=nmos_width,
                fingers=2,
                multipliers=nmos_mult,
                with_dummy=False,
                with_substrate_tap=True,
                length=nmos_length,
                with_tie=True,
                sd_route_topmet="met2",
                gate_route_topmet="met2")
                # with_tie=True)

    XMB11 = nmos(pdk,
                width=nmos_width,
                fingers=2*1,
                multipliers=1*nmos_mult,
                with_dummy=False,
                with_substrate_tap=True,
                length=nmos_length)

    XMB8 = nmos(pdk,
                width=nmos_width,
                fingers=2,
                multipliers=nmos_mult,
                with_dummy=False,
                with_substrate_tap=True,
                length=nmos_length,
                with_tie=True,
                sd_route_topmet="met2",
                gate_route_topmet="met2")

    XMB13 = nmos(pdk,
                width=nmos_width,
                fingers=2,
                multipliers=nmos_mult,
                with_dummy=False,
                with_substrate_tap=True,
                length=nmos_length,
                with_tie=True,
                sd_route_topmet="met2",
                gate_route_topmet="met2")
    
    XMB14 = nmos(pdk,
                width=nmos_width,
                fingers=2,
                multipliers=nmos_mult,
                with_dummy=False,
                with_substrate_tap=True,
                length=nmos_length,
                with_tie=True,
                sd_route_topmet="met2",
                gate_route_topmet="met2")

    XM12 = nmos(pdk,
                width=nmos_width,
                fingers=2,
                multipliers=nmos_mult,
                with_dummy=False,
                with_substrate_tap=True,
                length=nmos_length,
                with_tie=True,
                sd_route_topmet="met2",
                gate_route_topmet="met2")

    # Adding the references of the transistors to the top component
    fet_XMB10_ref = RegulatedCM << XMB10
    fet_XMB11_ref = RegulatedCM << XMB11
    fet_XMB8_ref = RegulatedCM << XMB8
    fet_XMB13_ref = RegulatedCM << XMB13
    fet_XMB14_ref = RegulatedCM << XMB14
    fet_XM12_ref = RegulatedCM << XM12


    # Naming each transistor reference
    fet_XMB10_ref.name = "XMB10"
    fet_XMB11_ref.name = "XMB11"
    fet_XMB8_ref.name = "XMB8"
    fet_XMB13_ref.name = "XMB13"
    fet_XMB14_ref.name = "XMB14"
    fet_XM12_ref.name = "XM12"

    
    # Add reference of each transistor to the top component
    RegulatedCM.add(fet_XMB10_ref)
    RegulatedCM.add(fet_XMB11_ref)
    RegulatedCM.add(fet_XMB8_ref)
    RegulatedCM.add(fet_XMB13_ref)
    RegulatedCM.add(fet_XMB14_ref)
    RegulatedCM.add(fet_XM12_ref)

    # Add ports of each transistor to the top component with prefixes
    RegulatedCM.add_ports(fet_XMB10_ref.get_ports_list(),prefix="rcm_XMB10_")
    RegulatedCM.add_ports(fet_XMB11_ref.get_ports_list(),prefix="rcm_XMB11_")
    RegulatedCM.add_ports(fet_XMB8_ref.get_ports_list(),prefix="rcm_XMB8_")
    RegulatedCM.add_ports(fet_XMB13_ref.get_ports_list(),prefix="rcm_XMB13_")
    RegulatedCM.add_ports(fet_XMB14_ref.get_ports_list(),prefix="rcm_XMB14_")
    RegulatedCM.add_ports(fet_XM12_ref.get_ports_list(),prefix="rcm_XM12_")

    # Get the dimensions of the transistors for placement
    fet_XMB10_dim = evaluate_bbox(fet_XMB10_ref)
    fet_XMB11_dim = evaluate_bbox(fet_XMB11_ref)
    fet_XMB8_dim = evaluate_bbox(fet_XMB8_ref)
    fet_XMB13_dim = evaluate_bbox(fet_XMB13_ref)
    fet_XMB14_dim = evaluate_bbox(fet_XMB14_ref)
    fet_XM12_dim = evaluate_bbox(fet_XM12_ref)

    # Place each transistor in the top component
    fet_XMB11_ref.movey(0.5*(fet_XMB10_dim[1]/2 -maxmet_sep - fet_XMB11_dim[1]/2))
    fet_XMB11_ref.movex(fet_XMB10_dim[0]/2 + maxmet_sep + fet_XMB11_dim[0]/2)

    fet_XMB8_ref.movey((fet_XMB10_dim[1]/2 + maxmet_sep + fet_XMB8_dim[1]/2))
    fet_XMB8_ref.movex(fet_XMB10_dim[0]/2 + maxmet_sep + fet_XMB8_dim[0]/2)

    fet_XMB13_ref.movex(fet_XMB10_dim[0]/2 + fet_XMB11_dim[0] + 4*maxmet_sep + fet_XMB13_dim[0]/2)

    fet_XMB14_ref.movex(fet_XMB10_dim[0]/2 + fet_XMB11_dim[0] + 4*maxmet_sep + fet_XMB14_dim[0]/2)
    fet_XMB14_ref.movey((fet_XMB11_dim[1]/2 + maxmet_sep + fet_XMB14_dim[1]/2))

    fet_XM12_ref.movex(fet_XMB10_dim[0]/2 + fet_XMB11_dim[0] + 6*maxmet_sep + fet_XMB14_dim[0] + fet_XM12_dim[0]/2)

    # Routing between the transistors
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    viam3m4 = via_stack(pdk, "met3", "met4", centered=True) 
    viam4m5 = via_stack(pdk, "met4", "met5", centered=True)

    # Position the vias to respective ports centre
    drain_XMB10_via = RegulatedCM << viam2m3
    drain_XMB10_via.move(RegulatedCM.ports["rcm_XMB10_multiplier_0_drain_W"].center)#.movey(-0.8*maxmet_sep) #.movex(1*maxmet_sep)
    source_XMB10_via = RegulatedCM << viam2m3
    source_XMB10_via.move(RegulatedCM.ports["rcm_XMB10_multiplier_0_source_E"].center)#.movey(0.8*maxmet_sep)
    gate_XMB10_via = RegulatedCM << viam2m3
    gate_XMB10_via.move(RegulatedCM.ports["rcm_XMB10_multiplier_0_gate_S"].center)#.movey(-0.8*maxmet_sep) 
    
    XMB10_D_XMB8_G_via = RegulatedCM << viam2m3
    XMB10_D_XMB8_G_via.movex((fet_XMB10_ref.ports["drain_E"].center[0] + fet_XMB8_ref.ports["gate_W"].center[0] - 16*maxmet_sep)/2)
    XMB10_D_XMB8_G_via.movey((fet_XMB10_ref.ports["drain_N"].center[1] + fet_XMB8_ref.ports["gate_S"].center[1] + 8*maxmet_sep)/2)
    # XMB10_D_XMB8_G_via.movey(fet_XMB10_ref.ports["drain_E"].center.y + fet_XMB8_ref.ports["gate_W"].center.y)/2
    # (prec_ref_center(fet_XMB10_ref.ports["drain_E"], fet_XMB8_ref.ports["gate_W"]))#.movey(-0.8*maxmet_sep)  

    XM12_G_XM14_S_via = RegulatedCM << viam2m3
    XM12_G_XM14_S_via.movex((fet_XM12_ref.ports["gate_E"].center[0] + fet_XMB14_ref.ports["source_W"].center[0] + 16*maxmet_sep)/2)
    XM12_G_XM14_S_via.movey((fet_XM12_ref.ports["gate_N"].center[1] + fet_XMB14_ref.ports["source_S"].center[1] + 12*maxmet_sep)/2)
    # XM12_G_XM14_S_via

    drain_XMB11_via = RegulatedCM << viam2m3
    # drain_XMB11_via.move(RegulatedCM.ports["rcm_XMB11_multiplier_0_drain_W"].center)#.movey(-0.8*maxmet_sep) #.movex(1*maxmet_sep)
    # drain_XMB11_via.move(RegulatedCM.ports["rcm_XMB11_drain_W"].center)
    drain_XMB11_via.move(fet_XMB11_ref.ports["drain_W"].center)
    source_XMB11_via = RegulatedCM << viam2m3
    # source_XMB11_via.move(RegulatedCM.ports["rcm_XMB11_multiplier_0_source_E"].center)#.movey(0.8*maxmet_sep)
    source_XMB11_via.move(fet_XMB11_ref.ports["source_W"].center)
    gate_XMB11_via = RegulatedCM << viam2m3
    # gate_XMB11_via.move(RegulatedCM.ports["rcm_XMB11_multiplier_0_gate_S"].center)#.movey(-0.8*maxmet_sep)    
    gate_XMB11_via.move(fet_XMB11_ref.ports["gate_W"].center)  

    drain_XMB8_via = RegulatedCM << viam2m3
    # drain_XMB8_via.move(RegulatedCM.ports["rcm_XMB8_multiplier_0_drain_W"].center)#.movey(-0.8*maxmet_sep) #.movex(1*maxmet_sep)
    drain_XMB8_via.move(fet_XMB8_ref.ports["drain_W"].center)
    source_XMB8_via = RegulatedCM << viam2m3
    # source_XMB8_via.move(RegulatedCM.ports["rcm_XMB8_multiplier_0_source_E"].center)#.movey(0.8*maxmet_sep)
    source_XMB8_via.move(fet_XMB8_ref.ports["source_W"].center)
    gate_XMB8_via = RegulatedCM << viam2m3
    # gate_XMB8_via.move(RegulatedCM.ports["rcm_XMB8_multiplier_0_gate_S"].center)#.movey(-0.8*maxmet_sep)    
    gate_XMB8_via.move(fet_XMB8_ref.ports["gate_W"].center) 

    drain_XMB13_via = RegulatedCM << viam2m3
    drain_XMB13_via.move(fet_XMB13_ref.ports["drain_W"].center)
    source_XMB13_via = RegulatedCM << viam2m3
    source_XMB13_via.move(fet_XMB13_ref.ports["source_W"].center)
    gate_XMB13_via = RegulatedCM << viam2m3
    gate_XMB13_via.move(fet_XMB13_ref.ports["gate_W"].center)   

    drain_XMB14_via = RegulatedCM << viam2m3
    drain_XMB14_via.move(fet_XMB14_ref.ports["drain_W"].center)
    source_XMB14_via = RegulatedCM << viam2m3
    source_XMB14_via.move(fet_XMB14_ref.ports["source_W"].center)
    gate_XMB14_via = RegulatedCM << viam2m3
    gate_XMB14_via.move(fet_XMB14_ref.ports["gate_W"].center)   

    drain_XM12_via = RegulatedCM << viam2m3
    drain_XM12_via.move(fet_XM12_ref.ports["drain_W"].center)
    source_XM12_via = RegulatedCM << viam2m3
    source_XM12_via.move(fet_XM12_ref.ports["source_W"].center)
    gate_XM12_via = RegulatedCM << viam2m3
    gate_XM12_via.move(fet_XM12_ref.ports["gate_W"].center)




    # with open("ports_RegulatedCM.csv" , "w") as f:
    #     with contextlib.redirect_stdout(f):
    #         RegulatedCM.pprint_ports()
            # fet_XMB10_ref.pprint_ports()
    # RegulatedCM.pprint_ports()
    # XMB10_D_XMB8_G_via.pprint_ports()

    #Routing
    ## XMB10 Gate to XMB11 Drain; XMB10 Source to XMB11 Source; XMB10 source to V_AUX; 
    RegulatedCM << straight_route(pdk, RegulatedCM.ports["rcm_XMB10_source_E"], fet_XMB11_ref.ports["source_W"])
    RegulatedCM << L_route(pdk, fet_XMB10_ref.ports["gate_E"], fet_XMB11_ref.ports["drain_S"])
    ## XMB8 Source to XMB11 Drain
    RegulatedCM << c_route(pdk, fet_XMB8_ref.ports["source_E"], fet_XMB11_ref.ports["drain_E"], extension = 10*maxmet_sep)
    ## XMB8 Gate to XMB10 Drain
    # RegulatedCM << L_route(pdk, fet_XMB8_ref.ports["gate_W"], fet_XMB10_ref.ports["drain_N"])
    RegulatedCM << L_route(pdk, fet_XMB8_ref.ports["gate_W"], XMB10_D_XMB8_G_via.ports["bottom_met_N"])
    RegulatedCM << L_route(pdk, XMB10_D_XMB8_G_via.ports["bottom_met_S"], fet_XMB10_ref.ports["drain_E"])
    ## XMB8 Drain to XMB11 Gate
    RegulatedCM << c_route(pdk, fet_XMB8_ref.ports["drain_E"], fet_XMB11_ref.ports["gate_E"],extension = 15*maxmet_sep)
    ## XM13 Source to XM11 Source
    RegulatedCM << straight_route(pdk, fet_XMB13_ref.ports["source_W"], fet_XMB11_ref.ports["source_W"])
    ## XMB13 Gate to XMB11 Gate
    RegulatedCM << straight_route(pdk, fet_XMB13_ref.ports["gate_W"], fet_XMB11_ref.ports["gate_E"])
    ## XM13 Drain to XM14 Source
    RegulatedCM << c_route(pdk, fet_XMB13_ref.ports["drain_W"], fet_XMB14_ref.ports["source_W"], extension = 10*maxmet_sep) 
    ## XM12 Source to XM13 Source
    RegulatedCM << straight_route(pdk, fet_XM12_ref.ports["source_W"], fet_XMB13_ref.ports["source_W"])
    ## XM12 Gate to XM13 Drain/XM14 Source
    RegulatedCM << L_route(pdk, fet_XM12_ref.ports["gate_W"], XM12_G_XM14_S_via.ports["bottom_met_S"])
    RegulatedCM << L_route(pdk, XM12_G_XM14_S_via.ports["bottom_met_N"], fet_XMB14_ref.ports["source_E"])
    ## XM12 Drain to XM14 Gate
    RegulatedCM << c_route(pdk, fet_XM12_ref.ports["drain_E"], fet_XMB14_ref.ports["gate_E"], extension = 10*maxmet_sep)

    ##xm12 drain to v_aux 
    RegulatedCM << c_route(pdk, fet_XM12_ref.ports["drain_N"], fet_XMB10_ref.ports["drain_N"], extension = 10*maxmet_sep)



    #Add Pins
    psize = (0.5,0.5)
    move_info = list()
    vaux_label = rectangle(layer = pdk.get_glayer("met3_pin"), size=psize, centered=True).copy()
    vaux_label.add_label(text="v_aux", layer=pdk.get_glayer("met3_label"))
    # move_info.append((iref_label, RegulatedCM.ports["rcm_XMB5_drain_N"], None))
    move_info.append((vaux_label, fet_XMB10_ref.ports["drain_W"], None))

    vss_label = rectangle(layer = pdk.get_glayer("met3_pin"), size=psize, centered=True).copy()
    vss_label.add_label(text="vss", layer=pdk.get_glayer("met3_label"))
    # move_info.append((vss_label, RegulatedCM.ports["rcm_XMB10_source_S"], None))
    move_info.append((vss_label, fet_XMB10_ref.ports["source_W"], None))

    v_in_label = rectangle(layer = pdk.get_glayer("met3_pin"), size=psize, centered=True).copy()
    v_in_label.add_label(text="v_in", layer=pdk.get_glayer("met3_label"))
    # move_info.append((v_in_label, RegulatedCM.ports["rcm_XMB8_gate_N"], None))
    move_info.append((v_in_label, fet_XMB8_ref.ports["drain_W"], None))

    v_out_label = rectangle(layer = pdk.get_glayer("met3_pin"), size=psize, centered=True).copy()
    v_out_label.add_label(text="v_out", layer=pdk.get_glayer("met3_label"))
    # move_info.append((v_out_label, RegulatedCM.ports["rcm_XMB11_drain_S"], None))
    move_info.append((v_out_label, fet_XMB14_ref.ports["drain_E"], None))   

    for comp, prt, alignment in move_info:
        alignment = ('c', 'b') if alignment is None else alignment
        aligned_comp = align_comp_to_port(comp, prt, alignment=alignment)
        RegulatedCM.add(aligned_comp)
    # component = RegulatedCM.flatten()

    #let's take a look at our current state of layout
    ## To see in Klayout via Klive
    # RegulatedCM.show()

    return RegulatedCM.flatten()

if __name__ == "__main__":
	# Main function to generate the current mirror layout
    # mappedpdk, Width, Length, num_cols, fingers, transistor type
    #comp = self_biased_cascode_current_mirror(gf180, num_cols=2, Width=3, device='nfet',show_netlist=False)
    selected_pdk = gf180
    comp = regulated_cascode_current_mirror(pdk=gf180)

   
    comp.name = "CM_RegC"
    comp.show()
    ##Write the current mirror layout to a GDS file
    comp.write_gds("./CM_RegC.gds")
    
    # # #Generate the netlist for the current mirror
    # print("\n...Generating Netlist...")
    #print(comp.info["netlist"].generate_netlist())
    # # #DRC Checks
    try: 
        drc_result = selected_pdk.drc_magic(comp, comp.name, output_file=Path("DRC/"))
    except:
        drc_result = selected_pdk.drc_magic(comp, comp.name)
    print("\n...DRC Result: ", drc_result)
    # # #LVS Checks
    # #print("\n...Running LVS...")
    #netgen_lvs_result = selected_pdk.lvs_netgen(comp, comp.name,output_file_path=Path("LVS/"),copy_intermediate_files=True)        

  


    # /headless/conda-env/miniconda3/envs/GLdev/bin/python3 cm_regc.py