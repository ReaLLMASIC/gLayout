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
from typing import ClassVar, Optional, Any, Union, Literal, Iterable, TypedDict
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


# @validate_arguments
def generate_current_mirror_netlist(
	pdk: MappedPDK,
	instance_name: str,
	CM_size: tuple[float, float, int],  # (width, length, multipliers)
	drain_net_ref: str,
	drain_net_copy: str,
	source_net_ref: str,
	source_net_copy: str,
	gate_net: str,
	transistor_type: str = "nfet",
	bulk_net: str = None,
	proposed_ground: str = None,  # Proposed ground net
	dummy: bool = True,
	subckt_only: bool = False,
	show_netlist: bool = False,
	**kwargs
	) -> Netlist:
	"""Generate a netlist for a current mirror."""

	if bulk_net is None:
		bulk_net = "VDD" if transistor_type.lower() == "pfet" else "VSS"

	width = CM_size[0]
	length = CM_size[1]
	multipliers = CM_size[2]  
	fingers =  CM_size[3] # Number of fingers of the interdigitized fets
	mtop = multipliers * fingers if subckt_only else 1
	#mtop = multipliers * 2 if dummy else multipliers # Double the multiplier to account for the dummies

	model_name = pdk.models[transistor_type.lower()]

	circuit_name = instance_name
	nodes = list(set([drain_net_ref, gate_net, drain_net_copy, source_net_ref,source_net_copy,bulk_net]))  # Take only unique NET names

	source_netlist = f".subckt {circuit_name} {' '.join(nodes)}\n"

	#source_netlist += f"V{proposed_ground}1 ({proposed_ground} {bulk_net}) 0\n" #Proposed ground connection

	# Generating only two transistors (one on each side):
	source_netlist += f"XA {drain_net_ref} {gate_net} {source_net_ref} {bulk_net} {model_name} l={length} w={width} m={mtop}\n"
	source_netlist += f"XB {drain_net_copy} {gate_net} {source_net_copy} {bulk_net} {model_name} l={length} w={width} m={mtop}\n"
	if dummy:
		source_netlist += f"XDUMMY {bulk_net} {bulk_net} {bulk_net} {bulk_net} {model_name} l={length} w={width} m={mtop}\n"
	source_netlist += ".ends " + circuit_name

	instance_format = "X{name} {nodes} {circuit_name} l={length} w={width} m={mult}"

	topnet=Netlist(
		circuit_name=circuit_name,
		nodes=nodes,
		source_netlist=source_netlist,
		instance_format=instance_format,
		parameters={
			"model": model_name,
			"width": width,
			"length": length,
			'mult': multipliers,},
		)
	if show_netlist:
		generated_netlist_for_lvs = topnet.generate_netlist()
		print(f"Generated netlist :\n", generated_netlist_for_lvs)

		file_path_local_storage = "./gen_netlist.txt"
		try:
			with open(file_path_local_storage, 'w') as file:
				file.write(generated_netlist_for_lvs)
		except:
			print(f"Verify the file availability and type: ", generated_netlist_for_lvs, type(generated_netlist_for_lvs))
	return topnet

