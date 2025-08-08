from glayout import MappedPDK, sky130,gf180
from glayout import nmos, pmos, tapring,via_stack

from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory.components import text_freetype, rectangle

from glayout.routing import c_route,L_route,straight_route
from glayout.spice.netlist import Netlist

from glayout.util.port_utils import add_ports_perimeter,rename_ports_by_orientation
from glayout.util.comp_utils import evaluate_bbox, prec_center, prec_ref_center, align_comp_to_port
from glayout.util.snap_to_grid import component_snap_to_grid
from typing import Optional, Union 

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

####################Import the Base structure#######################
from cm_prim import current_mirror_base

def generate_self_biased_current_mirror_netlist(
    names: str = "SelfBiasedCurrentMirror",
    regulator: Component = None,
    base: Component = None,
    show_netlist : Optional[bool] = False,
    ) -> Netlist:
    """Generate a netlist for a current mirror."""
    
    topnet = Netlist(
        circuit_name=names,
        nodes=['VREF', 'VCOPY', 'VSS', 'VB'],
    )
    
    base_ref = topnet.connect_netlist(
        base.info['netlist'],
        [('VSS', 'VSS') ]
    )

    regulator_ref = topnet.connect_netlist(
        regulator.info['netlist'],
        [('VREF', 'VREF'), ('VCOPY', 'VCOPY'), ('VSS', 'VSS'),('VB', 'VB')]
    )
    

    if show_netlist:
        generated_netlist_for_lvs = topnet.generate_netlist()
        print(f"Generated netlist :\n", generated_netlist_for_lvs)

        file_path_local_storage = "./gen_netlist.txt"
        try:
            with open(file_path_local_storage, 'w') as file:
                file.write(generated_netlist_for_lvs)
        except:
            print(f"Verify the file availability and device: ", generated_netlist_for_lvs, device(generated_netlist_for_lvs))
    return topnet

