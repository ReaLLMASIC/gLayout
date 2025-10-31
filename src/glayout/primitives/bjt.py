from pydantic import validate_arguments
from sys import prefix
import numpy as np
from typing import Any, Optional, Union
from glayout import MappedPDK, sky130 , gf180
from glayout.primitives.guardring import tapring
from glayout.routing import c_route
from glayout.util.pattern import check_pattern_level, check_pattern_size, get_cols_positions, transpose_pattern
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.util.port_utils import add_ports_perimeter, rename_ports_by_list, rename_ports_by_orientation
from glayout.util.comp_utils import prec_center, prec_array, prec_ref_center, to_float, move, align_comp_to_port, evaluate_bbox, to_decimal
from glayout.primitives.via_gen import via_array, via_stack
from glayout.routing.straight_route import straight_route
from gdsfactory.cell import cell
from gdsfactory import Component
from gdsfactory.components import text_freetype, rectangle, rectangular_ring


def get_number_contacts(dims, contact_dims, padding, spacing ):
    return np.floor((np.asarray(dims)-
              2*padding-
              np.asarray(contact_dims)
             )/(np.asarray(contact_dims)+spacing)+
                      np.asarray((1,1)))

def fill_comp_with_contacts(pdk: MappedPDK,reference: Component, contact_layer:str,
                       padding, spacing, contact_size):

    dims = evaluate_bbox(reference)
    center = prec_center(reference)


    return fill_area_with_contacts(pdk,dims,center,contact_layer,padding,spacing,contact_size)

def fill_area_with_contacts(pdk: MappedPDK, dims, center, contact_layer:str,
                       padding, spacing, contact_size):

    component = Component()

    n_contacts = get_number_contacts(dims, contact_size, padding, spacing)

    contact = rectangle(layer=pdk.get_glayer(contact_layer), size=contact_size,
                        centered=True)
    contacts = prec_array(contact,rows=n_contacts[1],
                          columns=n_contacts[0], spacing=spacing)

    centered_contacts =  prec_ref_center(contacts,destination=(float(center[0]),float(center[1])))
    component.add(centered_contacts)
    component.add_ports(centered_contacts.get_ports_list())

    return component


def get_rectangle_dims_over_ring(ring_dims:dict[str,np.ndarray[Any]],
                                 overlap=True, distance=0.0):

    bbox_ring = np.asarray(ring_dims["enclosed_size"]) + 2*np.asarray(ring_dims["width"])

    return {
        "N": {"size":(bbox_ring[0] if overlap else
                      ring_dims["enclosed_size"][0]-2*distance, ring_dims["width"])},
        "S": {"size":(bbox_ring[0] if overlap else
                      ring_dims["enclosed_size"][0]-2*distance, ring_dims["width"])},
        "E": {"size":(ring_dims["width"], bbox_ring[1])},
        "W": {"size":(ring_dims["width"], bbox_ring[1])}
    }

def get_mid_points_over_ring(ring_dims):

    mid_point_ring = np.asarray(ring_dims["enclosed_size"]) + np.asarray(ring_dims["width"])
    return {
        "N": mid_point_ring*np.asarray((0,0.5)),
        "S": mid_point_ring*np.asarray((0,-0.5)),
        "E": mid_point_ring*np.asarray((0.5,0)),
        "W": mid_point_ring*np.asarray((-0.5,0)),
    }




def draw_metal_over_ring(pdk: MappedPDK,ring_dims:dict[str,np.ndarray[Any]],
                         metal_layer:str, label=None):

    l_metal_dims= get_rectangle_dims_over_ring(ring_dims)
    l_metal_center_position = get_mid_points_over_ring(ring_dims)

    component = Component()

    for direction in l_metal_dims:
        metal = component << rectangle(layer=pdk.get_glayer(metal_layer), centered=True,
                  **l_metal_dims[direction])
        metal.move(l_metal_center_position[direction])
        component.add_ports(metal.get_ports_list(), prefix=f"metal_{direction}_")

        if label is not None:
            component.add_label(label,
                                position=l_metal_center_position[direction],
                                layer=pdk.get_glayer(metal_layer))


    return component

def fill_ring_with_contacts(pdk: MappedPDK,ring_dims:dict[str,np.ndarray[Any]],
                            contact_layer:str, padding, spacing, contact_size):

    l_metal_dims= get_rectangle_dims_over_ring(ring_dims,
                                               overlap=False,
                                               distance=0.25-0.1)
    l_metal_center_position = get_mid_points_over_ring(ring_dims)

    #print(l_metal_dims)
    component = Component()

    for direction in l_metal_dims:

        #print(l_metal_dims[direction])
        contacts = component << fill_area_with_contacts(pdk,
                                           l_metal_dims[direction]["size"],
                                           l_metal_center_position[direction],
                                           contact_layer,
                                           padding,
                                           spacing,
                                           contact_size)
        component.add_ports(contacts.get_ports_list(), prefix=f"contacts_{direction}_")

    return component