# @validate_arguments
def current_mirror_base(
        pdk: MappedPDK,
        Width: float = 1,
        Length: Optional[float] = None,
        num_cols: int = 2,
        fingers: int = 1,
        type: Optional[str] = 'nfet',
        with_substrate_tap: Optional[bool] = False,
        with_tie: Optional[bool] = True,
        tie_layers: tuple[str,str]=("met2","met1"),
        with_dummy: Optional[bool] = True,
        show_netlist: Optional[bool] = False,
        **kwargs
    ) -> Component:
    
    """An instantiable current mirror that returns a Component object. 
    The current mirror could be a two transistor interdigitized structure with a shorted source and gate.
    It can be instantiated with either nmos or pmos devices. It can also be instantiated with a dummy device, a substrate tap, and a tie layer, and is centered at the origin.
    Transistor A acts as the reference and Transistor B acts as the mirror fet
    This current mirror is used to generate a exact copy of the reference current.
    [TODO] Needs to be checked for both pfet and nfet configurations.
    [TODO] It will be updated with multi-leg or stackked length parametrization in future.
    [TODO] There will also be a Regulated Cascoded block added to it. 

	Args:
		pdk (MappedPDK): the process design kit to use
        Width (float): width of the interdigitized fets (same for both reference and mirror)
        Length (float): length of the interdigitized fets (same for both reference and mirror) 
        As Default, Set to None to use the minimum length of the technology
		numcols (int): number of columns of the interdigitized fets
        fingers: Number of fingers of interdigitized fets (same for both reference and mirror)
		device (str): nfet or pfet (can only interdigitize one at a time with this option)
		with_dummy (bool): True places dummies on either side of the interdigitized fets
		with_substrate_tap (bool): boolean to decide whether to place a substrate tapring
		with_tie (bool): boolean to decide whether to place a tapring for tielayer
		tie_layers (tuple[str,str], optional): the layers to use for the tie. Defaults to ("met2","met1").
		**kwargs: The keyword arguments are passed to the two_nfet_interdigitized or two_pfet_interdigitized functions and need to be valid arguments that can be accepted by the multiplier 
	Returns:
		Component: a current mirror component object
	"""
    pdk.activate()
    maxmet_sep = pdk.util_max_metal_seperation()
    # Create the current mirror component
    CurrentMirror = Component(name="CurrentMirror")
    Length = Length if Length is not None else pdk.get_grule('poly')['min_width']
    
    # Create the interdigitized fets
    if type.lower() =="pfet" or type.lower() =="pmos":
        currm= two_pfet_interdigitized(pdk,numcols=num_cols,width=Width,length=Length,fingers=fingers,dummy=with_dummy,with_substrate_tap=False,with_tie=False)
        well, sdglayer = "nwell", "p+s/d"
    elif type.lower() =="nfet" or type.lower() =="nmos":
        currm= two_nfet_interdigitized(pdk,numcols=num_cols,width=Width,length=Length,fingers=fingers,dummy=with_dummy,with_substrate_tap=False,with_tie=False)
        well, sdglayer = "pwell", "n+s/d"
    else:
        raise ValueError("type must be either nfet or pfet")
        
        
    # Add the interdigitized fets to the current mirror top component
    currm_ref = prec_ref_center(currm)
    CurrentMirror.add(currm_ref)
    CurrentMirror.add_ports(currm_ref.get_ports_list(),prefix="currm_")
    
    #Routing
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    drain_A_via  = CurrentMirror << viam2m3
    drain_A_via.move(CurrentMirror.ports["currm_A_0_drain_W"].center).movex(-2*maxmet_sep)

    
    drain_B_via  = CurrentMirror << viam2m3
    drain_B_via.move(CurrentMirror.ports[f"currm_B_{num_cols - 1}_drain_E"].center).movex(+2*maxmet_sep)

    #####################
    CurrentMirror << straight_route(pdk,currm_ref.ports["A_0_drain_E"], drain_A_via.ports["bottom_met_W"])
    CurrentMirror << straight_route(pdk,currm_ref.ports[f"B_{num_cols-1}_drain_E"], drain_B_via.ports["bottom_met_W"])
    ##################### 
    #CurrentMirror << straight_route(pdk,currm_ref.ports["A_0_source_E"], source_A_via.ports["bottom_met_W"])
    #CurrentMirror << straight_route(pdk,currm_ref.ports["B_0_source_E"], source_B_via.ports["bottom_met_W"])

    source_short = CurrentMirror << c_route(pdk, currm.ports['A_source_E'], currm.ports['B_source_E'],extension=5*maxmet_sep, viaoffset=False)
   
    #source_short =  CurrentMirror << straight_route(pdk, source_A_via.ports["top_met_N"], source_B_via.ports["top_met_S"])
    #,extension=1.2*max(Width,Width), width1=psize[0], width2=ps, cwidth=0.32, e1glayer="met3", e2glayer="met3", cglayer="met2")
    #####################
    # #connecting the Drian of A to gate short
    dg = CurrentMirror << L_route(pdk,drain_A_via.ports["top_met_S"],CurrentMirror.ports["currm_A_0_gate_W"])
    gate_short =  CurrentMirror << L_route(pdk, dg.ports["top_met_S"], CurrentMirror.ports["currm_B_0_gate_W"])
	# Adding tapring
    if with_tie:
        tap_sep = max(maxmet_sep,
            pdk.get_grule("active_diff", "active_tap")["min_separation"])
        tap_sep += pdk.get_grule(sdglayer, "active_tap")["min_enclosure"]
        tap_encloses = (
        2 * (tap_sep + currm.xmax),
        2 * (tap_sep + currm.ymax),
        )
        tie_ref = CurrentMirror << tapring(pdk, enclosed_rectangle = tap_encloses, sdlayer = sdglayer, horizontal_glayer = tie_layers[0], vertical_glayer = tie_layers[1])
        CurrentMirror.add_ports(tie_ref.get_ports_list(), prefix="welltie_")
        #tie_ref.pprint_ports()
        
        # for absc in CurrentMirror.ports.keys():
        #     if len(absc.split("_")) <= 10:
        #         if set(["currm","dummy","B","gsdcon"]).issubset(set(absc.split("_"))):
        #             print(absc+"\n")
    
  
    # add the substrate tap if specified
    if with_substrate_tap:
        subtap_sep = pdk.get_grule("dnwell", "active_tap")["min_separation"]
        subtap_enclosure = (
            2.5 * (subtap_sep + currm.xmax),
            2.5 * (subtap_sep + currm.ymax),
        )
        subtap_ring = CurrentMirror << tapring(pdk, enclosed_rectangle = subtap_enclosure, sdlayer = "p+s/d", horizontal_glayer = tie_layers[0], vertical_glayer = tie_layers[1])
        CurrentMirror.add_ports(subtap_ring.get_ports_list(), prefix="substrate_tap_")
        
    # add well
    CurrentMirror.add_padding(default=pdk.get_grule(well, "active_tap")["min_enclosure"],layers=[pdk.get_glayer(well)])
    CurrentMirror = add_ports_perimeter(CurrentMirror, layer = pdk.get_glayer(well), prefix="well_")

    try:
        CurrentMirror << straight_route(pdk, CurrentMirror.ports["currm_A_0_dummy_L_gsdcon_top_met_W"],CurrentMirror.ports["welltie_W_top_met_W"],glayer2="met1")
    except KeyError:
        pass
    try:
        CurrentMirror << straight_route(pdk, CurrentMirror.ports[f'currm_B_{num_cols - 1}_dummy_R_gsdcon_top_met_E'], CurrentMirror.ports["welltie_E_top_met_E"], glayer2="met1")
    except KeyError:
        pass

    
    #Connecting the source of the fets to the bulk ???
    #src2bulk=CurrentMirror << straight_route(pdk, source_short.ports["con_N"],CurrentMirror.ports["welltie_N_top_met_N"])
    
    ##The default naming scheme of ports in GDSFactory
    ##e1=West, e2=North, e3=East, e4=South. The default naming scheme of ports in GDSFactory

    # ###########################################################
    # Irefpin = CurrentMirror << rectangle(size=psize,layer=pdk.get_glayer("met3"),centered=True)
    # Irefpin.move(drain_A_via.center).movey(0.2*evaluate_bbox(currm_ref)[0])
    # CurrentMirror << straight_route(pdk, drain_A_via.ports["top_met_N"],Irefpin.ports["e4"], glayer2="met3")
    
    # Icopypin = CurrentMirror << rectangle(size=psize,layer=pdk.get_glayer("met3"),centered=True)
    # Icopypin.move(drain_A_via.center).movex(-1+Length).movey(0.2*evaluate_bbox(currm_ref)[0])
    # CurrentMirror << straight_route(pdk, drain_B_via.ports["top_met_N"],Icopypin.ports["e4"], glayer2="met3")
    
    # bulkpin = CurrentMirror << rectangle(size=psize,layer=pdk.get_glayer("met3"),centered=True)
    # bulkpin.move(source_A_via.center).movey(0.2*evaluate_bbox(currm_ref)[0])
    # CurrentMirror << straight_route(pdk, src2bulk["route_N"],bulkpin.ports["e4"], glayer2="met3")
    # ###########################################################
    
    CurrentMirror.add_ports(drain_A_via.get_ports_list(), prefix="A_drain_")
    CurrentMirror.add_ports(drain_B_via.get_ports_list(), prefix="B_drain_")
    CurrentMirror.add_ports(gate_short.get_ports_list(), prefix="gateshortports_")
    CurrentMirror.add_ports(source_short.get_ports_list(), prefix="sourceshortports_")

    CurrentMirror = component_snap_to_grid(rename_ports_by_orientation(CurrentMirror))

    CurrentMirror.info["netlist"] = generate_current_mirror_netlist(
                                    pdk=pdk,
                                    instance_name=CurrentMirror.name,
                                    CM_size= (Width, Length, num_cols,fingers),  # (width, length, multipliers, fingers)
                                    transistor_type=type,
                                    drain_net_ref="VREF",  # Input drain connected to IREF
                                    drain_net_copy="VCOPY", # Output drain connected to ICOPY
                                    gate_net="VREF",      # Gate connected to VREF 
                                    source_net_ref="VSS" if type.lower()=="nfet" else "VDD",    # Source connected to VSS
                                    source_net_copy="VSS" if type.lower()=="nfet" else "VDD",    # Source connected to VSS
                                    bulk_net= "VB",
                                    subckt_only=True,
                                    show_netlist=show_netlist,
                                    )

    return CurrentMirror