# @validate_arguments
def self_biased_cascode_current_mirror(
        pdk: MappedPDK,
        Width: float = 1,
        Length: Optional[float] = None,
        num_cols: int = 2,
        fingers: int = 1,
        device: Optional[str] = 'nfet',
        with_substrate_tap: Optional[bool] = False,
        with_tie: Optional[bool] = True,
        with_dummy: Optional[bool] = True,
        tie_layers: tuple[str,str]=("met2","met1"),
        show_netlist: Optional[bool] = False,
        **kwargs
    ) -> Component:
    """An instantiable self biased casoded current mirror that returns a Component object."""
    
    pdk.activate()
    maxmet_sep = pdk.util_max_metal_seperation()
    psize=(0.35,0.35)
    
    # Create the current mirror component
    SBCurrentMirror = Component(name="SBCurrentMirror")
    Length = Length if Length is not None else pdk.get_grule('poly')['min_width']
    
    # Create the interdigitized fets
    if device.lower() =="pfet" or device.lower() =="pmos":
        top_currm=two_pfet_interdigitized(pdk,numcols=num_cols,width=Width,length=Length,fingers=fingers,dummy=with_dummy,with_substrate_tap=False,with_tie=False)
        well, sdglayer = "nwell", "p+s/d"
    elif device.lower() =="nfet" or device.lower() =="nmos":
        top_currm= two_nfet_interdigitized(pdk,numcols=num_cols,width=Width,length=Length,fingers=fingers,dummy=with_dummy,with_substrate_tap=False,with_tie=False)
        well, sdglayer = "pwell", "n+s/d"
    else:
        raise ValueError("device must be either nfet or pfet")
        
    # Add the interdigitized fets to the current mirror top component
    top_currm_ref = prec_ref_center(top_currm)
    SBCurrentMirror.add(top_currm_ref)
    SBCurrentMirror.add_ports(top_currm_ref.get_ports_list(),prefix="top_currm_")

    #Routing
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    
    topA_drain_via  = SBCurrentMirror << viam2m3
    topA_drain_via.move(SBCurrentMirror.ports[f"top_currm_A_0_drain_W"].center).movex(-3*maxmet_sep)
    topA_source_via  = SBCurrentMirror << viam2m3
    topA_source_via.move(SBCurrentMirror.ports[f"top_currm_A_0_source_W"].center).movex(-2*maxmet_sep)

    topB_drain_via  = SBCurrentMirror << viam2m3
    topB_drain_via.move(SBCurrentMirror.ports[f"top_currm_B_{num_cols - 1}_drain_E"].center).movex(+3*maxmet_sep)
    
    topB_source_via  = SBCurrentMirror << viam2m3
    topB_source_via.move(SBCurrentMirror.ports[f"top_currm_B_{num_cols - 1}_source_E"].center).movex(+2*maxmet_sep)
    
    #####################
    SBCurrentMirror << straight_route(pdk,top_currm_ref.ports["A_0_drain_W"], topA_drain_via.ports["bottom_met_E"])
    SBCurrentMirror << straight_route(pdk,top_currm_ref.ports["B_0_drain_W"], topB_drain_via.ports["bottom_met_E"])
    ##################### 
    SBCurrentMirror << straight_route(pdk,top_currm_ref.ports["A_0_source_E"], topA_source_via.ports["bottom_met_W"])
    SBCurrentMirror << straight_route(pdk,top_currm_ref.ports["B_0_source_E"], topB_source_via.ports["bottom_met_W"])
    
    # source_short =  SBCurrentMirror << straight_route(pdk, topA_source_via.ports["top_met_N"], topB_source_via.ports["top_met_S"])
    # ,extension=1.2*max(Width,Width), width1=psize[0], width2=ps, cwidth=0.32, e1glayer="met3", e2glayer="met3", cglayer="met2")
    # ####################
    gate_short =  SBCurrentMirror << c_route(pdk, top_currm_ref.ports[f"A_{num_cols - 1}_gate_E"], top_currm_ref.ports[f"B_{num_cols - 1}_gate_E"],cglayer="met2")
    SBCurrentMirror << L_route(pdk,top_currm_ref.ports[f"A_{num_cols - 1}_drain_E"],gate_short.ports["con_N"])
    
    ## Adding the Bottom Current Mirror
    BCM = current_mirror_base(pdk=pdk, Width=Width, Length=Length, num_cols=num_cols, device=device,with_tie=False)
    bottom_cm_ref= prec_ref_center(BCM)
    bottom_cm_ref.move(top_currm_ref.center).movey(-(2*maxmet_sep)-evaluate_bbox(top_currm_ref)[1])
   
    # #bottom_cm_ref.pprint_ports()

    SBCurrentMirror.add(bottom_cm_ref)
    SBCurrentMirror.add_ports(bottom_cm_ref.get_ports_list(), prefix="bottom_cm_")
    
    # ##############################
    
    SBCurrentMirror << L_route(pdk,topA_source_via.ports["top_met_W"], bottom_cm_ref.ports["A_drain_top_met_N"])
    SBCurrentMirror << L_route(pdk,topB_source_via.ports["top_met_E"], bottom_cm_ref.ports["B_drain_top_met_N"])


    # Adding tapring
    if with_tie:
        tap_sep = max(maxmet_sep,
            pdk.get_grule("active_diff", "active_tap")["min_separation"])
        tap_sep += pdk.get_grule(sdglayer, "active_tap")["min_enclosure"]
        tap_encloses = (
        2 * (tap_sep + SBCurrentMirror.xmax),
        2 * (tap_sep + SBCurrentMirror.ymax + BCM.ymax),
        )
        tie_ref = SBCurrentMirror << tapring(pdk, enclosed_rectangle = tap_encloses, sdlayer = sdglayer, horizontal_glayer = tie_layers[0], vertical_glayer = tie_layers[1])
        tie_ref.movey(-(BCM.ymax+tap_sep));
        SBCurrentMirror.add_ports(tie_ref.get_ports_list(), prefix="welltie_")
        ##tie_ref.pprint_ports()
        
        # for absc in CurrentMirror.ports.keys():
        #     if len(absc.split("_")) <= 10:
        #         if set(["currm","dummy","B","gsdcon"]).issubset(set(absc.split("_"))):
        #             print(absc+"\n")
    
  
    #     # add the substrate tap if specified
    #     if with_substrate_tap:
    #         subtap_sep = pdk.get_grule("dnwell", "active_tap")["min_separation"]
    #         subtap_enclosure = (
    #             2.5 * (subtap_sep + SBCurrentMirror.xmax),
    #             2.5 * (subtap_sep + SBCurrentMirror.ymax),
    #         )
    #         subtap_ring = SBCurrentMirror << tapring(pdk, enclosed_rectangle = subtap_enclosure, sdlayer = "p+s/d", horizontal_glayer = tie_layers[0], vertical_glayer = tie_layers[1])
    #         SBCurrentMirror.add_ports(subtap_ring.get_ports_list(), prefix="substrate_tap_")
            
    #     # add well
    #     SBCurrentMirror.add_padding(default=pdk.get_grule(well, "active_tap")["min_enclosure"],layers=[pdk.get_glayer(well)])
    #     SBCurrentMirror = add_ports_perimeter(SBCurrentMirror, layer = pdk.get_glayer(well), prefix="well_")
    
    #     try:
    #         SBCurrentMirror << straight_route(pdk, SBCurrentMirror.ports["top_currm_A_0_dummy_L_gsdcon_top_met_W"],SBCurrentMirror.ports["welltie_W_top_met_W"],glayer2="met1")
    #     except KeyError:
    #         pass
    #     try:
    #         SBCurrentMirror << straight_route(pdk, SBCurrentMirror.ports[f'top_currm_B_{num_cols - 1}_dummy_R_gsdcon_top_met_E'], SBCurrentMirror.ports["welltie_E_top_met_E"], glayer2="met1")
    #     except KeyError:
    #         pass
        
    #SBCurrentMirror.add_ports(topA_drain_via.get_ports_list(), prefix="A_drain_")
    #SBCurrentMirror.add_ports(topB_drain_via.get_ports_list(), prefix="B_drain_")

    
    ##############################
    # # Adding the Top Current Mirror Netlist
    # topcurrm.info["netlist"] = generate_current_mirror_netlist(
    #                                 pdk=pdk,
    #                                 instance_name="TopCurrentMirror",
    #                                 CM_size= (Width, Length, num_cols,fingers),  # (width, length, multipliers, fingers)
    #                                 transistor_device=device,
    #                                 drain_net_ref="IREF",  # Input drain connected to VREF 
    #                                 drain_net_copy="ICOPY", # Output drain connected to VCOPY
    #                                 gate_net="IREF",      # Gate connected to VREF 
    #                                 source_net_ref="INTA" ,
    #                                 source_net_copy="INTB" ,
    #                                 proposed_ground= "VSS" if device=="nfet" else "VDD", #Proposed ground should also change
    #                                 subckt_only=True,
    #                                 show_netlist=False,
    #                                 )
    
    # SBCurrentMirror.info["netlist"] = generate_self_biased_current_mirror_netlist(
    #                                 names=SBCurrentMirror.name,
    #                                 regulator=topcurrm,
    #                                 base=BCM,
    #                                 show_netlist=False,
    #                                 )

    return rename_ports_by_orientation(component_snap_to_grid(SBCurrentMirror))

    
