"""
Geometry utility functions for Glayout.
"""

from typing import Optional, Union, Tuple, List
from pathlib import Path

from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory import ComponentReference as Reference
from gdsfactory.typings import Layer, ComponentOrReference
from pydantic import validate_arguments

from ..pdk.mappedpdk import MappedPDK

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def rectangle(
    size: tuple[float, float],
    layer: Layer,
    centered: bool = True
) -> Component:
    """Create a rectangle component.
    
    Args:
        size: Rectangle size (width, height)
        layer: Layer to draw rectangle on
        centered: Whether to center the rectangle
    
    Returns:
        Component: Rectangle component
    """
    rect = Component()
    width, height = size
    
    if centered:
        rect.add_polygon(
            [(-width/2, -height/2), (width/2, -height/2), (width/2, height/2), (-width/2, height/2)],
            layer=layer
        )
    else:
        rect.add_polygon(
            [(0, 0), (width, 0), (width, height), (0, height)],
            layer=layer
        )
    
    return rect

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def evaluate_bbox(component: ComponentOrReference) -> tuple[float, float]:
    """Get the bounding box dimensions of a component.
    
    Args:
        component: Component to evaluate
    
    Returns:
        tuple: (width, height) of bounding box
    """
    bbox = component.bbox
    return (bbox[1][0] - bbox[0][0], bbox[1][1] - bbox[0][1])

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def component_snap_to_grid(component: Component) -> Component:
    """Snap component ports and polygons to grid.
    
    Args:
        component: Component to snap
    
    Returns:
        Component: Snapped component
    """
    # Snap ports to grid
    for port in component.ports.values():
        port.center = (round(port.center[0]), round(port.center[1]))
    
    # Snap polygons to grid
    for polygon in component.polygons:
        polygon.points = [(round(p[0]), round(p[1])) for p in polygon.points]
    
    return component

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def rename_ports_by_orientation(component: Component) -> Component:
    """Rename ports based on their orientation.
    
    Args:
        component: Component to rename ports for
    
    Returns:
        Component: Component with renamed ports
    """
    for port_name, port in component.ports.items():
        if port.orientation == 0:
            new_name = f"{port_name}_E"
        elif port.orientation == 90:
            new_name = f"{port_name}_N"
        elif port.orientation == 180:
            new_name = f"{port_name}_W"
        elif port.orientation == 270:
            new_name = f"{port_name}_S"
        else:
            new_name = port_name
        
        if new_name != port_name:
            component.ports[new_name] = port
            del component.ports[port_name]
    
    return component

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def prec_ref_center(component: Component) -> Reference:
    """Create a centered reference to a component.
    
    Args:
        component: Component to reference
    
    Returns:
        Reference: Centered reference
    """
    ref = component.ref()
    ref.center = (0, 0)
    return ref

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def prec_array(
    component: Component,
    columns: int = 1,
    rows: int = 1,
    spacing: tuple[float, float] = (0, 0),
    absolute_spacing: bool = False
) -> Component:
    """Create an array of components.
    
    Args:
        component: Component to array
        columns: Number of columns
        rows: Number of rows
        spacing: Spacing between components (x, y)
        absolute_spacing: Whether spacing is absolute or relative to component size
    
    Returns:
        Component: Array component
    """
    array = Component()
    
    if absolute_spacing:
        x_spacing, y_spacing = spacing
    else:
        width, height = evaluate_bbox(component)
        x_spacing = width + spacing[0]
        y_spacing = height + spacing[1]
    
    for row in range(rows):
        for col in range(columns):
            ref = array << component
            ref.move((col * x_spacing, row * y_spacing))
            array.add_ports(ref.get_ports_list(), prefix=f"row{row}_col{col}_")
    
    return array

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def to_decimal(value: Union[float, str]) -> float:
    """Convert value to decimal.
    
    Args:
        value: Value to convert
    
    Returns:
        float: Decimal value
    """
    if isinstance(value, str):
        return float(value)
    return value

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def to_float(value: Union[float, str]) -> float:
    """Convert value to float.
    
    Args:
        value: Value to convert
    
    Returns:
        float: Float value
    """
    if isinstance(value, str):
        return float(value)
    return value

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def move(
    component: ComponentOrReference,
    destination: tuple[float, float]
) -> ComponentOrReference:
    """Move component to destination.
    
    Args:
        component: Component to move
        destination: Destination point (x, y)
    
    Returns:
        ComponentOrReference: Moved component
    """
    component.move(destination)
    return component

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def movex(
    component: ComponentOrReference,
    destination: float
) -> ComponentOrReference:
    """Move component in x direction.
    
    Args:
        component: Component to move
        destination: Destination x coordinate
    
    Returns:
        ComponentOrReference: Moved component
    """
    component.movex(destination)
    return component

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def movey(
    component: ComponentOrReference,
    destination: float
) -> ComponentOrReference:
    """Move component in y direction.
    
    Args:
        component: Component to move
        destination: Destination y coordinate
    
    Returns:
        ComponentOrReference: Moved component
    """
    component.movey(destination)
    return component

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def align_comp_to_port(
    component: Component,
    port: ComponentOrReference,
    alignment: tuple[Optional[str], Optional[str]] = (None, None),
    layer: Optional[Layer] = None
) -> Reference:
    """Align component to port.
    
    Args:
        component: Component to align
        port: Port to align to
        alignment: Alignment type (x, y) where each is 'l', 'c', 'r' or None
        layer: Layer to align on
    
    Returns:
        Reference: Aligned component reference
    """
    ref = component.ref()
    
    # Get port center
    if isinstance(port, Component):
        port_center = port.center
    else:
        port_center = port.ports[list(port.ports.keys())[0]].center
    
    # Get component center
    if layer:
        bbox = ref.bbox
        comp_center = ((bbox[0][0] + bbox[1][0])/2, (bbox[0][1] + bbox[1][1])/2)
    else:
        comp_center = ref.center
    
    # Calculate alignment
    x_align, y_align = alignment
    
    if x_align == 'l':
        x_offset = port_center[0] - ref.xmin
    elif x_align == 'r':
        x_offset = port_center[0] - ref.xmax
    elif x_align == 'c':
        x_offset = port_center[0] - comp_center[0]
    else:
        x_offset = 0
    
    if y_align == 'b':
        y_offset = port_center[1] - ref.ymin
    elif y_align == 't':
        y_offset = port_center[1] - ref.ymax
    elif y_align == 'c':
        y_offset = port_center[1] - comp_center[1]
    else:
        y_offset = 0
    
    # Move component
    ref.move((x_offset, y_offset))
    
    return ref

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def rename_ports_by_list(
    component: Component,
    rename_list: List[tuple[str, str]]
) -> Component:
    """Rename ports based on a list of (old, new) prefixes.
    
    Args:
        component: Component to rename ports for
        rename_list: List of (old_prefix, new_prefix) tuples
    
    Returns:
        Component: Component with renamed ports
    """
    for old_prefix, new_prefix in rename_list:
        for port_name in list(component.ports.keys()):
            if port_name.startswith(old_prefix):
                new_name = port_name.replace(old_prefix, new_prefix, 1)
                component.ports[new_name] = component.ports[port_name]
                del component.ports[port_name]
    
    return component 