def add_cm_labels(cm_in: Component,
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
    move_info.append((vsslabel,cm_in.ports["sourceshortports_con_N"],None))
    
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

# import sys
# sys.path.append('../../elementary/current_mirror/')

# from current_mirror import current_mirror,add_cm_labels

# comp = current_mirror(gf180)
# # comp.pprint_ports()
# comp = add_cm_labels(comp,gf180)
# comp.name = "CM"
# comp.show()

if __name__ == "__main__":
    selected_pdk=gf180
    comp = current_mirror_base(selected_pdk, num_cols=2, Length=5*selected_pdk.get_grule('poly')['min_width'],Width=3.2, device='nfet',show_netlist=False)
    #comp.pprint_ports()
    comp = add_cm_labels(comp, pdk=selected_pdk)
    comp.name = "CM"
    comp.show()
    ##Write the current mirror layout to a GDS file
    # comp.write_gds("./CM.gds")
    
    # # #Generate the netlist for the current mirror
    # print("\n...Generating Netlist...")
    print(comp.info["netlist"].generate_netlist())
    # # #DRC Checks
    drc_result = selected_pdk.drc_magic(comp, comp.name,output_file=Path("DRC/"))
    # # #LVS Checks
    # #print("\n...Running LVS...")
    #netgen_lvs_result = selected_pdk.lvs_netgen(comp, comp.name,output_file_path=Path("LVS/"),copy_intermediate_files=True)        