def add_sbcm_labels(cm_in: Component,
                pdk: MappedPDK 
                ) -> Component:
	
    cm_in.unlock()

    psize=(0.35,0.35)
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    
    # vref
    vreflabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    vreflabel.add_label(text="VREF",layer=pdk.get_glayer("met3_label"))
    move_info.append((vreflabel,cm_in.ports["A_drain_top_met_N"],None))
    
    # vcopy
    vcopylabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    vcopylabel.add_label(text="VCOPY",layer=pdk.get_glayer("met3_label"))
    move_info.append((vcopylabel,cm_in.ports["B_drain_top_met_N"],None))

    # vss
    vsslabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    vsslabel.add_label(text="VSS",layer=pdk.get_glayer("met3_label"))
    move_info.append((vsslabel,cm_in.ports["bottom_cm_sourceshortports_con_N"],None))
    
    # VB
    vblabel = rectangle(layer=pdk.get_glayer("met3_pin"),size=psize,centered=True).copy()
    vblabel.add_label(text="VB",layer=pdk.get_glayer("met3_label"))
    move_info.append((vblabel,cm_in.ports["welltie_N_top_met_N"], None))
    
    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        cm_in.add(compref)
    return cm_in.flatten() 



if __name__ == "__main__":
    selected_pdk=gf180
    comp = self_biased_cascode_current_mirror(selected_pdk, num_cols=2, Length=5*selected_pdk.get_grule('poly')['min_width'],Width=3.2, device='nfet',show_netlist=False)
    #comp.pprint_ports()
    #comp = add_sbcm_labels(comp, pdk=selected_pdk)
    comp.name = "CM"
    comp.show()
    ##Write the current mirror layout to a GDS file
    # comp.write_gds("./CM.gds")
    
    # # #Generate the netlist for the current mirror
    # print("\n...Generating Netlist...")
    #print(comp.info["netlist"].generate_netlist())
    # # #DRC Checks
    drc_result = selected_pdk.drc_magic(comp, comp.name,output_file=Path("DRC/"))
    # # #LVS Checks
    # #print("\n...Running LVS...")
    #netgen_lvs_result = selected_pdk.lvs_netgen(comp, comp.name,output_file_path=Path("LVS/"),copy_intermediate_files=True)        

  