"""
Routing utility functions for Glayout.
"""

from typing import Optional, Tuple
from gdsfactory.component import Component
from gdsfactory.typings import Port
from ..pdk.mappedpdk import MappedPDK
from .geometry import rectangle


def straight_route(pdk: MappedPDK, port1: Port, port2: Port, glayer: Optional[str] = None) -> Component:
    """Create a straight route between two ports."""
    c = Component()
    if glayer is None:
        glayer = "met1"
    x1, y1 = port1.center
    x2, y2 = port2.center
    width = abs(y2 - y1) if abs(y2 - y1) > abs(x2 - x1) else abs(x2 - x1)
    length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    # Draw a rectangle between the two ports
    c << rectangle(size=(length, pdk.get_grule(glayer)["width"]), layer=pdk.get_glayer(glayer), centered=True)
    return c


def L_route(pdk: MappedPDK, port1: Port, port2: Port, glayer: Optional[str] = None) -> Component:
    """Create an L-shaped route between two ports."""
    c = Component()
    if glayer is None:
        glayer = "met1"
    x1, y1 = port1.center
    x2, y2 = port2.center
    # Horizontal then vertical
    mid = (x2, y1)
    c << straight_route(pdk, port1, type('Port', (), {'center': mid})(), glayer)
    c << straight_route(pdk, type('Port', (), {'center': mid})(), port2, glayer)
    return c


def c_route(pdk: MappedPDK, port1: Port, port2: Port, glayer: Optional[str] = None) -> Component:
    """Create a C-shaped route between two ports (for demonstration)."""
    c = Component()
    if glayer is None:
        glayer = "met1"
    x1, y1 = port1.center
    x2, y2 = port2.center
    # C route: horizontal, vertical, horizontal
    mid1 = (x1, (y1 + y2) / 2)
    mid2 = (x2, (y1 + y2) / 2)
    c << straight_route(pdk, port1, type('Port', (), {'center': mid1})(), glayer)
    c << straight_route(pdk, type('Port', (), {'center': mid1})(), type('Port', (), {'center': mid2})(), glayer)
    c << straight_route(pdk, type('Port', (), {'center': mid2})(), port2, glayer)
    return c 
