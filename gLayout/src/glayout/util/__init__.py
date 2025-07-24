"""
utils functions

removing initial imports to avoid circular imports
everythong is imported in top the __init__.py file

from .comp_utils import evaluate_bbox, center_to_edge_distance, move, movex, movey, to_float, to_decimal, prec_array, prec_center, prec_ref_center, get_padding_points_cc, get_primitive_rectangle
from .port_utils import PortTree, parse_direction, proc_angle, ports_inline, ports_parallel, rename_component_ports, rename_ports_by_list, rename_ports_by_orientation, remove_ports_with_prefix, add_ports_perimeter, get_orientation, assert_port_manhattan, assert_ports_perpindicular, set_port_orientation, set_port_width, print_ports, create_private_ports, print_port_tree_all_cells
from .geometry import rectangle, rename_ports_by_orientation, prec_array, prec_ref_center
from .snap_to_grid import component_snap_to_grid
from .component_array_create import get_files_with_extension, write_component_matrix
from .print_rules import split_rule, create_ruledeck_python_dictionary_definition, visualize_ruleset



Duplicate functions ignored:

| Source File              | Function Name                    | Currently in __init__.py |
|--------------------------|----------------------------------|--------------------------|
| comp_utils.py            | align_comp_to_port               | NO                       | ####
| geometry.py              | evaluate_bbox                    | NO                       | ####
| geometry.py              | component_snap_to_grid           | NO                       | ####
| geometry.py              | to_decimal                       | NO                       | ####
| geometry.py              | to_float                         | NO                       | ####
| geometry.py              | move                             | NO                       | ####
| geometry.py              | movex                            | NO                       | ####
| geometry.py              | movey                            | NO                       | ####
| geometry.py              | align_comp_to_port               | NO                       | ####
| geometry.py              | rename_ports_by_list             | NO                       | ####
| routing.py               | straight_route                   | NO                       | ####
| routing.py               | L_route                          | NO                       | ####
| routing.py               | c_route                          | NO                       | ####

"""