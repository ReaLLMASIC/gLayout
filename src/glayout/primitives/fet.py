"""
FET primitives for Glayout.
"""

from typing import Optional, Union, Tuple
from pathlib import Path

from gdsfactory.cell import cell
from gdsfactory.component import Component
from gdsfactory.types import Layer
from pydantic import validate_arguments

from ..pdk.mappedpdk import MappedPDK
from ..util.geometry import (
    rectangle,
    evaluate_bbox,
    component_snap_to_grid,
    rename_ports_by_orientation,
    prec_ref_center,
    prec_array,
    to_decimal,
    to_float,
    move,
    movex,
    movey,
    align_comp_to_port,
    rename_ports_by_list
)
from ..util.routing import straight_route, L_route, c_route
from ..spice.netlist import Netlist
from .via_gen import via_stack, via_array

@validate_arguments
def __gen_fingers_macro(
    pdk: MappedPDK,
    rmult: int,
    fingers: int,
    length: float,
    width: float,
    poly_height: float,
    sdlayer: str,
    inter_finger_topmet: str
) -> Component:
    """Internal use: returns an array of fingers.
    
    Args:
        pdk: MappedPDK instance
        rmult: Routing multiplier
        fingers: Number of fingers
        length: Transistor length
        width: Transistor width
        poly_height: Poly height
        sdlayer: Source/drain layer
        inter_finger_topmet: Top metal for inter-finger routing
    
    Returns:
        Component: Finger array component
    """
    length = pdk.snap_to_2xgrid(length)
    width = pdk.snap_to_2xgrid(width)
    poly_height = pdk.snap_to_2xgrid(poly_height)
    
    # Calculate poly spacing
    sizing_ref_viastack = via_stack(pdk, "active_diff", "met1")
    sd_viaxdim = rmult*evaluate_bbox(via_stack(pdk, "active_diff", "met1"))[0]
    poly_spacing = 2 * pdk.get_grule("poly", "mcon")["min_separation"] + pdk.get_grule("mcon")["width"]
    poly_spacing = max(sd_viaxdim, poly_spacing)
    met1_minsep = pdk.get_grule("met1")["min_separation"]
    poly_spacing += met1_minsep if length < met1_minsep else 0
    
    # Create single finger
    finger = Component("finger")
    gate = finger << rectangle(
        size=(length, poly_height),
        layer=pdk.get_glayer("poly"),
        centered=True
    )
    
    # Create source/drain via array
    sd_viaarr = via_array(
        pdk,
        "active_diff",
        "met1",
        size=(sd_viaxdim, width),
        minus1=True,
        lay_bottom=False
    ).copy()
    
    # Add inter-finger routing
    interfinger_correction = via_array(
        pdk,
        "met1",
        inter_finger_topmet,
        size=(None, width),
        lay_every_layer=True,
        num_vias=(1,None)
    )
    sd_viaarr << interfinger_correction
    sd_viaarr_ref = finger << sd_viaarr
    sd_viaarr_ref.movex((poly_spacing+length) / 2)
    
    # Add ports
    finger.add_ports(gate.get_ports_list(),prefix="gate_")
    finger.add_ports(sd_viaarr_ref.get_ports_list(),prefix="rightsd_")
    
    # Create finger array
    fingerarray = prec_array(
        finger,
        columns=fingers,
        rows=1,
        spacing=(poly_spacing+length, 1),
        absolute_spacing=True
    )
    
    # Add left source/drain via
    sd_via_ref_left = fingerarray << sd_viaarr
    sd_via_ref_left.movex(0-(poly_spacing+length)/2)
    fingerarray.add_ports(sd_via_ref_left.get_ports_list(),prefix="leftsd_")
    
    # Center finger array
    centered_farray = Component()
    fingerarray_ref_center = prec_ref_center(fingerarray)
    centered_farray.add(fingerarray_ref_center)
    centered_farray.add_ports(fingerarray_ref_center.get_ports_list())
    
    # Create diffusion and doped region
    multiplier = rename_ports_by_orientation(centered_farray)
    diff_extra_enc = 2 * pdk.get_grule("mcon", "active_diff")["min_enclosure"]
    diff_dims = (diff_extra_enc + evaluate_bbox(multiplier)[0], width)
    diff = multiplier << rectangle(
        size=diff_dims,
        layer=pdk.get_glayer("active_diff"),
        centered=True
    )
    
    sd_diff_ovhg = pdk.get_grule(sdlayer, "active_diff")["min_enclosure"]
    sdlayer_dims = [dim + 2*sd_diff_ovhg for dim in diff_dims]
    sdlayer_ref = multiplier << rectangle(
        size=sdlayer_dims,
        layer=pdk.get_glayer(sdlayer),
        centered=True
    )
    
    multiplier.add_ports(sdlayer_ref.get_ports_list(),prefix="plusdoped_")
    multiplier.add_ports(diff.get_ports_list(),prefix="diff_")
    
    return component_snap_to_grid(rename_ports_by_orientation(multiplier))

