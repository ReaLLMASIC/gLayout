from gdsfactory.cell import cell
from gdsfactory.component import Component
from gdsfactory.port import Port
from glayout.pdk.mappedpdk import MappedPDK
from typing import Optional, Union
from glayout.primitives.via_gen import via_stack, via_array
from glayout.util.comp_utils import evaluate_bbox, align_comp_to_port, to_decimal, to_float, prec_ref_center, get_primitive_rectangle
from glayout.util.port_utils import rename_ports_by_orientation, rename_ports_by_list, print_ports, assert_port_manhattan, assert_ports_perpindicular
from decimal import Decimal
from glayout.routing.straight_route import straight_route
from glayout.routing.c_route import c_route, __fill_empty_viastack__macro
from glayout.routing.L_route import L_route
from glayout.util.comp_utils import evaluate_bbox, get_primitive_rectangle, to_float, prec_ref_center
from glayout.util.port_utils import add_ports_perimeter, rename_ports_by_orientation, rename_ports_by_list, print_ports, set_port_width, set_port_orientation, get_orientation
from pydantic import validate_arguments
from gdsfactory.snap import snap_to_grid

@cell
def z_route(
    pdk: MappedPDK,
    edge1: Port,
    edge2: Port,
    width1: Optional[float] = None,
    width2: Optional[float] = None,
    cwidth: Optional[float] = None,
    glayer1: Optional[str] = None,
    glayer2: Optional[str] = None,
    cglayer: Optional[str] = None,
    fullbottom: bool = True,
    extra_vias: Optional[bool] = False,
    ) -> Component:
    """ 
    Creates a Z shaped route between 2 ports.
    edge1| ------
                |
                | 
                ------ |edge2
    
    Requires:
    - ports be vertical or horizontal
    - edges need to be on the same or opposite orientation (e.g south-north and east-west)

    ****NOTE: does no drc error checking 
	args:
	pdk = pdk to use
	edge1 = first port
	edge2 = second port
	width1 = optional will default to vertical edge width if None
	width2 = optional will default to horizontal edge width if None
	hglayer = glayer for vertical route. Defaults to the layer of the edge oriented N/S
	vglayer = glayer for horizontal route. Defaults to the layer of the edge oriented E/W
	viaoffset = push the via away from both edges so that inside corner aligns with via corner
	****via offset can also be specfied as a tuple(bool,bool): movex? if viaoffset[0] and movey? if viaoffset[1]
	fullbottom = fullbottom option for via
	"""

    assert_port_manhattan([edge1, edge2])
    if edge1.orientation % 180 != edge2.orientation % 180:
        raise ValueError(
            f"Z-route error: Port should be paralel. "
            f"Found: edge1={edge1.orientation}°, edge2={edge2.orientation}°"
        )
        
    if edge1.orientation == edge2.orientation:
        edge2.orientation = (edge2.orientation + 180) % 360
        
    pdk.activate()
    Zroute = Component()
    edge1_is_EW = bool(round(edge1.orientation + 90) % 180)
    diff_y = abs(edge1.y -edge2.y)
    diff_x = abs(edge1.x -edge2.x)
    if glayer1 is None:
        glayer1 = pdk.layer_to_glayer(edge1.layer)
    if glayer2 is None:
        glayer2 = pdk.layer_to_glayer(edge2.layer)
    glayer_plusone = "met" + str(int(glayer1[-1])+1)
    cglayer = cglayer if cglayer else glayer_plusone

      
    hdim_center = float(to_decimal(edge1.center[0]) - to_decimal(edge2.center[0]))
    vdim_center = float(to_decimal(edge2.center[1]) - to_decimal(edge1.center[1]))

    viastack1 = via_stack(pdk,glayer1,cglayer,fullbottom=fullbottom,assume_bottom_via=True,fulltop=True)
    viastack1_dims = evaluate_bbox(viastack1,True)

    if edge1_is_EW:
        # horizontal z route
        width2 = width2 if width2 else edge1.width
        width1 = width1 if width1 else edge2.width
        center = snap_to_grid((edge1.x + edge2.x) / 2)
        end_pos = snap_to_grid(edge2.y)
    else:
        width1 = width1 if width1 else edge1.width
        width2 = width2 if width2 else width1
        end_pos = snap_to_grid((edge1.y + edge2.y) / 2)
        center = snap_to_grid(edge2.x)
    cwidth = cwidth if cwidth else min(width1,width2)
    if extra_vias:  
        #condition checking for multiple vias at first intermediate node,  
        if round(edge1.orientation) == 0 or round(edge1.orientation) == 180:
            use_arr1 = viastack1_dims[0] < cwidth or viastack1_dims[1] < width1
        if round(edge1.orientation) == 90 or round(edge1.orientation) == 270:
            use_arr1 = viastack1_dims[0] < width1 or viastack1_dims[1] < cwidth 
        #via array for the first node
        if use_arr1:
            if round(edge1.orientation) == 0 or round(edge1.orientation) == 180:
                viastack1 = via_array(pdk, glayer1, cglayer, size=(cwidth,width1), fullbottom=fullbottom, no_exception=True)
            if round(edge1.orientation) == 90 or round(edge1.orientation) == 270:
                viastack1 = via_array(pdk, glayer2, cglayer, size=(width1,cwidth), fullbottom=fullbottom, no_exception=True)

    if glayer1==cglayer and glayer2==cglayer:
        viastack1 = __fill_empty_viastack__macro(pdk,glayer1)
    elif glayer1 == cglayer:
        viastack1 = __fill_empty_viastack__macro(pdk,glayer1,size=evaluate_bbox(viastack1))
    elif glayer2 == cglayer:
        viastack1 = __fill_empty_viastack__macro(pdk,glayer2,size=evaluate_bbox(viastack1))
 
    me1 = prec_ref_center(viastack1)
    
    Zroute.add(me1)
    me1.move(destination=(center, end_pos))

    if edge1_is_EW:
        if edge1.y > edge2.y:
            route_1 = L_route(pdk, edge1, me1.ports["top_met_S"], width1, cwidth, glayer1, cglayer)
        else:
            route_1 = L_route(pdk, edge1, me1.ports["top_met_N"], width1, cwidth, glayer1, cglayer)
    else:
        if edge1.x > edge2.x:
            route_1 = L_route(pdk, edge1, me1.ports["top_met_E"], width1, cwidth, glayer1, cglayer)
        else:
            route_1 = L_route(pdk, edge1, me1.ports["top_met_W"], width1, cwidth, glayer1, cglayer)
    
    if round(edge1.orientation) == 0: 
        route_2 = straight_route(pdk, edge2, me1.ports["top_met_E"], glayer2, width2, cglayer)
    elif round(edge1.orientation) == 270:
        route_2 = straight_route(pdk, edge2, me1.ports["top_met_S"], glayer2, width2, cglayer)
    elif round(edge1.orientation) == 180:
        route_2 = straight_route(pdk, edge2, me1.ports["top_met_W"], glayer2, width2, cglayer)
    elif round(edge1.orientation) == 90:
        route_2 = straight_route(pdk, edge2, me1.ports["top_met_N"], glayer2, width2, cglayer)
    
    Zroute.add(route_2)
    Zroute.add(route_1)
    Zroute.add_ports(me1.get_ports_list(), prefix="con_v_")
    
    return rename_ports_by_orientation(Zroute.flatten())