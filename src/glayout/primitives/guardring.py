"""
Guard ring primitives for Glayout.
"""

from typing import Optional, Union, Tuple
from pathlib import Path

from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory.typings import Layer
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
from .via_gen import via_stack, via_array

@cell
def tapring(
    pdk: MappedPDK,
    enclosed_rectangle: tuple[float, float],
    sdlayer: str,
    horizontal_glayer: str = "met2",
    vertical_glayer: str = "met1",
    rmult: Optional[int] = None,
    sd_rmult: int = 1,
    gate_rmult: int = 1,
    interfinger_rmult: int = 1,
    sd_route_extension: float = 0,
    gate_route_extension: float = 0,
    dummy_routes: bool = True
) -> Component:
    """Create a guard ring for well ties.
    
    Args:
        pdk: MappedPDK instance
        enclosed_rectangle: Size of rectangle to enclose (width, height)
        sdlayer: Source/drain layer (p+s/d for PMOS, n+s/d for NMOS)
        horizontal_glayer: Metal layer for horizontal routing
        vertical_glayer: Metal layer for vertical routing
        rmult: Routing multiplier (overrides other multipliers)
        sd_rmult: Source/drain routing multiplier
        gate_rmult: Gate routing multiplier
        interfinger_rmult: Inter-finger routing multiplier
        sd_route_extension: Source/drain route extension
        gate_route_extension: Gate route extension
        dummy_routes: Whether to route dummy transistors
    
    Returns:
        Component: Guard ring component
    """
    # Error checking
    if "+s/d" not in sdlayer:
        raise ValueError("specify + doped region for tapring")
    if not "met" in horizontal_glayer or not "met" in vertical_glayer:
        raise ValueError("glayer specified must be metal layer")
    if rmult:
        if rmult<1:
            raise ValueError("rmult must be positive int")
        sd_rmult = rmult
        gate_rmult = 1
        interfinger_rmult = ((rmult-1) or 1)
    if sd_rmult<1 or interfinger_rmult<1 or gate_rmult<1:
        raise ValueError("routing multipliers must be positive int")
    
    # Create guard ring
    guardring = Component()
    
    # Calculate dimensions
    width, height = enclosed_rectangle
    width = pdk.snap_to_2xgrid(width)
    height = pdk.snap_to_2xgrid(height)
    
    # Create active region
    active = guardring << rectangle(
        size=(width, height),
        layer=pdk.get_glayer("active_tap"),
        centered=True
    )
    
    # Create doped region
    sd_diff_ovhg = pdk.get_grule(sdlayer, "active_tap")["min_enclosure"]
    sdlayer_dims = [dim + 2*sd_diff_ovhg for dim in (width, height)]
    sdlayer_ref = guardring << rectangle(
        size=sdlayer_dims,
        layer=pdk.get_glayer(sdlayer),
        centered=True
    )
    
    # Create via array for horizontal routing
    hvia = via_array(
        pdk,
        "active_tap",
        horizontal_glayer,
        size=(width, None),
        num_vias=(None, sd_rmult),
        no_exception=True,
        fullbottom=True
    )
    hvia_ref = guardring << hvia
    hvia_ref.movey(height/2)
    
    # Create via array for vertical routing
    vvia = via_array(
        pdk,
        "active_tap",
        vertical_glayer,
        size=(None, height),
        num_vias=(sd_rmult, None),
        no_exception=True,
        fullbottom=True
    )
    vvia_ref = guardring << vvia
    vvia_ref.movex(width/2)
    
    # Add ports
    guardring.add_ports(hvia_ref.get_ports_list(), prefix="top_")
    guardring.add_ports(hvia_ref.get_ports_list(), prefix="bottom_")
    guardring.add_ports(vvia_ref.get_ports_list(), prefix="left_")
    guardring.add_ports(vvia_ref.get_ports_list(), prefix="right_")
    
    return component_snap_to_grid(rename_ports_by_orientation(guardring)) 
