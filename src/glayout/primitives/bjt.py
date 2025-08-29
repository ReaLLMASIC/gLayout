from sys import prefix
import numpy as np
from typing import Any
from glayout import MappedPDK, sky130 , gf180
from glayout.util.geometry import evaluate_bbox, to_float
from glayout.util.comp_utils import prec_center, prec_array, prec_ref_center, to_float
#from gdsfactory.cell import cell
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

    print(l_metal_dims)
    component = Component()

    for direction in l_metal_dims:

        print(l_metal_dims[direction])
        contacts = component << fill_area_with_contacts(pdk,
                                           l_metal_dims[direction]["size"],
                                           l_metal_center_position[direction],
                                           contact_layer,
                                           padding,
                                           spacing,
                                           contact_size)
        component.add_ports(contacts.get_ports_list(), prefix=f"contacts_{direction}_")

    return component

def get_bjt_dimensions (pdk: MappedPDK, active_area: tuple[float], bjt_type: str)-> dict[str,Any]:
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
    drc = {"size": (np.asarray(collector["enclosed_size"]) +
           2*collector["width"])  if bjt_type=="pnp" else dnwell["size"] }


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


def draw_bjt(pdk: MappedPDK, active_area: tuple[float], bjt_type: str)->Component:

    component = Component()

    # Validate the size parameter
    if bjt_type not in pdk.valid_bjt_sizes.keys():
        raise ValueError(f"Not a valid type of bjt: {bjt_type}.\n"
                         f"Valid options are: {list(pdk.valid_bjt_sizes.keys())}")

    if active_area not in  pdk.valid_bjt_sizes[bjt_type]:
        raise ValueError(f"Not a valid size for the bjt: {active_area}.\n"
                         f"Valid options are: {pdk.valid_bjt_sizes[bjt_type]}")

    dims=get_bjt_dimensions(pdk,active_area,bjt_type)
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
    if bjt_type=="npn":
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

    metal_e = component << rectangle(layer=pdk.get_glayer("met1"),
                                     centered=True, **dims["emitter_active"])
    component.add_ports(metal_e.get_ports_list(), prefix="E_")

    component.add_label("E",position=metal_e.center,layer=pdk.get_glayer("met1"))

    metal_b = component << draw_metal_over_ring(pdk,dims["base_active"],"met1","B")
    component.add_ports(metal_b.get_ports_list(), prefix="B_")

    metal_c = component << draw_metal_over_ring(pdk,dims["collector_active"],"met1","C")
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

    return component