def fet_netlist(
    pdk: MappedPDK,
    circuit_name: str,
    model: str,
    width: float,
    length: float,
    fingers: int,
    multipliers: int,
    with_dummy: Union[bool, tuple[bool, bool]]
) -> Netlist:
    """Generate SPICE netlist for a FET.
    
    Args:
        pdk: MappedPDK instance
        circuit_name: Name of the circuit
        model: Transistor model name
        width: Transistor width
        length: Transistor length
        fingers: Number of fingers
        multipliers: Number of multipliers
        with_dummy: Whether to include dummy transistors
    
    Returns:
        Netlist: SPICE netlist for the FET
    """
    # Calculate number of dummies
    num_dummies = 0
    if with_dummy == False or with_dummy == (False, False):
        num_dummies = 0
    elif with_dummy == (True, False) or with_dummy == (False, True):
        num_dummies = 1
    elif with_dummy == True or with_dummy == (True, True):
        num_dummies = 2
    
    if length is None:
        length = pdk.get_grule('poly')['min_width']
    
    ltop = length
    wtop = width
    mtop = fingers * multipliers
    dmtop = multipliers
    
    # Generate netlist
    source_netlist = """.subckt {circuit_name} {nodes} """+f'l={ltop} w={wtop} m={mtop} dm={dmtop} '+"""
XMAIN   D G S B {model} l={{l}} w={{w}} m={{m}}"""

    for i in range(num_dummies):
        source_netlist += "\nXDUMMY" + str(i+1) + " B B B B {model} l={{l}} w={{w}} m={{dm}}"

    source_netlist += "\n.ends {circuit_name}"

    return Netlist(
        circuit_name=circuit_name,
        nodes=['D', 'G', 'S', 'B'],
        source_netlist=source_netlist,
        instance_format="X{name} {nodes} {circuit_name} l={length} w={width} m={mult} dm={dummy_mult}",
        parameters={
            'model': model,
            'length': ltop,
            'width': wtop,
            'mult': mtop / 2,
            'dummy_mult': dmtop
        }
    )

