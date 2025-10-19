"""
Glayout - A PDK-agnostic layout automation framework for analog circuit design
"""

from .pdk.mappedpdk import MappedPDK
from .pdk.sky130_mapped import sky130_mapped_pdk as sky130
from .pdk.gf180_mapped import gf180_mapped_pdk as gf180
from .pdk.ihp130_mapped import ihp130_mapped_pdk as ihp130

from .primitives.via_gen import via_stack, via_array
from .primitives.fet import nmos, pmos, multiplier
from .primitives.guardring import tapring
from .primitives.mimcap import mimcap, mimcap_array
from .primitives.resistor import resistor

from .spice import Netlist

from .util.port_utils import PortTree, parse_direction, proc_angle, ports_inline, ports_parallel, rename_component_ports, rename_ports_by_list, rename_ports_by_orientation, remove_ports_with_prefix, add_ports_perimeter, get_orientation, assert_port_manhattan, assert_ports_perpindicular, set_port_orientation, set_port_width, print_ports, create_private_ports, print_port_tree_all_cells

from .util.comp_utils import move, movex, movey, align_comp_to_port,evaluate_bbox, center_to_edge_distance, to_float, to_decimal, prec_array, prec_center, prec_ref_center, get_padding_points_cc, get_primitive_rectangle

from .util.snap_to_grid import component_snap_to_grid

from .routing.c_route import c_route
from .routing.L_route import L_route
from .routing.straight_route import straight_route
from .routing.smart_route import smart_route

from .placement.common_centroid_ab_ba import common_centroid_ab_ba
from .placement.four_transistor_interdigitized import generic_4T_interdigitzed
from .placement.two_transistor_interdigitized import two_transistor_interdigitized,two_pfet_interdigitized,two_nfet_interdigitized,macro_two_transistor_interdigitized
from .placement.two_transistor_place import two_transistor_place

__version__ = "0.1.1"

__all__ = [
    "Netlist",
    "mimcap",
    "mimcap_array",
    "resistor",
    "evaluate_bbox",
    "center_to_edge_distance",
    "to_float",
    "to_decimal",
    "prec_array",
    "prec_center",
    "prec_ref_center",
    "get_padding_points_cc",
    "get_primitive_rectangle",
    "parse_direction",
    "proc_angle",
    "ports_inline",
    "ports_parallel",
    "rename_component_ports",
    "rename_ports_by_list",
    "remove_ports_with_prefix",
    "add_ports_perimeter",
    "get_orientation",
    "assert_port_manhattan",
    "assert_ports_perpindicular",
    "set_port_orientation",
    "set_port_width",
    "print_ports",
    "component_snap_to_grid",
    "two_transistor_place",
    "two_transistor_interdigitized",
    "two_pfet_interdigitized",
    "two_nfet_interdigitized",
    "macro_two_transistor_interdigitized",
    "generic_4T_interdigitzed",
    "smart_route",
    "c_route",
    "L_route",
    "straight_route",
    "via_stack",
    "via_array",
    "nmos", 
    "pmos", 
    "multiplier",
    "tapring",
    "PortTree",
    "rename_ports_by_orientation",
    "move",
    "movex",
    "movey",
    "align_comp_to_port",
    "sky130",
    "gf180",
] 
