from gdsfactory.cell import cell
from gdsfactory.component import Component
from gdsfactory.components.rectangle import rectangle
from glayout.pdk.mappedpdk import MappedPDK
from typing import Optional
from glayout.primitives.via_gen import via_array
from glayout.util.comp_utils import prec_array, to_decimal, to_float, evaluate_bbox, align_comp_to_port
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
    pdk: MappedPDK, size: tuple[float,float]=(5.0, 5.0), option: str = "B", 
    extension_width: float = 0.0, extension_length: float = 0.0
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
    extension_width=float width of bottom plate extensions for via connections (default: 0.0um)
    extension_length=float length of bottom plate extensions outside capacitor (default: 0.0um)
    
    ports:
    top_met_...all edges, this is the top metal plate
    met5_...all edges, this is the bottom metal plate connection through metal5 vias
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
    
    # 1. Create bottom metal plate with proper enclosure first
    # Per design rules: Minimum bottom plate overlap of top plate = 0.6um
    try:
        bottom_met_enclosure = pdk.get_grule(capmetbottom, "capmet")["min_enclosure"]
    except (KeyError, NotImplementedError):
        bottom_met_enclosure = 0.6  # Default fallback
    
    bottom_met_enclosure = max(bottom_met_enclosure, 0.6)  # Ensure minimum 0.6um
    bottom_plate_size = (size[0] + 2*bottom_met_enclosure, size[1] + 2*bottom_met_enclosure)
    
    bottom_met_ref = mim_cap << rectangle(
        size=bottom_plate_size,
        layer=pdk.get_glayer(capmetbottom),
        centered=True
    )
    
    # 2. Create CAP_MK layer - dielectric layer (with 0.6um overhang to match KLayout generator)
    cap_mk_overhang = 0.6  # 0.6um overhang on each side to match KLayout standard
    cap_mk_size = (size[0] + 2*cap_mk_overhang, size[1] + 2*cap_mk_overhang)
    cap_mk_ref = mim_cap << rectangle(
        size=cap_mk_size, 
        layer=pdk.get_glayer("capmet"), 
        centered=True
    )
    
    # 3. Create top metal plate with via connections
    # Use minus1=False to get maximum via coverage like KLayout generator
    top_met_ref = mim_cap << via_array(
        pdk, capmetbottom, capmettop, size=size, minus1=False, lay_bottom=False
    )
    
    # 4. Add FuseTop layer - required for both options (defines the MIM area)
    fusetop_comp = rectangle(
        size=size, 
        layer=pdk.layers["fusetop"], 
        centered=True
    )
    
    # Add ports to FuseTop for alignment purposes
    fusetop_comp = add_ports_perimeter(fusetop_comp, layer=pdk.layers["fusetop"], prefix="fusetop_")
    
    # Add the FuseTop component to the main component
    fusetop_ref = mim_cap << fusetop_comp
    
    # 5. Add option-specific layers
    if option == "B":
        # Option B specific: Add MIM_L_MK layer (marks the capacitor length)
        # MIM_L_MK should have height of 0.1um and denote the length of the capacitor
        mim_l_mk_size = (
            size[0],  # x = length of capacitor (same as FuseTop)
            0.1       # y = 0.1um height as specified
        )
        
        mim_l_mk_ref = mim_cap << rectangle(
            size=mim_l_mk_size,
            layer=pdk.layers["MIM_L_MK"],
            centered=True
        )
        
        # Align MIM_L_MK to the south border of the MIM capacitor
        # MIM_L_MK center aligned horizontally, top edge aligned to MIM cap south edge
        align_comp_to_port(mim_l_mk_ref, fusetop_ref.ports["fusetop_S"], alignment=('c', 't'))
    # Option A: Only needs FuseTop, CAP_MK, and metal layers (no MIM_L_MK)
    
    # 6. Add bottom metal extensions and via connections to metal5
    # Use the provided extension parameters
    
    # Calculate positions for extensions on each side
    # Get bottom plate dimensions [x-length, y-length]
    bottom_plate_size = evaluate_bbox(bottom_met_ref)
    bottom_plate_center = bottom_met_ref.center
    
    # Calculate edge positions from center and dimensions
    half_width = bottom_plate_size[0] / 2
    half_height = bottom_plate_size[1] / 2
    
    # Create extensions on all four sides
    extensions = []
    
    extension_width = 2*half_width 
    extension_length =  0.4 # 0.4um length of the extensions
    # South extension  
    south_ext_size = (extension_width, extension_length)
    south_ext_pos = (bottom_plate_center[0], bottom_plate_center[1] - half_height - extension_length/2)
    south_ext = mim_cap << rectangle(
        size=south_ext_size,
        layer=pdk.get_glayer(capmetbottom),
        centered=True
    )
    south_ext.move(south_ext_pos)
    extensions.append(("S", south_ext, south_ext_size))
    
    """
    # North extension
    north_ext_size = (extension_width, extension_length)
    north_ext_pos = (bottom_plate_center[0], bottom_plate_center[1] + half_height + extension_length/2)
    north_ext = mim_cap << rectangle(
        size=north_ext_size,
        layer=pdk.get_glayer(capmetbottom),
        centered=True
    )
    north_ext.move(north_ext_pos)
    extensions.append(("N", north_ext, north_ext_size))

    # East extension
    east_ext_size = (extension_length, extension_width)
    east_ext_pos = (bottom_plate_center[0] + half_width + extension_length/2, bottom_plate_center[1])
    east_ext = mim_cap << rectangle(
        size=east_ext_size,
        layer=pdk.get_glayer(capmetbottom),
        centered=True
    )
    east_ext.move(east_ext_pos)
    extensions.append(("E", east_ext, east_ext_size))
    
    # West extension
    west_ext_size = (extension_length, extension_width)
    west_ext_pos = (bottom_plate_center[0] - half_width - extension_length/2, bottom_plate_center[1])
    west_ext = mim_cap << rectangle(
        size=west_ext_size,
        layer=pdk.get_glayer(capmetbottom),
        centered=True
    )
    west_ext.move(west_ext_pos)
    extensions.append(("W", west_ext, west_ext_size))
    """
    
    # 7. Add via arrays from extensions to metal5
    via_refs = []
    for direction, ext_ref, ext_size in extensions:
        # Create via array from bottom metal to metal5
        via_ref = mim_cap << via_array(
            pdk, 
            capmetbottom, 
            "met5", 
            size=ext_size, 
            # minus1=True,  # Use minus1=True for smaller extensions
            lay_bottom=False
        )
        # Align via array to the extension
        via_ref.move(ext_ref.center)
        via_refs.append((direction, via_ref))
    
    # 8. Create ports on metal5 instead of bottom metal
    # Add ports to the via arrays (which have metal5 on top)
    for direction, via_ref in via_refs:
        mim_cap.add_ports(via_ref.get_ports_list())
    
    # Add top metal ports (unchanged)
    mim_cap.add_ports(top_met_ref.get_ports_list())

    component = rename_ports_by_orientation(mim_cap).flatten()

    # netlist generation
    component.info['netlist'] = __generate_mimcap_netlist(pdk, size)

    return component

#@cell
def mimcap_array(pdk: MappedPDK, rows: int, columns: int, size: tuple[float,float] = (5.0,5.0), rmult: Optional[int]=1, option: str = "B", extension_width: float = 0.0, extension_length: float = 0.0) -> Component:
	"""create mimcap array
	args:
	pdk to use
	rows = number of rows
	columns = number of columns  
	size = tuple(float,float) size of a single cap
	rmult = routing multiplier
	option = "A" for Metal3-Metal2 or "B" for Metal5-Metal4 (default: "B")
	extension_width = width of bottom plate extensions for via connections (default: 2.0um)
	extension_length = length of bottom plate extensions outside capacitor (default: 1.0um)
	****Note: size is the size of the capmet layer
	ports:
	cap_x_y_top_met_...all edges, this is the metal over the capmet in row x, col y
	cap_x_y_met5_...all edges, this is the bottom metal connection through metal5 vias in row x, col y
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
	mimcap_single = mimcap(pdk, size, option=option, extension_width=extension_width, extension_length=extension_length)
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
			for level,layer in [("met5_","met5"),("top_met_",capmettop)]:
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