@cell
def multiplier(
    pdk: MappedPDK,
    sdlayer: str,
    width: Optional[float] = 3,
    length: Optional[float] = None,
    fingers: int = 1,
    routing: bool = True,
    inter_finger_topmet: str = "met2",
    dummy: Union[bool, tuple[bool, bool]] = True,
    sd_route_topmet: str = "met2",
    gate_route_topmet: str = "met2",
    rmult: Optional[int]=None,
    sd_rmult: int = 1,
    gate_rmult: int=1,
    interfinger_rmult: int=1,
    sd_route_extension: float = 0,
    gate_route_extension: float = 0,
    dummy_routes: bool=True
) -> Component:
    """Create a transistor multiplier.
    
    Args:
        pdk: MappedPDK instance
        sdlayer: Source/drain layer (p+s/d for PMOS, n+s/d for NMOS)
        width: Transistor width
        length: Transistor length
        fingers: Number of fingers
        routing: Whether to route source/drain
        inter_finger_topmet: Top metal for inter-finger routing
        dummy: Whether to add dummy transistors
        sd_route_topmet: Top metal for source/drain routing
        gate_route_topmet: Top metal for gate routing
        rmult: Routing multiplier (overrides other multipliers)
        sd_rmult: Source/drain routing multiplier
        gate_rmult: Gate routing multiplier
        interfinger_rmult: Inter-finger routing multiplier
        sd_route_extension: Source/drain route extension
        gate_route_extension: Gate route extension
        dummy_routes: Whether to route dummy transistors
    
    Returns:
        Component: Multiplier component
    """
    # Error checking
    if "+s/d" not in sdlayer:
        raise ValueError("specify + doped region for multiplier")
    if not "met" in sd_route_topmet or not "met" in gate_route_topmet:
        raise ValueError("topmet specified must be metal layer")
    if rmult:
        if rmult<1:
            raise ValueError("rmult must be positive int")
        sd_rmult = rmult
        gate_rmult = 1
        interfinger_rmult = ((rmult-1) or 1)
    if sd_rmult<1 or interfinger_rmult<1 or gate_rmult<1:
        raise ValueError("routing multipliers must be positive int")
    if fingers < 1:
        raise ValueError("number of fingers must be positive int")
    
    # Setup dimensions
    min_length = pdk.get_grule("poly")["min_width"]
    length = min_length if (length or min_length) <= min_length else length
    length = pdk.snap_to_2xgrid(length)
    min_width = max(min_length, pdk.get_grule("active_diff")["min_width"])
    width = min_width if (width or min_width) <= min_width else width
    width = pdk.snap_to_2xgrid(width)
    poly_height = width + 2 * pdk.get_grule("poly", "active_diff")["overhang"]
    
    # Create finger array
    multiplier = __gen_fingers_macro(
        pdk,
        interfinger_rmult,
        fingers,
        length,
        width,
        poly_height,
        sdlayer,
        inter_finger_topmet
    )
    
    # Route source/drain and gate
    if routing:
        # Place vias and route source/drain
        sd_N_port = multiplier.ports["leftsd_top_met_N"]
        sdvia = via_stack(pdk, "met1", sd_route_topmet)
        sdmet_hieght = sd_rmult*evaluate_bbox(sdvia)[1]
        sdroute_minsep = pdk.get_grule(sd_route_topmet)["min_separation"]
        sdvia_ports = list()
        
        for finger in range(fingers+1):
            diff_top_port = movey(sd_N_port,destination=width/2)
            big_extension = sdroute_minsep + sdmet_hieght/2 + sdmet_hieght
            sdvia_extension = big_extension if finger % 2 else sdmet_hieght/2
            sdvia_ref = align_comp_to_port(sdvia,diff_top_port,alignment=('c','t'))
            multiplier.add(sdvia_ref.movey(sdvia_extension + pdk.snap_to_2xgrid(sd_route_extension)))
            multiplier << straight_route(pdk, diff_top_port, sdvia_ref.ports["bottom_met_N"])
            sdvia_ports += [sdvia_ref.ports["top_met_W"], sdvia_ref.ports["top_met_E"]]
            
            if finger==fingers:
                break
            sd_N_port = multiplier.ports[f"row0_col{finger}_rightsd_top_met_N"]
            
            # Route gates
            gate_S_port = multiplier.ports[f"row0_col{finger}_gate_S"]
            metal_seperation = pdk.util_max_metal_seperation()
            psuedo_Ngateroute = movey(gate_S_port.copy(),0-metal_seperation-gate_route_extension)
            psuedo_Ngateroute.y = pdk.snap_to_2xgrid(psuedo_Ngateroute.y)
            multiplier << straight_route(pdk,gate_S_port,psuedo_Ngateroute)
        
        # Place gate route
        gate_width = gate_S_port.center[0] - multiplier.ports["row0_col0_gate_S"].center[0] + gate_S_port.width
        gate = rename_ports_by_list(
            via_array(
                pdk,
                "poly",
                gate_route_topmet,
                size=(gate_width,None),
                num_vias=(None,gate_rmult),
                no_exception=True,
                fullbottom=True
            ),
            [("top_met_","gate_")]
        )
        gate_ref = align_comp_to_port(
            gate.copy(),
            psuedo_Ngateroute,
            alignment=(None,'b'),
            layer=pdk.get_glayer("poly")
        )
        multiplier.add(gate_ref)
        
        # Place source/drain routes
        sd_width = sdvia_ports[-1].center[0] - sdvia_ports[0].center[0]
        sd_route = rectangle(
            size=(sd_width,sdmet_hieght),
            layer=pdk.get_glayer(sd_route_topmet),
            centered=True
        )
        source = align_comp_to_port(sd_route.copy(), sdvia_ports[0], alignment=(None,'c'))
        drain = align_comp_to_port(sd_route.copy(), sdvia_ports[2], alignment=(None,'c'))
        multiplier.add(source)
        multiplier.add(drain)
        
        # Add ports
        multiplier.add_ports(drain.get_ports_list(), prefix="drain_")
        multiplier.add_ports(source.get_ports_list(), prefix="source_")
        multiplier.add_ports(gate_ref.get_ports_list(prefix="gate_"))
    
    # Create dummy regions
    if isinstance(dummy, bool):
        dummyl = dummyr = dummy
    else:
        dummyl, dummyr = dummy
    
    if dummyl or dummyr:
        dummy = __gen_fingers_macro(
            pdk,
            rmult=interfinger_rmult,
            fingers=1,
            length=length,
            width=width,
            poly_height=poly_height,
            sdlayer=sdlayer,
            inter_finger_topmet="met1"
        )
        dummyvia = dummy << via_stack(pdk,"poly","met1",fullbottom=True)
        align_comp_to_port(dummyvia,dummy.ports["row0_col0_gate_S"],layer=pdk.get_glayer("poly"))
        dummy << L_route(pdk,dummyvia.ports["top_met_W"],dummy.ports["leftsd_top_met_S"])
        dummy << L_route(pdk,dummyvia.ports["top_met_E"],dummy.ports["row0_col0_rightsd_top_met_S"])
        dummy.add_ports(dummyvia.get_ports_list(),prefix="gsdcon_")
        
        dummy_space = pdk.get_grule(sdlayer)["min_separation"] + dummy.xmax
        sides = list()
        if dummyl:
            sides.append((-1,"dummy_L_"))
        if dummyr:
            sides.append((1,"dummy_R_"))
        
        for side, name in sides:
            dummy_ref = multiplier << dummy
            dummy_ref.movex(side * (dummy_space + multiplier.xmax))
            multiplier.add_ports(dummy_ref.get_ports_list(),prefix=name)
    
    return component_snap_to_grid(rename_ports_by_orientation(multiplier))