def get_bjt_dimensions (pdk: MappedPDK, active_area: tuple[float, float], bjt_type:
                        str, draw_dnwell: bool =False)-> dict[str,Any]:
    min_enclosure_tap_ncomp = float(pdk.get_grule("p+s/d","active_tap")["min_enclosure"])
    min_enclosure_tap_pcomp = float(pdk.get_grule("n+s/d","active_tap")["min_enclosure"])
    min_enclosure_dnwell_pwell = float(pdk.get_grule("dnwell",
                                                     "pwell")["min_enclosure"])
    contact_size= float(pdk.get_grule("mcon","mcon")["width"])
    min_enclosure_contact_tap = 0.1
    tap_width= contact_size+2*min_enclosure_contact_tap
    ndiff_width = tap_width+2*min_enclosure_tap_ncomp
    pdiff_width = tap_width+2*min_enclosure_tap_pcomp
    emitter_active = {"size": np.asarray(active_area)}
    emitter={ "size": emitter_active["size"] + 2*(min_enclosure_tap_ncomp if
                                                  bjt_type=="npn" else
                                                   min_enclosure_tap_pcomp)
               }

    base = { "enclosed_size": np.asarray(emitter["size"]),
               "width": pdiff_width if bjt_type=="npn" else ndiff_width
               }

    base_active = { "enclosed_size": emitter["size"] + 2*(min_enclosure_tap_pcomp if
                                                  bjt_type=="npn" else
                                                   min_enclosure_tap_ncomp),
               "width": tap_width
               }

    collector = { "enclosed_size": np.asarray(base["enclosed_size"]) + 2*base["width"],
                 "width": ndiff_width if bjt_type=="npn" else pdiff_width
               }

    collector_active = { "enclosed_size":
                        collector["enclosed_size"] + 2*(min_enclosure_tap_ncomp if
                                                  bjt_type=="npn" else
                                                   min_enclosure_tap_pcomp),
               "width": tap_width
               }

    well = {"size": np.asarray(base["enclosed_size"]) + 2*base["width"]}
    dnwell = {"size": np.asarray(well["size"]) + 2*min_enclosure_dnwell_pwell}
    drc = {"size": dnwell["size"]  if
           bjt_type=="npn" and draw_dnwell else (np.asarray(collector["enclosed_size"]) +
           2*collector["width"]) }


    return {
        "min_enclosure_tap_ncomp": min_enclosure_tap_ncomp,
        "min_enclosure_tap_pcomp": min_enclosure_tap_pcomp,
        "min_enclosure_dnwell_pwell": min_enclosure_dnwell_pwell,
        "contact_size": contact_size,
        "min_enclosure_contact_tap": min_enclosure_contact_tap,
        "tap_width": tap_width,
        "ndiff_width": ndiff_width,
        "pdiff_width": pdiff_width,
        "emitter" : emitter,
        "emitter_active" : emitter_active,
        "base" : base,
        "base_active" : base_active,
        "collector" : collector,
        "collector_active" : collector_active,
        "well": well,
        "dnwell": dnwell,
        "drc": drc
    }


def draw_bjt(pdk: MappedPDK, active_area: tuple[float,float], bjt_type: str,
             draw_dnwell: bool = False, with_labels=True)->Component:

    component = Component()

    # Validate the size parameter
    if bjt_type not in pdk.valid_bjt_sizes.keys():
        raise ValueError(f"Not a valid type of bjt: {bjt_type}.\n"
                         f"Valid options are: {list(pdk.valid_bjt_sizes.keys())}")

    if active_area not in  pdk.valid_bjt_sizes[bjt_type]:
        raise ValueError(f"Not a valid size for the bjt: {active_area}.\n"
                         f"Valid options are: {pdk.valid_bjt_sizes[bjt_type]}")

    dims=get_bjt_dimensions(pdk,active_area,bjt_type,
                            draw_dnwell=draw_dnwell)
    bjt_layers= {
        "npn":("n+s/d","p+s/d","n+s/d"),
        "pnp":("p+s/d","n+s/d","p+s/d")
    }
    comp_layer="active_tap"

    well_layer = {
        "npn":"pwell",
        "pnp":"nwell"
    }

    ## Add diffusion areas
    diff_e= component << rectangle(layer=pdk.get_glayer(bjt_layers[bjt_type][0]),
                                   centered=True, **dims["emitter"])
    diff_b= component << rectangular_ring(layer=pdk.get_glayer(bjt_layers[bjt_type][1]),
                                          centered=True, **dims["base"])
    diff_c= component << rectangular_ring(layer=pdk.get_glayer(bjt_layers[bjt_type][2]),
                                          centered=True, **dims["collector"])
    component.add_ports(diff_e.get_ports_list(),prefix="diff_e_")
    component.add_ports(diff_b.get_ports_list(),prefix="diff_b_")
    component.add_ports(diff_c.get_ports_list(),prefix="diff_c_")

    ## Add active region inside diffusion areas
    tap_e= component << rectangle(layer=pdk.get_glayer(comp_layer),
                                   centered=True, **dims["emitter_active"])
    tap_b= component << rectangular_ring(layer=pdk.get_glayer(comp_layer),
                                          centered=True, **dims["base_active"])
    tap_c= component << rectangular_ring(layer=pdk.get_glayer(comp_layer),
                                          centered=True,
                                         **dims["collector_active"])
    component.add_ports(tap_e.get_ports_list(),prefix="tap_e_")
    component.add_ports(tap_b.get_ports_list(),prefix="tap_b_")
    component.add_ports(tap_c.get_ports_list(),prefix="tap_c_")

    ## Adding well layer
    well = component << rectangle(
        layer=pdk.get_glayer(well_layer[bjt_type]), centered=True, **dims["well"])

    component.add_ports(well.get_ports_list(), prefix="well_")

    ## Adding dnwell if required
    if bjt_type=="npn" and draw_dnwell:
        dnwell = component << rectangle(
            layer=pdk.get_glayer("dnwell"), centered=True, **dims["dnwell"])
        component.add_ports(dnwell.get_ports_list(), prefix="dnwell_")

    ## Add lvs and drc
    lvs= component << rectangle(layer=pdk.get_glayer("lvs_bjt"),
                                   centered=True, **dims["emitter_active"])

    drc= component << rectangle(layer=pdk.get_glayer("drc_bjt"),
                                   centered=True, **dims["drc"])

    component.add_ports(lvs.get_ports_list(), prefix="lvs_")
    component.add_ports(drc.get_ports_list(), prefix="drc_")


    ## Add metals
    metal_e = component << rectangle(layer=pdk.get_glayer("met1"),
                                     centered=True, **dims["emitter_active"])
    component.add_ports(metal_e.get_ports_list(), prefix="E_")

    if with_labels:
        component.add_label("E",position=metal_e.center,layer=pdk.get_glayer("met1"))

    metal_b = component << draw_metal_over_ring(pdk,
                                                dims["base_active"],
                                                "met1",
                                                "B" if with_labels else
                                                None)
    component.add_ports(metal_b.get_ports_list(), prefix="B_")

    metal_c = component << draw_metal_over_ring(pdk,
                                                dims["collector_active"],
                                                "met1",
                                                "C" if with_labels else
                                                None)
    component.add_ports(metal_c.get_ports_list(), prefix="C_")

    contacts_e = component << fill_comp_with_contacts(pdk,
                                                 metal_e,
                                                 "mcon",
                                                 dims["min_enclosure_contact_tap"],
                                                 (0.28,0.28),
                                                 np.asarray((1,1))*dims["contact_size"])
    component.add_ports(contacts_e.get_ports_list(), prefix="contacts_e_")

    contacts_b = component << fill_ring_with_contacts(pdk,
                                                 dims["base_active"],
                                                 "mcon",
                                                 dims["min_enclosure_contact_tap"],
                                                 (0.25,0.25),
                                                 np.asarray((1,1))*dims["contact_size"])

    component.add_ports(contacts_b.get_ports_list(), prefix="contacts_b_")

    contacts_c = component << fill_ring_with_contacts(pdk,
                                                 dims["collector_active"],
                                                 "mcon",
                                                 dims["min_enclosure_contact_tap"],
                                                 (0.25,0.25),
                                                 np.asarray((1,1))*dims["contact_size"])

    component.add_ports(contacts_c.get_ports_list(), prefix="contacts_c_")

    return rename_ports_by_orientation(component)

