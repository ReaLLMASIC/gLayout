from gdsfactory.cell import cell
from gdsfactory.component import Component
from gdsfactory.components.rectangle import rectangle
from glayout.pdk.mappedpdk import MappedPDK
from typing import Optional
from glayout.primitives.via_gen import via_array
from glayout.util.comp_utils import prec_array, to_decimal, to_float, evaluate_bbox
from glayout.util.port_utils import rename_ports_by_orientation, add_ports_perimeter, print_ports
from pydantic import validate_arguments
from glayout.routing.straight_route import straight_route
from decimal import ROUND_UP, Decimal
from glayout.spice import Netlist

@validate_arguments
def __get_mimcap_layerconstruction_info(pdk: MappedPDK) -> tuple[str,str]:
	"""returns the glayer metal below and glayer metal above capmet
	args: pdk
	"""
	capmettop = pdk.layer_to_glayer(pdk.get_grule("capmet")["capmettop"])
	capmetbottom = pdk.layer_to_glayer(pdk.get_grule("capmet")["capmetbottom"])
	pdk.has_required_glayers(["capmet",capmettop,capmetbottom])
	pdk.activate()
	return capmettop, capmetbottom

def __generate_mimcap_netlist(pdk: MappedPDK, size: tuple[float, float]) -> Netlist:
	return Netlist(
		circuit_name="MIMCap",
		nodes = ['V1', 'V2'],
		source_netlist=""".subckt {circuit_name} {nodes} l=1 w=1
X1 V1 V2 {model} l={{l}} w={{w}}
.ends {circuit_name}""",
		instance_format="X{name} {nodes} {circuit_name} l={length} w={width}",
		parameters={
			'model': pdk.models['mimcap'],
			'length': size[0],
			'width': size[1]
		}
	)

def __generate_mimcap_array_netlist(mimcap_netlist: Netlist, num_caps: int) -> Netlist:
	arr_netlist = Netlist(
		circuit_name="MIMCAP_ARR",
		nodes = ['V1', 'V2']
	)

	for _ in range(num_caps):
		arr_netlist.connect_netlist(
			mimcap_netlist,
			[]
		)

	return arr_netlist

#@cell
def mimcap(
    pdk: MappedPDK, size: tuple[float,float]=(5.0, 5.0), option: str = "B"
) -> Component:
    """create a MIM capacitor according to GF180MCU Option A or Option B
    
    MIM Option A structure (Metal3-Metal2 stack):
    - FuseTop layer defines the top plate of MIM capacitor
    - Metal3 forms the actual top plate 
    - CAP_MK defines the dielectric layer
    - Metal2 forms the bottom plate
    - For 3 metal layer processes
    
    MIM Option B structure (Metal5-Metal4 stack):
    - FuseTop layer defines the top plate area
    - Metal5 (top metal) forms the actual top plate 
    - CAP_MK defines the dielectric
    - Metal4 (bottom metal) forms the bottom plate
    - MIM_L_MK marks the capacitor's length dimension
    - For 4+ metal layer processes
    
    args:
    pdk=pdk to use
    size=tuple(float,float) size of cap
    option=str either "A" for Metal3-Metal2 or "B" for Metal5-Metal4 (default: "B")
    
    ports:
    top_met_...all edges, this is the top metal plate
    bottom_met_...all edges, this is the bottom metal plate
    """
    size = pdk.snap_to_2xgrid(size)
    
    # Validate option parameter - default to Option B if invalid
    if option not in ["A", "B"]:
        print(f"Warning: Invalid option '{option}'. Defaulting to Option B")
        option = "B"
    
    # Minimum area check per MIMTM.8a (5*5 um2)
    min_area = 25.0  # 5*5 um2
    if size[0] * size[1] < min_area:
        print(f"Warning: MIM cap area {size[0]*size[1]:.2f} um2 is below minimum {min_area} um2")
    
    # Maximum area check per MIMTM.8b (100*100 um2)
    max_area = 10000.0  # 100*100 um2
    if size[0] * size[1] > max_area:
        raise ValueError(f"MIM cap area {size[0]*size[1]:.2f} um2 exceeds maximum {max_area} um2")
    
    # Set layer construction based on option
    if option == "A":
        # Option A: Metal3-Metal2 stack (for 3 metal layer processes)
        capmettop = "met3"
        capmetbottom = "met2"
    else:  # option == "B"
        # Option B: Metal5-Metal4 stack (for 4+ metal layer processes)
        capmettop = "met5" 
        capmetbottom = "met4"
    
    # Create main component
    mim_cap = Component()
    
    # 1. Create CAP_MK layer - dielectric layer (common to both options)
    cap_mk_ref = mim_cap << rectangle(
        size=size, 
        layer=pdk.get_glayer("capmet"), 
        centered=True
    )
    
    # 2. Create top and bottom metal plates with via connections
    top_met_ref = mim_cap << via_array(
        pdk, capmetbottom, capmettop, size=size, minus1=True, lay_bottom=False
    )
    
    # 3. Create bottom metal plate with proper enclosure
    # Per design rules: Minimum bottom plate overlap of top plate = 0.6um
    try:
        bottom_met_enclosure = pdk.get_grule(capmetbottom, "capmet")["min_enclosure"]
    except (KeyError, NotImplementedError):
        bottom_met_enclosure = 0.6  # Default fallback
    
    bottom_met_enclosure = max(bottom_met_enclosure, 0.6)  # Ensure minimum 0.6um
    
    mim_cap.add_padding(
        layers=(pdk.get_glayer(capmetbottom),), 
        default=bottom_met_enclosure
    )
    
    # 4. Add FuseTop layer - required for both options (defines the MIM area)
    fusetop_ref = mim_cap << rectangle(
        size=size, 
        layer=pdk.layers["fusetop"], 
        centered=True
    )
    
    # 5. Add option-specific layers
    if option == "B":
        # Option B specific: Add MIM_L_MK layer (marks the capacitor length)
        current_size = evaluate_bbox(mim_cap)
        mim_l_mk_size = (
            current_size[0] + 0.2,  # Add 0.1um margin on each side
            current_size[1] + 0.2
        )
        
        mim_l_mk_ref = mim_cap << rectangle(
            size=mim_l_mk_size,
            layer=pdk.layers["MIM_L_MK"],
            centered=True
        )
    # Option A: Only needs FuseTop, CAP_MK, and metal layers (no MIM_L_MK)
    
    # Create ports
    mim_cap = add_ports_perimeter(
        mim_cap, 
        layer=pdk.get_glayer(capmetbottom), 
        prefix="bottom_met_"
    )
    mim_cap.add_ports(top_met_ref.get_ports_list())

    component = rename_ports_by_orientation(mim_cap).flatten()

    # netlist generation
    component.info['netlist'] = __generate_mimcap_netlist(pdk, size)

    return component