@cell
def nmos(
    pdk: MappedPDK,
    width: float = 3,
    fingers: Optional[int] = 1,
    multipliers: Optional[int] = 1,
    with_tie: bool = True,
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    with_dnwell: bool = True,
    with_substrate_tap: bool = True,
    length: Optional[float] = None,
    sd_route_topmet: str = "met2",
    gate_route_topmet: str = "met2",
    sd_route_left: bool = True,
    rmult: Optional[int] = None,
    sd_rmult: int = 1,
    gate_rmult: int=1,
    interfinger_rmult: int=1,
    tie_layers: tuple[str,str] = ("met2","met1"),
    substrate_tap_layers: tuple[str,str] = ("met2","met1"),
    dummy_routes: bool=True
) -> Component:
    """Create an NMOS transistor.
    
    Args:
        pdk: MappedPDK instance
        width: Transistor width
        fingers: Number of fingers
        multipliers: Number of multipliers
        with_tie: Whether to add bulk tie
        with_dummy: Whether to add dummy transistors
        with_dnwell: Whether to use deep N-well
        with_substrate_tap: Whether to add substrate tap
        length: Transistor length
        sd_route_topmet: Top metal for source/drain routing
        gate_route_topmet: Top metal for gate routing
        sd_route_left: Whether to route source/drain on left
        rmult: Routing multiplier
        sd_rmult: Source/drain routing multiplier
        gate_rmult: Gate routing multiplier
        interfinger_rmult: Inter-finger routing multiplier
        tie_layers: Layers for well tie ring
        substrate_tap_layers: Layers for substrate tap ring
        dummy_routes: Whether to route dummy transistors
    
    Returns:
        Component: NMOS component
    """
    pdk.activate()
    nfet = Component()
    
    if rmult:
        if rmult<1:
            raise ValueError("rmult must be positive int")
        sd_rmult = rmult
        gate_rmult = 1
        interfinger_rmult = ((rmult-1) or 1)
    
    # Create multiplier array
    multiplier_arr = multiplier(
        pdk,
        "n+s/d",
        width=width,
        fingers=fingers,
        length=length,
        dummy=with_dummy,
        sd_route_topmet=sd_route_topmet,
        gate_route_topmet=gate_route_topmet,
        sd_rmult=sd_rmult,
        gate_rmult=gate_rmult,
        interfinger_rmult=interfinger_rmult,
        dummy_routes=dummy_routes
    )
    
    # Create array of multipliers
    if multipliers > 1:
        multiplier_arr = prec_array(
            multiplier_arr,
            columns=1,
            rows=multipliers,
            spacing=(1, pdk.get_grule("active_diff")["min_separation"]),
            absolute_spacing=True
        )
    
    multiplier_arr_ref = nfet << multiplier_arr
    nfet.add_ports(multiplier_arr_ref.get_ports_list())
    
    # Add bulk tie if requested
    if with_tie:
        tap_separation = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule("p+s/d", "active_tap")["min_enclosure"]
        tap_encloses = (
            2 * (tap_separation + nfet.xmax),
            2 * (tap_separation + nfet.ymax),
        )
        tiering_ref = nfet << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        nfet.add_ports(tiering_ref.get_ports_list(), prefix="tie_")
        
        # Route dummy transistors to tie ring
        for row in range(multipliers):
            for dummyside,tieside in [("L","W"),("R","E")]:
                try:
                    nfet << straight_route(
                        pdk,
                        nfet.ports[f"multiplier_{row}_dummy_{dummyside}_gsdcon_top_met_W"],
                        nfet.ports[f"tie_{tieside}_top_met_{tieside}"],
                        glayer2="met1"
                    )
                except KeyError:
                    pass
    
    return component_snap_to_grid(rename_ports_by_orientation(nfet))