# drain is above source
@cell
def multiplier(
    pdk: MappedPDK,
    active_area: tuple[float,float] = (5.,5.),
    bjt_type: str = "pnp",
    routing: bool = True,
    dummy: Union[bool, tuple[bool, bool]] = True,
    bc_route_topmet: str = "met2",
    emitter_route_topmet: str = "met2",
    rmult: Optional[int]=None,
    bc_rmult: int = 1,
    emitter_rmult: int=1,
    dummy_routes: bool=True,
    dummy_separation_rmult: int = 0
) -> Component:
    """Generic poly/sd vias generator
    args:
    pdk = pdk to use
    active_area = sets the emitter active area. Needs to be a valid size
    supported by the technology
    routing = true or false, specfies if should create the routes for base and
    collector
    ****NOTE: routing metal is layed over the source drain regions regardless of routing option
    dummy = true or false add dummy active/plus doped regions
    bc_rmult = multiplies thickness of metal in base and collector (int only)
    emitter_rmult = multiplies gate by adding rows to the gate via array (int only)
    bc_route_extension = float, how far extra to extend the source/drain connections (default=0)
    emitter_route_extension = float, how far extra to extend the gate connection (default=0)
    dummy_routes: bool default=True, if true add add vias and short dummy base,
    collector and emitter

    ports (one port for each edge),
    ****NOTE: source is below drain:
    base_... all edges (top met route of base connection)
    collector_...all edges (top met route of collector connections)
    emitter_...all edges (top met route of emitter connections)
    leftsd_...all ports associated with the left most via array
    dummy_L,R_N,E,S,W ports if dummy_routes=True
    """
    # error checking
    if not "met" in bc_route_topmet or not "met" in bc_route_topmet:
        raise ValueError("topmet specified must be metal layer")
    if rmult:
        if rmult<1:
            raise ValueError("rmult must be positive int")
        bc_rmult = rmult
        emitter_rmult = 1
    # call finger array
    multiplier = draw_bjt(pdk, active_area,
                          bjt_type, draw_dnwell=False)
    # route base and collector
    # tested with 5x5 size, need to test with smaller sizes
    if routing:

        bcroute_minsep = pdk.get_grule(bc_route_topmet)["min_separation"]

        # place via for base
        b_N_port = multiplier.ports["B_metal_W_N"]
        bvia = via_stack(pdk, "met1", bc_route_topmet)
        bmet_height = bc_rmult*evaluate_bbox(bvia)[1]
        bvia_ref = align_comp_to_port(bvia,b_N_port,alignment=('c','b'))
        multiplier.add(bvia_ref)

        # place via for the collector
        c_S_port = multiplier.ports["C_metal_W_S"]
        cvia = via_stack(pdk, "met1", bc_route_topmet)
        cmet_height = bc_rmult*evaluate_bbox(cvia)[1]
        # get the distance between the port and the bvia_ref
        distance_bmet_cmet=  (bvia_ref.center[1]
                              - c_S_port.center[1]
                              - evaluate_bbox(cvia)[1]/2
                              - bmet_height/2
                              - cmet_height/2)
        cvia_ref = align_comp_to_port(cvia,c_S_port,alignment=('c','t'))

        # place sdvia such that metal does not overlap diffusion
        if (distance_bmet_cmet<bcroute_minsep):
            cvia_extension = bcroute_minsep - distance_bmet_cmet
            cvia_ref = align_comp_to_port(cvia,c_S_port,alignment=('c','t'))
            multiplier.add(cvia_ref.movey(-cvia_extension))
            multiplier << straight_route(pdk, c_S_port,
                                         cvia_ref.ports["top_met_N"])

        else:
            multiplier.add(cvia_ref)

        # place emitter via at the center
        ecenter= ((multiplier.ports["E_W"].center[0]+multiplier.ports["E_E"].center[0])/2,
                    (multiplier.ports["E_N"].center[1]+multiplier.ports["E_S"].center[1])/2)
        evia = rename_ports_by_list(via_stack(pdk,
                                              "met1",
                                              emitter_route_topmet),
                                     [("top_met_","emitter_")])
        evia_ref = move(evia.ref(),destination=ecenter)
        multiplier.add(evia_ref)

        # place the route met for collector and base

        bc_width=  bvia_ref.ports["top_met_E"].center[0] - cvia_ref.ports["top_met_W"].center[0]
        b_route = rectangle(size=(bc_width,
                                  bmet_height),layer=pdk.get_glayer(bc_route_topmet),centered=True)
        c_route = rectangle(size=(bc_width,
                                  cmet_height),layer=pdk.get_glayer(bc_route_topmet),centered=True)

        base = align_comp_to_port(b_route.copy(),
                                  bvia_ref.ports["top_met_E"],
                                  alignment=("l",'c'))
        collector = align_comp_to_port(c_route.copy(),
                                       cvia_ref.ports["top_met_W"],
                                       alignment=("r",'c'))

        multiplier.add(base)
        multiplier.add(collector)
        multiplier.add_ports(evia_ref.get_ports_list(prefix="emitter_"))
        multiplier.add_ports(base.get_ports_list(), prefix="base_")
        multiplier.add_ports(collector.get_ports_list(),prefix="collector_")


    # get reference for dummy sep

    rvia = via_stack(pdk, "met1", bc_route_topmet)
    dummy_sep = dummy_separation_rmult*float(evaluate_bbox(rvia)[1])

    # create dummy regions
    if isinstance(dummy, bool):
        dummyl = dummyr = dummy
    else:
        dummyl, dummyr = dummy
    if dummyl or dummyr:
        dummy = draw_bjt(pdk, active_area,
                         bjt_type, with_labels=False)
        dummy << straight_route(pdk,dummy.ports["E_S"],dummy.ports["B_metal_S_N"])
        dummy << straight_route(pdk,dummy.ports["B_metal_S_S"],dummy.ports["C_metal_S_N"])
        dummy_separation = max(pdk.get_grule("n+s/d")["min_separation"],pdk.get_grule("p+s/d")["min_separation"])
        dummy_space = dummy_separation  + (dummy.xmax-dummy.xmin)/2 + dummy_sep
        sides = list()
        if dummyl:
            sides.append((-1,"dummy_L_"))
        if dummyr:
            sides.append((1,"dummy_R_"))
        for side, name in sides:
            dummy_ref = multiplier << dummy
            dummy_ref.movex(side * (dummy_space + multiplier.xmax))
            multiplier.add_ports(dummy_ref.get_ports_list(),prefix=name)
    # ensure correct port names and return
    return component_snap_to_grid(rename_ports_by_orientation(multiplier))


