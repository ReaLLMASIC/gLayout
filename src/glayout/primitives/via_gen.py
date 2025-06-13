"""
Via generator primitives for Glayout.
"""

from typing import Optional, Literal, Union, Tuple
from pathlib import Path
from math import floor

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
    to_float
)

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def __get_layer_dim(pdk: MappedPDK, glayer: str, mode: Literal["both","above","below"]="both") -> float:
    """Returns the required dimension of a routable layer in a via stack.
    
    Args:
        pdk: MappedPDK instance
        glayer: The routable glayer
        mode: One of [both,below,above]. Specifies which vias to consider.
            - both: considers enclosure rules for vias above and below
            - below: only considers enclosure rules for via below
            - above: only considers enclosure rules for via above
    
    Returns:
        float: Required dimension of the layer
    """
    if not pdk.is_routable_glayer(glayer):
        raise ValueError("__get_layer_dim: glayer must be a routable layer")
    
    consider_above = (mode=="both" or mode=="above")
    consider_below = (mode=="both" or mode=="below")
    is_lvl0 = any([hint in glayer for hint in ["poly","active"]])
    layer_dim = 0
    
    if consider_below and not is_lvl0:
        via_below = "mcon" if glayer=="met1" else "via"+str(int(glayer[-1])-1)
        layer_dim = pdk.get_grule(via_below)["width"] + 2*pdk.get_grule(via_below,glayer)["min_enclosure"]
    
    if consider_above:
        via_above = "mcon" if is_lvl0 else "via"+str(glayer[-1])
        layer_dim = max(layer_dim, pdk.get_grule(via_above)["width"] + 2*pdk.get_grule(via_above,glayer)["min_enclosure"])
    
    layer_dim = max(layer_dim, pdk.get_grule(glayer)["min_width"])
    return layer_dim

@validate_arguments(config=dict(arbitrary_types_allowed=True))
def __get_viastack_minseperation(pdk: MappedPDK, viastack: Component, ordered_layer_info) -> tuple[float,float]:
    """Internal use: return absolute via separation and top_enclosure.
    
    Args:
        pdk: MappedPDK instance
        viastack: Via stack component
        ordered_layer_info: Layer ordering information
    
    Returns:
        tuple[float,float]: Via separation and top enclosure
    """
    get_sep = lambda _pdk, rule, _lay_, comp : (rule+2*comp.extract(layers=[_pdk.get_glayer(_lay_)]).xmax)
    level1, level2 = ordered_layer_info[0]
    glayer1, glayer2 = ordered_layer_info[1]
    mcon_rule = pdk.get_grule("mcon")["min_separation"]
    via_spacing = [] if level1 else [get_sep(pdk,mcon_rule,"mcon",viastack)]
    level1_met = level1 if level1 else level1 + 1
    top_enclosure = 0
    
    for level in range(level1_met, level2):
        met_glayer = "met" + str(level)
        via_glayer = "via" + str(level)
        mrule = pdk.get_grule(met_glayer)["min_separation"]
        vrule = pdk.get_grule(via_glayer)["min_separation"]
        via_spacing.append(get_sep(pdk, mrule,met_glayer,viastack))
        via_spacing.append(get_sep(pdk, vrule,via_glayer,viastack))
        if level == (level2-1):
            top_enclosure = pdk.get_grule(glayer2,via_glayer)["min_enclosure"]
    
    via_spacing = pdk.snap_to_2xgrid(max(via_spacing),return_type="float")
    top_enclosure = pdk.snap_to_2xgrid(top_enclosure,return_type="float")
    return pdk.snap_to_2xgrid([via_spacing, 2*top_enclosure], return_type="float")

