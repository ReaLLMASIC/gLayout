"""
MIM capacitor primitives for Glayout.
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
def mimcap(
    pdk: MappedPDK,
    width: float,
    height: float,
    top_metal: str = "met4",
    bottom_metal: str = "met3",
    via_metal: str = "met3",
    rmult: Optional[int] = None,
    sd_rmult: int = 1,
    gate_rmult: int = 1,
    interfinger_rmult: int = 1,
    sd_route_extension: float = 0,
    gate_route_extension: float = 0,
    dummy_routes: bool = True
) -> Component:
    """Create a MIM capacitor.
    
    Args:
        pdk: MappedPDK instance
        width: Capacitor width
        height: Capacitor height
        top_metal: Top metal layer
        bottom_metal: Bottom metal layer
        via_metal: Via metal layer
        rmult: Routing multiplier (overrides other multipliers)
        sd_rmult: Source/drain routing multiplier
        gate_rmult: Gate routing multiplier
        interfinger_rmult: Inter-finger routing multiplier
        sd_route_extension: Source/drain route extension
        gate_route_extension: Gate route extension
        dummy_routes: Whether to route dummy transistors
    
    Returns:
        Component: MIM capacitor component
    """
    # Error checking
    if not "met" in top_metal or not "met" in bottom_metal or not "met" in via_metal:
        raise ValueError("metal layers must be metal layers")
    if rmult:
        if rmult<1:
            raise ValueError("rmult must be positive int")
        sd_rmult = rmult
        gate_rmult = 1
        interfinger_rmult = ((rmult-1) or 1)
    if sd_rmult<1 or interfinger_rmult<1 or gate_rmult<1:
        raise ValueError("routing multipliers must be positive int")
    
    # Create capacitor
    cap = Component()
    
    # Calculate dimensions
    width = pdk.snap_to_2xgrid(width)
    height = pdk.snap_to_2xgrid(height)
    
    # Create bottom plate
    bottom = cap << rectangle(
        size=(width, height),
        layer=pdk.get_glayer(bottom_metal),
        centered=True
    )
    
    # Create top plate
    top = cap << rectangle(
        size=(width, height),
        layer=pdk.get_glayer(top_metal),
        centered=True
    )
    
    # Create via array for bottom plate
    bottom_via = via_array(
        pdk,
        bottom_metal,
        via_metal,
        size=(width, height),
        num_vias=(sd_rmult, sd_rmult),
        no_exception=True,
        fullbottom=True
    )
    bottom_via_ref = cap << bottom_via
    
    # Create via array for top plate
    top_via = via_array(
        pdk,
        top_metal,
        via_metal,
        size=(width, height),
        num_vias=(sd_rmult, sd_rmult),
        no_exception=True,
        fullbottom=True
    )
    top_via_ref = cap << top_via
    
    # Add ports
    cap.add_ports(bottom_via_ref.get_ports_list(), prefix="bottom_")
    cap.add_ports(top_via_ref.get_ports_list(), prefix="top_")
    
    return component_snap_to_grid(rename_ports_by_orientation(cap))

@cell
def mimcap_array(
    pdk: MappedPDK,
    width: float,
    height: float,
    rows: int = 1,
    columns: int = 1,
    top_metal: str = "met4",
    bottom_metal: str = "met3",
    via_metal: str = "met3",
    rmult: Optional[int] = None,
    sd_rmult: int = 1,
    gate_rmult: int = 1,
    interfinger_rmult: int = 1,
    sd_route_extension: float = 0,
    gate_route_extension: float = 0,
    dummy_routes: bool = True
) -> Component:
    """Create an array of MIM capacitors.
    
    Args:
        pdk: MappedPDK instance
        width: Capacitor width
        height: Capacitor height
        rows: Number of rows
        columns: Number of columns
        top_metal: Top metal layer
        bottom_metal: Bottom metal layer
        via_metal: Via metal layer
        rmult: Routing multiplier (overrides other multipliers)
        sd_rmult: Source/drain routing multiplier
        gate_rmult: Gate routing multiplier
        interfinger_rmult: Inter-finger routing multiplier
        sd_route_extension: Source/drain route extension
        gate_route_extension: Gate route extension
        dummy_routes: Whether to route dummy transistors
    
    Returns:
        Component: MIM capacitor array component
    """
    # Error checking
    if rows < 1 or columns < 1:
        raise ValueError("rows and columns must be positive integers")
    
    # Create single capacitor
    single_cap = mimcap(
        pdk,
        width=width,
        height=height,
        top_metal=top_metal,
        bottom_metal=bottom_metal,
        via_metal=via_metal,
        rmult=rmult,
        sd_rmult=sd_rmult,
        gate_rmult=gate_rmult,
        interfinger_rmult=interfinger_rmult,
        sd_route_extension=sd_route_extension,
        gate_route_extension=gate_route_extension,
        dummy_routes=dummy_routes
    )
    
    # Create array
    cap_array = prec_array(
        single_cap,
        columns=columns,
        rows=rows,
        spacing=(pdk.get_grule(top_metal)["min_separation"], pdk.get_grule(top_metal)["min_separation"]),
        absolute_spacing=True
    )
    
    return component_snap_to_grid(rename_ports_by_orientation(cap_array)) 