@validate_arguments
def __mult_array_macro(
    pdk: MappedPDK,
    active_area: tuple[float,float] = (5.,5.),
    bjt_type: str = "pnp",
    multipliers: int = 1,
    routing: Optional[bool] = True,
    dummy: Optional[Union[bool, tuple[bool, bool]]] = True,
    bc_route_topmet: Optional[str] = "met2",
    emitter_route_topmet: Optional[str] = "met2",
    bc_route_left: Optional[bool] = True,
    bc_rmult: int = 1,
    emitter_rmult: int=1,
    dummy_routes: bool=True,
    pattern: Union[list[str], list[int], None] = None,
    is_bc_short: bool = False,
    is_bc_shared: bool = False,
    centered: bool = True,
    dummy_separation_rmult: int = 0
) -> Component:
    """create a multiplier array with multiplier_0 at the bottom
    The array is correctly centered
    """

    # check the validy of the pattern if exists
    if pattern is not None:
        if(len(pattern)!=multipliers):
            raise ValueError("Not a valid pattern. Must have the same number of "
                             "elements as the multiplier")

        unique_elements=list(set(pattern))

    # create multiplier array
    pdk.activate()
    # TODO: error checking
    multiplier_arr = Component("temp multiplier array")
    multiplier_comp = multiplier(
        pdk,
        active_area=active_area,
        bjt_type=bjt_type,
        dummy=dummy,
        routing=routing,
        bc_route_topmet=bc_route_topmet,
        emitter_route_topmet=emitter_route_topmet,
        bc_rmult=bc_rmult,
        emitter_rmult=emitter_rmult,
        dummy_routes=dummy_routes,
        dummy_separation_rmult=dummy_separation_rmult
    )
    _max_metal_separation_ps = max([pdk.get_grule("met"+str(i))["min_separation"] for i in range(1,5)])
    min_diff_separation = max(pdk.get_grule("n+s/d")["min_separation"],pdk.get_grule("p+s/d")["min_separation"])
    routing_separation = max([ _max_metal_separation_ps, min_diff_separation])
    multiplier_separation = to_decimal(
        float(routing_separation) + evaluate_bbox(multiplier_comp)[1]
    )
    for rownum in range(multipliers):
        row_displacment = rownum * multiplier_separation - (multiplier_separation/2 * (multipliers-1))
        row_ref = multiplier_arr << multiplier_comp
        row_ref.movey(to_float(row_displacment))
        multiplier_arr.add_ports(
            row_ref.get_ports_list(), prefix="multiplier_" + str(rownum) + "_"
        )
    b_extension = to_decimal(0.6)

    # using the C route will use the port width to make the routing
    # then we can check the width for it and add the required space accordingly
    # we assume the width is the same in west as the east

    sample_base_port="multiplier_0_base_W"
    sample_collector_port="multiplier_0_collector_W"
    base_port_width= multiplier_arr[sample_base_port].width
    collector_port_width = multiplier_arr[sample_collector_port].width
    distance = base_port_width/2 + collector_port_width/2 + 2*pdk.get_grule("met4")["min_separation"]

    c_extension= to_decimal(to_float(b_extension)+ distance )

    if pattern is not None:
        bc_pattern_distances = [distance*2*n for n in range(len(unique_elements))]
        e_pattern_distances = [distance*n for n in range(len(unique_elements))]

        if is_bc_short:
            if is_bc_shared:
                bc_pattern_distances = [0]*len(unique_elements)
            else:
                bc_pattern_distances = e_pattern_distances

        bc_distances_by_element = dict(zip(unique_elements,bc_pattern_distances))
        e_distances_by_element = dict(zip(unique_elements,e_pattern_distances))


    bc_side = "W" if bc_route_left else "E"
    e_side = "E" if bc_route_left else "W"

    dimension_wo_routing = evaluate_bbox(multiplier_arr)
    #print(multiplier_arr.ports)
    if routing:
        if pattern is None and multipliers > 1:
            for rownum in range(multipliers-1):
                thismult = "multiplier_" + str(rownum) + "_"
                nextmult = "multiplier_" + str(rownum+1) + "_"
                # route bases left
                basepfx = thismult + "base_"
                this_base = multiplier_arr.ports[basepfx+bc_side]
                next_base = multiplier_arr.ports[nextmult + "base_"+bc_side]
                base_ref = multiplier_arr << c_route(pdk, this_base, next_base,
                                                     viaoffset=(True,False),
                                                     extension=to_float(b_extension))
                multiplier_arr.add_ports(base_ref.get_ports_list(), prefix=basepfx)
                # route collectors left
                collectorpfx = thismult + "collector_"
                this_collector = multiplier_arr.ports[collectorpfx+bc_side]
                next_collector = multiplier_arr.ports[nextmult +
                                                      "collector_"+bc_side]
                collector_ref = multiplier_arr << c_route(pdk,
                                                          this_collector,
                                                          next_collector,
                                                      viaoffset=(True,False),
                                                      extension=to_float(c_extension))
                multiplier_arr.add_ports(collector_ref.get_ports_list(),
                                         prefix=collectorpfx)
                # route emitter right
                emitterpfx = thismult + "emitter_"
                this_emitter = multiplier_arr.ports[emitterpfx+e_side]
                next_emitter = multiplier_arr.ports[nextmult +
                                                    "emitter_"+e_side]
                emitter_ref = multiplier_arr << c_route(pdk,
                                                        this_emitter,
                                                        next_emitter,
                                                        viaoffset=(True,False),
                                                        extension=to_float(b_extension))
                multiplier_arr.add_ports(emitter_ref.get_ports_list(), prefix=emitterpfx)
        elif pattern is not None:
            for rownum in range(len(unique_elements)):
                this_id_pfx = unique_elements[rownum] + "_"

                this_collector_pfx = this_id_pfx + "collector_"
                this_base_pfx = this_id_pfx + "base_"
                this_emitter_pfx = this_id_pfx + "emitter_"

                eglayer_plusone = "met" + str(int(bc_route_topmet[-1])+1)
                bvia = via_stack(pdk, bc_route_topmet, eglayer_plusone)
                width_routing = bc_rmult*evaluate_bbox(bvia)[1]

                ref_port_base = multiplier_arr.ports["multiplier_0_base_" + bc_side]
                ref_port_collector = multiplier_arr.ports["multiplier_0_collector_" + bc_side]
                ref_port_emitter = multiplier_arr.ports["multiplier_0_emitter_" + e_side]

                nref_port_base= move(ref_port_base,
                                     destination=(ref_port_base.center[0] -
                                                  bc_distances_by_element[unique_elements[rownum]]
                                                  - to_float(b_extension),
                                                  (multiplier_arr.ymax +
                                                      multiplier_arr.ymin)/2))

                nref_port_collector= move(ref_port_collector,
                                     destination=(ref_port_collector.center[0] -
                                                  bc_distances_by_element[unique_elements[rownum]]
                                                  - to_float(c_extension),
                                                  (multiplier_arr.ymax +
                                                      multiplier_arr.ymin)/2))

                nref_port_emitter= move(ref_port_emitter,
                                     destination=(ref_port_emitter.center[0] +
                                                  e_distances_by_element[unique_elements[rownum]]
                                                  + to_float(b_extension),
                                                  (multiplier_arr.ymax +
                                                      multiplier_arr.ymin)/2))

                sample_route = rectangle(size=(width_routing,
                                             dimension_wo_routing[1]),
                                       layer=pdk.get_glayer(eglayer_plusone),
                                       centered=True)

                if not is_bc_shared or rownum<1:
                    base_route_ref = align_comp_to_port(sample_route.copy(),
                                           nref_port_base,
                                           alignment=("l",'c'))
                    multiplier_arr.add(base_route_ref)
                    if is_bc_shared:
                        this_base_pfx = "base_"
                    multiplier_arr.add_ports(base_route_ref.get_ports_list(),
                                             prefix=this_base_pfx)

                    if not is_bc_short and not is_bc_shared:
                        collector_route_ref = align_comp_to_port(sample_route.copy(),
                                               nref_port_collector,
                                               alignment=("l",'c'))
                        multiplier_arr.add(collector_route_ref)
                        multiplier_arr.add_ports(collector_route_ref.get_ports_list(),
                                                 prefix=this_collector_pfx)

                emitter_route_ref = align_comp_to_port(sample_route.copy(),
                                       nref_port_emitter,
                                       alignment=("r",'c'))
                multiplier_arr.add(emitter_route_ref)
                multiplier_arr.add_ports(emitter_route_ref.get_ports_list(),
                                         prefix=this_emitter_pfx)

                multiplier_arr = rename_ports_by_orientation(multiplier_arr)

            for rownum, pat in enumerate(pattern):

                thismult = "multiplier_" + str(rownum) + "_"

                basepfx = thismult + "base_"
                this_base = multiplier_arr.ports[basepfx+bc_side]

                collectorpfx = thismult + "collector_"
                this_collector = multiplier_arr.ports[collectorpfx+bc_side]

                emitterpfx = thismult + "emitter_"
                this_emitter = multiplier_arr.ports[emitterpfx+e_side]

                if not is_bc_shared:
                    base_route=multiplier_arr.ports[str(pat)+"_base_"+e_side]
                    collector_route=multiplier_arr.ports[str(pat)+"_collector_"+e_side] if not is_bc_short else base_route
                else:
                    base_route = multiplier_arr.ports["base_"+e_side]
                    collector_route = base_route
                emitter_route=multiplier_arr.ports[str(pat)+"_emitter_"+bc_side]

                # creating the connections from each of the ports to the
                # corresponding routes

                collector_ref = multiplier_arr << straight_route(pdk, this_collector,
                                                                 collector_route)
                base_ref = multiplier_arr << straight_route(pdk, this_base,
                                                                 base_route)
                emitter_ref = multiplier_arr << straight_route(pdk,
                                                               this_emitter,
                                                                 emitter_route)

    multiplier_arr = component_snap_to_grid(rename_ports_by_orientation(multiplier_arr))
    # add port redirects for shortcut names (source,drain,gate N,E,S,W)
    if pattern is None:
        for pin in ["base","collector","emitter"]:
            for side in ["N","E","S","W"]:
                aliasport = pin + "_" + side
                actualport = "multiplier_0_" + aliasport
                multiplier_arr.add_port(port=multiplier_arr.ports[actualport],name=aliasport)
    # recenter
    final_arr = Component()
    marrref = final_arr << multiplier_arr
    if centered:
        correctionxy = prec_center(marrref)
        marrref.movex(correctionxy[0]).movey(correctionxy[1])
    final_arr.add_ports(marrref.get_ports_list())
    return component_snap_to_grid(rename_ports_by_orientation(final_arr))