@cell
def via_stack(
    pdk: MappedPDK,
    glayer1: str,
    glayer2: str,
    centered: bool = True,
    fullbottom: bool = False,
    fulltop: bool = False,
    assume_bottom_via: bool = False,
    same_layer_behavior: Literal["lay_nothing","min_square"] = "lay_nothing"
) -> Component:
    """Create a via stack between two layers.
    
    Args:
        pdk: MappedPDK instance
        glayer1: First layer
        glayer2: Second layer
        centered: Whether to center the via stack
        fullbottom: Whether to extend bottom layer to full width
        fulltop: Whether to extend top layer to full width
        assume_bottom_via: Whether to assume bottom via exists
        same_layer_behavior: Behavior when layers are the same
    
    Returns:
        Component: Via stack component
    """
    # Order layers by level
    ordered_layer_info = pdk.order_layers_by_level(glayer1, glayer2)
    level1, level2 = ordered_layer_info[0]
    glayer1, glayer2 = ordered_layer_info[1]
    
    viastack = Component()
    
    # Handle same layer case
    if level1 == level2:
        if same_layer_behavior=="lay_nothing":
            return viastack
        min_square = viastack << rectangle(
            size=2*[pdk.get_grule(glayer1)["min_width"]],
            layer=pdk.get_glayer(glayer1),
            centered=centered
        )
        if level1==0:  # both poly or active
            viastack.add_ports(min_square.get_ports_list(),prefix="bottom_layer_")
        else:  # both mets
            viastack.add_ports(min_square.get_ports_list(),prefix="top_met_")
            viastack.add_ports(min_square.get_ports_list(),prefix="bottom_met_")
    else:
        ports_to_add = dict()
        for level in range(level1,level2+1):
            via_name = "mcon" if level==0 else "via"+str(level)
            layer_name = glayer1 if level==0 else "met"+str(level)
            
            # Get layer sizing
            mode = "below" if level==level2 else ("above" if level==level1 else "both")
            mode = "both" if assume_bottom_via and level==level1 else mode
            layer_dim = __get_layer_dim(pdk, layer_name, mode=mode)
            
            # Place via and layer
            if level != level2:
                via_dim = pdk.get_grule(via_name)["width"]
                via_ref = viastack << rectangle(
                    size=[via_dim,via_dim],
                    layer=pdk.get_glayer(via_name),
                    centered=True
                )
            
            lay_ref = viastack << rectangle(
                size=[layer_dim,layer_dim],
                layer=pdk.get_glayer(layer_name),
                centered=True
            )
            
            # Update ports
            if layer_name == glayer1:
                ports_to_add["bottom_layer_"] = lay_ref.get_ports_list()
                ports_to_add["bottom_via_"] = via_ref.get_ports_list()
            if (level1==0 and level==1) or (level1>0 and layer_name==glayer1):
                ports_to_add["bottom_met_"] = lay_ref.get_ports_list()
            if layer_name == glayer2:
                ports_to_add["top_met_"] = lay_ref.get_ports_list()
        
        # Handle fullbottom and fulltop options
        if fullbottom:
            bot_ref = viastack << rectangle(
                size=evaluate_bbox(viastack),
                layer=pdk.get_glayer(glayer1),
                centered=True
            )
            if level1!=0:
                ports_to_add["bottom_met_"] = bot_ref.get_ports_list()
            ports_to_add["bottom_layer_"] = bot_ref.get_ports_list()
        
        if fulltop:
            ports_to_add["top_met_"] = (viastack << rectangle(
                size=evaluate_bbox(viastack),
                layer=pdk.get_glayer(glayer2),
                centered=True
            )).get_ports_list()
        
        # Add all ports
        for prefix, ports_list in ports_to_add.items():
            viastack.add_ports(ports_list,prefix=prefix)
        
        # Move to origin if not centered
        if not centered:
            viastack = move(viastack,(viastack.xmax,viastack.ymax))
    
    return rename_ports_by_orientation(viastack.flatten())