#@cell
def mimcap_array(pdk: MappedPDK, rows: int, columns: int, size: tuple[float,float] = (5.0,5.0), rmult: Optional[int]=1, option: str = "B") -> Component:
	"""create mimcap array
	args:
	pdk to use
	rows = number of rows
	columns = number of columns  
	size = tuple(float,float) size of a single cap
	rmult = routing multiplier
	option = "A" for Metal3-Metal2 or "B" for Metal5-Metal4 (default: "B")
	****Note: size is the size of the capmet layer
	ports:
	cap_x_y_top_met_...all edges, this is the metal over the capmet in row x, col y
	cap_x_y_bottom_met_...all edges, this is the metal below capmet in row x, col y
	"""
	# Set layer construction based on option
	if option == "A":
		capmettop = "met3"
		capmetbottom = "met2"
	else:  # option == "B"
		capmettop = "met5" 
		capmetbottom = "met4"
		
	mimcap_arr = Component()
	# create the mimcap array
	mimcap_single = mimcap(pdk, size, option=option)
	mimcap_space = pdk.get_grule("capmet")["min_separation"] #+ evaluate_bbox(mimcap_single)[0]
	array_ref = mimcap_arr << prec_array(mimcap_single, rows, columns, spacing=2*[mimcap_space])
	mimcap_arr.add_ports(array_ref.get_ports_list())
	# create a list of ports that should be routed to connect the array
	port_pairs = list()
	for rownum in range(rows):
		for colnum in range(columns):
			bl_mimcap = f"row{rownum}_col{colnum}_"
			right_mimcap = f"row{rownum}_col{colnum+1}_"
			top_mimcap = f"row{rownum+1}_col{colnum}_"
			for level,layer in [("bottom_met_",capmetbottom),("top_met_",capmettop)]:
				bl_east_port = mimcap_arr.ports.get(bl_mimcap+level+"E")
				r_west_port = mimcap_arr.ports.get(right_mimcap+level+"W")
				bl_north_port = mimcap_arr.ports.get(bl_mimcap+level+"N")
				top_south_port = mimcap_arr.ports.get(top_mimcap+level+"S")
				if rownum == rows-1 and colnum == columns-1:
					continue
				elif rownum == rows-1:
					port_pairs.append((bl_east_port,r_west_port,layer))
				elif colnum == columns-1:
					port_pairs.append((bl_north_port,top_south_port,layer))
				else:
					port_pairs.append((bl_east_port,r_west_port,layer))
					port_pairs.append((bl_north_port,top_south_port,layer))
	for port_pair in port_pairs:
		mimcap_arr << straight_route(pdk,port_pair[0],port_pair[1],width=rmult*pdk.get_grule(port_pair[2])["min_width"])

	# add netlist
	mimcap_arr.info['netlist'] = __generate_mimcap_array_netlist(mimcap_single.info['netlist'], rows * columns)

	return mimcap_arr.flatten()