@validate_arguments
def __mult_2dim_array_macro(
    pdk: MappedPDK,
    active_area: tuple[float,float] = (5.,5.),
    bjt_type: str = "pnp",
    multipliers: Union[tuple[int,int], int] = (1,1),
    routing: Optional[bool] = True,
    dummy: Optional[Union[bool, tuple[bool, bool]]] = True,
    bc_route_topmet: Optional[str] = "met2",
    emitter_route_topmet: Optional[str] = "met2",
    bc_route_left: Optional[bool] = True,
    bc_route_bottom: Optional[bool] = True,
    bc_rmult: int = 1,
    emitter_rmult: int=1,
    dummy_routes: bool=True,
    pattern: Union[list[list[str]], list[list[int]], list[str], list[int], None] = None,
    is_bc_short: bool = False,
    is_bc_shared: bool = False
) -> Component:
    """create a multiplier array with multiplier_0 at the bottom
    The array is correctly centered
    """

    # check the validy of the pattern if exists
    if check_pattern_level(pattern) != 2:
        raise ValueError("Pattern level not valid for this function")

    # check multiplier quantity matches the pattern
    if check_pattern_size(pattern) != multipliers:
        raise ValueError("Multipliers size doesn't match pattern size")

    # create multiplier array
    pdk.activate()
    # TODO: error checking
    multiplier_2dim_arr = Component("temp multiplier array")

    t_pattern = transpose_pattern(pattern)

    l_cols = []

    max_width = 0
    for column_pattern in t_pattern:
        multiplier_arr = __mult_array_macro(
            pdk,
            active_area=active_area,
            bjt_type=bjt_type,
            multipliers=len(column_pattern),
            routing=routing,
            dummy=False,
            bc_route_topmet=bc_route_topmet,
            emitter_route_topmet=emitter_route_topmet,
            bc_route_left=bc_route_left,
            bc_rmult=bc_rmult,
            emitter_rmult=emitter_rmult,
            dummy_routes=dummy_routes,
            pattern=column_pattern,
            is_bc_short=is_bc_short,
            is_bc_shared=is_bc_shared,
            centered=False
        )
        l_cols.append(multiplier_arr)


        if float(evaluate_bbox(multiplier_arr)[0]) > float( max_width ):
            max_width = evaluate_bbox(multiplier_arr)[0]

    # create a multiplier reference to extract the original width
    multiplier_ref = multiplier(
            pdk,
            active_area=active_area,
            bjt_type=bjt_type,
            routing=routing,
            dummy=False,
            bc_route_topmet=bc_route_topmet,
            emitter_route_topmet=emitter_route_topmet,
            bc_rmult=bc_rmult,
            emitter_rmult=emitter_rmult,
            dummy_routes=dummy_routes,
        )

    mult_width = evaluate_bbox(multiplier_ref)[0]
    rvia = via_stack(pdk, "met1", bc_route_topmet)
    unit_sep_width = evaluate_bbox(rvia)[0]
    dummy_separation_rmult = int((max_width - mult_width)/unit_sep_width)
    # create dummy regions
    if isinstance(dummy, bool):
        dummyl = dummyr = dummy
    else:
        dummyl, dummyr = dummy

    if dummyl:
        dummy_L = __mult_array_macro(
                pdk,
                active_area=active_area,
                bjt_type=bjt_type,
                multipliers=len(t_pattern[0]),
                routing=routing,
                dummy=(True,False),
                bc_route_topmet=bc_route_topmet,
                emitter_route_topmet=emitter_route_topmet,
                bc_route_left=bc_route_left,
                bc_rmult=bc_rmult,
                emitter_rmult=emitter_rmult,
                dummy_routes=dummy_routes,
                pattern=t_pattern[0],
                is_bc_short=is_bc_short,
                is_bc_shared=is_bc_shared,
                centered=False,
                dummy_separation_rmult=dummy_separation_rmult
            )
        l_cols[0]=dummy_L

    if dummyr:
        dummy_R = __mult_array_macro(
                pdk,
                active_area=active_area,
                bjt_type=bjt_type,
                multipliers=len(t_pattern[-1]),
                routing=routing,
                dummy=(False,True),
                bc_route_topmet=bc_route_topmet,
                emitter_route_topmet=emitter_route_topmet,
                bc_route_left=bc_route_left,
                bc_rmult=bc_rmult,
                emitter_rmult=emitter_rmult,
                dummy_routes=dummy_routes,
                pattern=t_pattern[-1],
                is_bc_short=is_bc_short,
                is_bc_shared=is_bc_shared,
                centered=False,
                dummy_separation_rmult=dummy_separation_rmult
            )
        l_cols[-1]=dummy_R


    _max_metal_separation_ps = max([pdk.get_grule("met"+str(i))["min_separation"] for i in range(1,5)])
    min_diff_separation = max(pdk.get_grule("n+s/d")["min_separation"],pdk.get_grule("p+s/d")["min_separation"])
    routing_separation = max([ _max_metal_separation_ps, min_diff_separation])
    multiplier_separation = to_decimal(
        float(routing_separation) + max_width
    )

    for colnum in range(len(l_cols)):
        col_displacment = colnum * multiplier_separation - (multiplier_separation/2 * (len(l_cols)-1))
        col_ref = multiplier_2dim_arr << l_cols[colnum]
        col_ref.movex(to_float(col_displacment))
        multiplier_2dim_arr.add_ports(
            col_ref.get_ports_list(), prefix="col_" + str(colnum) + "_"
        )

    # routing 
    # get position for unique elements from the pattern
    element_positions = get_cols_positions(pattern)
    print(element_positions)


    # using the C route will use the port width to make the routing
    # then we can check the width for it and add the required space accordingly
    # we assume the width is the same in west as the east

    sample_element = list(element_positions.keys())[0]
    sample_col=element_positions[sample_element][0]
    if not is_bc_shared:
        sample_base_port="col_"+ str(sample_col) +"_" + sample_element + "_base_S"
        sample_collector_port=( "col_"+ str(sample_col)+"_" + sample_element +
                               "_collector_S" ) if not is_bc_short else sample_base_port
    else:
        sample_base_port="col_"+ str(sample_col) +"_base_S"
        sample_collector_port= sample_base_port

    base_port_width= multiplier_2dim_arr[sample_base_port].width
    collector_port_width = multiplier_2dim_arr[sample_collector_port].width
    bc_distance = base_port_width/2 + collector_port_width/2 + 2*pdk.get_grule("met4")["min_separation"]

    print(sample_base_port)
    print(sample_collector_port)
    print(bc_distance)

    bc_side = "S" if bc_route_bottom else "N"
    e_side = "N" if bc_route_bottom else "S"

    if not is_bc_shared:
        if not is_bc_short:
            pins = ["collector", "base", "emitter"]
            sides = [bc_side, bc_side, e_side]
            distances = [0, bc_distance, 0]
            shift_factors = [2, 2, 1]
        else:
            pins = ["base", "emitter"]
            sides = [bc_side, e_side]
            distances = [0, 0]
            shift_factors = [1, 1]
    else:
        pins = ["emitter"]
        sides = [e_side]
        distances = [0]
        shift_factors = [ 1]

    if is_bc_shared:
        for n in range(len(pattern[0])-1):
            this_portpfx = "col_" + str(n) + "_"
            next_portpfx = "col_" + str(n+1) + "_"
            this_port = this_portpfx + "base_" + bc_side
            next_port = next_portpfx + "base_" + bc_side

            ref = multiplier_2dim_arr << c_route(pdk,
                                                      multiplier_2dim_arr.ports[this_port],
                                                      multiplier_2dim_arr.ports[next_port],
                                                  viaoffset=(True,False),
                                                  extension=0)
            multiplier_2dim_arr.add_ports(ref.get_ports_list(),
                                          prefix="_".join(["route",
                                                           str(n),
                                                           "base"]))


    correction_factor=0
    for n, element in enumerate(element_positions.keys()):

        print(n , element)
        if len(element_positions[element])==1:
            correction_factor+=1
            continue

        element_shift = (n - correction_factor )*bc_distance
        l_positions = element_positions[element]
        for i_pos in range(len(l_positions)-1):
            this_portpfx = "col_" + str(l_positions[i_pos]) + "_" + element + "_"
            next_portpfx = "col_" + str(l_positions[i_pos+1]) + "_" + element + "_"

            for pin, side, distance, shift_factor in list(zip(pins,sides,distances, shift_factors)):

                this_port = this_portpfx + pin + "_" +side
                next_port = next_portpfx + pin + "_" +side

                print(this_port)
                print(next_port)

                ref = multiplier_2dim_arr << c_route(pdk,
                                                          multiplier_2dim_arr.ports[this_port],
                                                          multiplier_2dim_arr.ports[next_port],
                                                      viaoffset=(True,False),
                                                      extension=to_float(distance)+element_shift*shift_factor)
                multiplier_2dim_arr.add_ports(ref.get_ports_list(),
                                              prefix="_".join(["route",
                                                               element,
                                                               str(l_positions[i_pos]),
                                                               pin]))


    return multiplier_2dim_arr