@cell
def via_array(
    pdk: MappedPDK,
    glayer1: str,
    glayer2: str,
    size: Optional[tuple[Optional[float],Optional[float]]] = None,
    minus1: bool = False,
    num_vias: Optional[tuple[Optional[int],Optional[int]]] = None,
    lay_bottom: bool = True,
    fullbottom: bool = False,
    no_exception: bool = False,
    lay_every_layer: bool = False
) -> Component:
    """Create an array of vias between two layers.
    
    Args:
        pdk: MappedPDK instance
        glayer1: First layer
        glayer2: Second layer
        size: (width, height) of area to enclose
        minus1: Remove one via from rows/cols
        num_vias: Number of rows/cols in via array
        lay_bottom: Whether to lay bottom layer
        fullbottom: Whether to extend bottom layer to full width
        no_exception: Whether to adjust size to meet minimum
        lay_every_layer: Whether to lay every layer between glayer1 and glayer2
    
    Returns:
        Component: Via array component
    """
    # Setup
    ordered_layer_info = pdk.order_layers_by_level(glayer1, glayer2)
    level1, level2 = ordered_layer_info[0]
    glayer1, glayer2 = ordered_layer_info[1]
    viaarray = Component()
    
    # Handle same level case
    if level1 == level2:
        return viaarray
    
    # Calculate via spacing
    viastack = via_stack(pdk, glayer1, glayer2)
    viadim = evaluate_bbox(viastack)[0]
    via_abs_spacing, top_enclosure = __get_viastack_minseperation(pdk, viastack, ordered_layer_info)
    
    # Calculate number of vias
    cnum_vias = 2*[None]
    for i in range(2):
        if (num_vias[i] if num_vias else False):
            cnum_vias[i] = num_vias[i]
        elif (size[i] if size else False):
            dim = pdk.snap_to_2xgrid(size[i],return_type="float")
            fltnum = floor((dim - top_enclosure) / (via_abs_spacing)) or 1
            fltnum = 1 if fltnum < 1 else fltnum
            cnum_vias[i] = ((fltnum - 1) or 1) if minus1 else fltnum
            if to_decimal(viadim) > to_decimal(dim) and not no_exception:
                raise ValueError(f"via_array,size:dim#{i}={dim} < {viadim}")
        else:
            raise ValueError("give at least 1: num_vias or size for each dim")
    
    # Create array
    viaarray_ref = prec_ref_center(prec_array(
        viastack,
        columns=cnum_vias[0],
        rows=cnum_vias[1],
        spacing=2*[via_abs_spacing],
        absolute_spacing=True
    ))
    viaarray.add(viaarray_ref)
    viaarray.add_ports(viaarray_ref.get_ports_list(),prefix="array_")
    
    # Calculate dimensions
    viadims = evaluate_bbox(viaarray)
    if not size:
        size = 2*[None]
    size = [size[i] if size[i] else viadims[i] for i in range(2)]
    size = [viadims[i] if viadims[i]>size[i] else size[i] for i in range(2)]
    
    # Place bottom layer
    if lay_bottom or fullbottom or lay_every_layer:
        bdims = evaluate_bbox(viaarray.extract(layers=[pdk.get_glayer(glayer1)]))
        bref = viaarray << rectangle(
            size=(size if fullbottom else bdims),
            layer=pdk.get_glayer(glayer1),
            centered=True
        )
        viaarray.add_ports(bref.get_ports_list(), prefix="bottom_lay_")
    else:
        viaarray = viaarray.remove_layers(layers=[pdk.get_glayer(glayer1)])
    
    # Place top metal
    tref = viaarray << rectangle(
        size=size,
        layer=pdk.get_glayer(glayer2),
        centered=True
    )
    viaarray.add_ports(tref.get_ports_list(), prefix="top_met_")
    
    # Place intermediate layers if requested
    if lay_every_layer:
        for i in range(level1+1,level2):
            bdims = evaluate_bbox(viaarray.extract(layers=[pdk.get_glayer(f"met{i}")]))
            viaarray << rectangle(
                size=bdims,
                layer=pdk.get_glayer(f"met{i}"),
                centered=True
            )
    
    return component_snap_to_grid(rename_ports_by_orientation(viaarray)) 