@cell
def pmos(
    pdk: MappedPDK,
    width: float = 3,
    fingers: Optional[int] = 1,
    multipliers: Optional[int] = 1,
    with_tie: Optional[bool] = True,
    dnwell: Optional[bool] = False,
    with_dummy: Optional[Union[bool, tuple[bool, bool]]] = True,
    with_substrate_tap: Optional[bool] = True,
    length: Optional[float] = None,
    sd_route_topmet: Optional[str] = "met2",
    gate_route_topmet: Optional[str] = "met2",
    sd_route_left: Optional[bool] = True,
    rmult: Optional[int] = None,
    sd_rmult: int=1,
    gate_rmult: int=1,
    interfinger_rmult: int=1,
    tie_layers: tuple[str,str] = ("met2","met1"),
    substrate_tap_layers: tuple[str,str] = ("met2","met1"),
    dummy_routes: bool=True
) -> Component:
    """Create a PMOS transistor.
    
    Args:
        pdk: MappedPDK instance
        width: Transistor width
        fingers: Number of fingers
        multipliers: Number of multipliers
        with_tie: Whether to add bulk tie
        dnwell: Whether to use deep N-well
        with_dummy: Whether to add dummy transistors
        with_substrate_tap: Whether to add substrate tap
        length: Transistor length
        sd_route_topmet: Top metal for source/drain routing
        gate_route_topmet: Top metal for gate routing
        sd_route_left: Whether to route source/drain on left
        rmult: Routing multiplier
        sd_rmult: Source/drain routing multiplier
        gate_rmult: Gate routing multiplier
        interfinger_rmult: Inter-finger routing multiplier
        tie_layers: Layers for well tie ring
        substrate_tap_layers: Layers for substrate tap ring
        dummy_routes: Whether to route dummy transistors
    
    Returns:
        Component: PMOS component
    """
    pdk.activate()
    pfet = Component()
    
    if rmult:
        if rmult<1:
            raise ValueError("rmult must be positive int")
        sd_rmult = rmult
        gate_rmult = 1
        interfinger_rmult = ((rmult-1) or 1)
    
    # Create multiplier array
    multiplier_arr = multiplier(
        pdk,
        "p+s/d",
        width=width,
        fingers=fingers,
        length=length,
        dummy=with_dummy,
        sd_route_topmet=sd_route_topmet,
        gate_route_topmet=gate_route_topmet,
        sd_rmult=sd_rmult,
        gate_rmult=gate_rmult,
        interfinger_rmult=interfinger_rmult,
        dummy_routes=dummy_routes
    )
    
    # Create array of multipliers
    if multipliers > 1:
        multiplier_arr = prec_array(
            multiplier_arr,
            columns=1,
            rows=multipliers,
            spacing=(1, pdk.get_grule("active_diff")["min_separation"]),
            absolute_spacing=True
        )
    
    multiplier_arr_ref = pfet << multiplier_arr
    pfet.add_ports(multiplier_arr_ref.get_ports_list())
    
    return component_snap_to_grid(rename_ports_by_orientation(pfet)) 