def pnp(
    pdk,
    active_area: tuple[float,float] = (5.,5.),
    multipliers: int = 1,
    with_substrate_tap: Optional[bool] = True,
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    bc_route_topmet: str = "met2",
    emitter_route_topmet: str = "met2",
    bc_route_left: bool = True,
    rmult: Optional[int] = None,
    bc_rmult: int=1,
    emitter_rmult: int=1,
    substrate_tap_layers: tuple[str,str] = ("met2","met1"),
    dummy_routes: bool=True,
    pattern: Union[list[str], list[int], None] = None,
    is_bc_short: bool = False,
    is_bc_shared: bool = False
) -> Component:
    """Generic NMOS generator
    pdk: mapped pdk to use
    active_area: active area of the npn emitter
    multipliers: number of multipliers (a multiplier is a row of fingers)
    with_dummy: tuple(bool,bool) or bool specifying both sides dummy or neither side dummy
    ****using the tuple option, you can specify a single side dummy such as true,false
    with_substrate_tap: add substrate tap on the very outside perimeter of nmos
    bc_route_topmet: specify top metal glayer for the base/collector route
    emitter_route_topmet: specify top metal glayer for the gate route
    bc_route_left: specify if the source/drain inter-multiplier routes should be on the left side or right side (if false)
    rmult: if not None overrides all other multiplier options to provide a simple routing multiplier (int only)
    bc_rmult: mulitplies the thickness of the source drain route (int only)
    emitter_rmult: add additional via rows to the gate route via array (int only) - Currently not supported
    substrate_tap_layers: tuple[str,str] specifying (horizontal glayer, vertical glayer) or substrate tap ring. default=("met2","met1")
    dummy_routes: bool default=True, if true add add vias and short dummy emitter, collector and base
    """
    pdk.activate()
    pnp = Component()
    if rmult:
        if rmult<1:
            raise ValueError("rmult must be positive int")
        bc_rmult = rmult
        emitter_rmult = 1
    # create and add multipliers to bjt

    level = check_pattern_level(pattern)
    #print(level)
    __macro =  __mult_array_macro if level<=1 else __mult_2dim_array_macro
    multiplier_arr = __macro(
        pdk,
        active_area,
        "pnp",
        multipliers,
        routing=True,
        dummy=with_dummy,
        bc_route_topmet=bc_route_topmet,
        emitter_route_topmet=emitter_route_topmet,
        bc_route_left=bc_route_left,
        bc_rmult=bc_rmult,
        emitter_rmult=emitter_rmult,
        dummy_routes=dummy_routes,
        pattern=pattern,
        is_bc_short=is_bc_short,
        is_bc_shared=is_bc_shared
    )
    multiplier_arr_ref = multiplier_arr.ref()
    pnp.add(multiplier_arr_ref)
    pnp.add_ports(multiplier_arr_ref.get_ports_list())
    # add substrate if substrate
    if with_substrate_tap:
        tap_separation = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule("n+s/d", "active_tap")["min_enclosure"]
        tap_encloses = (
            2 * (tap_separation + pnp.xmax),
            2 * (tap_separation + pnp.ymax),
        )
        substrate_ref = pnp << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="n+s/d",
            horizontal_glayer=substrate_tap_layers[0],
            vertical_glayer=substrate_tap_layers[1],
        )
        pnp.add_ports(substrate_ref.get_ports_list(), prefix="substrate_")

        if isinstance(with_dummy, bool):
            dummyl = dummyr = with_dummy
        else:
            dummyl, dummyr = with_dummy

        n_dummies = multipliers if level<=1 else multipliers[1]
        for row in range(n_dummies):
            if dummyl:
                dummy_port_name = f"multiplier_{row}_dummy_L_C_metal_W_W"
                if level >1:
                    dummy_port_name = "col_0_" + dummy_port_name
                pnp<<straight_route(pdk,pnp.ports[dummy_port_name],pnp.ports[f"substrate_W_top_met_W"],glayer2="met1")
            if dummyr:
                dummy_port_name = f"multiplier_{row}_dummy_R_C_metal_E_E"
                if level >1:
                    dummy_port_name = "col_" + str(multipliers[0]-1) + "_" + dummy_port_name
                pnp<<straight_route(pdk,pnp.ports[dummy_port_name],pnp.ports[f"substrate_E_top_met_E"],glayer2="met1")

    component =  rename_ports_by_orientation(pnp).flatten()

    #component.info['netlist'] = fet_netlist(
    #    pdk,
    #    circuit_name="PNP",
    #    model=pdk.models['pnp'],
    #    multipliers=multipliers,
    #    with_dummy=with_dummy
    #)

    return component

def npn(
    pdk,
    active_area: tuple[float,float] = (5.,5.),
    multipliers: int = 1,
    with_dnwell: Optional[bool] = True,
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool=True,
    bc_route_topmet: str = "met2",
    emitter_route_topmet: str = "met2",
    bc_route_left: bool = True,
    rmult: Optional[int] = None,
    bc_rmult: int=1,
    emitter_rmult: int=1,
    substrate_tap_layers: tuple[str,str] = ("met2","met1"),
    dummy_routes: bool=True,
    pattern: Union[list[str], list[int], None] = None,
    is_bc_short: bool = False
) -> Component:
    """Generic NMOS generator
    pdk: mapped pdk to use
    active_area: active area of the npn emitter
    multipliers: number of multipliers (a multiplier is a row of fingers)
    with_dummy: tuple(bool,bool) or bool specifying both sides dummy or neither side dummy
    ****using the tuple option, you can specify a single side dummy such as true,false
    with_substrate_tap: add substrate tap on the very outside perimeter of nmos
    bc_route_topmet: specify top metal glayer for the base/collector route
    emitter_route_topmet: specify top metal glayer for the gate route
    bc_route_left: specify if the source/drain inter-multiplier routes should be on the left side or right side (if false)
    rmult: if not None overrides all other multiplier options to provide a simple routing multiplier (int only)
    bc_rmult: mulitplies the thickness of the source drain route (int only)
    emitter_rmult: add additional via rows to the gate route via array (int only) - Currently not supported
    substrate_tap_layers: tuple[str,str] specifying (horizontal glayer, vertical glayer) or substrate tap ring. default=("met2","met1")
    dummy_routes: bool default=True, if true add add vias and short dummy emitter, collector and base
    """
    pdk.activate()
    npn = Component()
    if rmult:
        if rmult<1:
            raise ValueError("rmult must be positive int")
        bc_rmult = rmult
        emitter_rmult = 1
    # create and add multipliers to bjt
    multiplier_arr = __mult_array_macro(
        pdk,
        active_area,
        "npn",
        multipliers,
        routing=True,
        dummy=with_dummy,
        bc_route_topmet=bc_route_topmet,
        emitter_route_topmet=emitter_route_topmet,
        bc_route_left=bc_route_left,
        bc_rmult=bc_rmult,
        emitter_rmult=emitter_rmult,
        dummy_routes=dummy_routes,
        pattern=pattern,
        is_bc_short=is_bc_short
    )
    multiplier_arr_ref = multiplier_arr.ref()
    npn.add(multiplier_arr_ref)
    npn.add_ports(multiplier_arr_ref.get_ports_list())

    # add nwell
    nwell_glayer = "dnwell" if with_dnwell else "nwell"
    npn.add_padding(
        layers=(pdk.get_glayer(nwell_glayer),),
        default=pdk.get_grule("dnwell", "pwell")["min_enclosure"],
    )
    npn = add_ports_perimeter(npn,layer=pdk.get_glayer(nwell_glayer),prefix="well_")

    # Required for DRC the BJT_DRC layer
    npn.add_padding(
        layers=(pdk.get_glayer("drc_bjt"),),
        default=0,
    )

    # add substrate tap if with_substrate_tap
    if with_substrate_tap:
        substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")[
            "min_separation"
        ]
        substrate_tap_encloses = (
            2 * (substrate_tap_separation + npn.xmax),
            2 * (substrate_tap_separation + npn.ymax),
        )
        substrate_ref = npn << tapring(
            pdk,
            enclosed_rectangle=substrate_tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer=substrate_tap_layers[0],
            vertical_glayer=substrate_tap_layers[1],
        )

        npn.add_ports(substrate_ref.get_ports_list(), prefix="substrate_")

        if isinstance(with_dummy, bool):
            dummyl = dummyr = with_dummy
        else:
            dummyl, dummyr = with_dummy

        for row in range(multipliers):
            if dummyl:
                npn<<straight_route(pdk,npn.ports[f"multiplier_{row}_dummy_L_C_metal_W_W"],npn.ports[f"substrate_W_top_met_W"],glayer2="met1")
            if dummyr:
                npn<<straight_route(pdk,npn.ports[f"multiplier_{row}_dummy_R_C_metal_E_E"],npn.ports[f"substrate_E_top_met_E"],glayer2="met1")


    component =  rename_ports_by_orientation(npn).flatten()

    #component.info['netlist'] = fet_netlist(
    #    pdk,
    #    circuit_name="NPN",
    #    model=pdk.models['npn'],
    #    multipliers=multipliers,
    #    with_dummy=with_dummy
    #)

    return component
