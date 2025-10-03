"""
This current mirror was generated as part of the AutoMOS project, Chipathon
2025

It is based on macros included in the fet generator and the feature of pattern
generation.

To use this generator there is a constraint that each of the branches must be
pair (multiple of two). This is because the pattern is generated to guarantee
simetry and keep the reference diodes at the middle

"""

from glayout.routing import c_route, straight_route, L_route
from glayout.util.pattern import flatten_array
from glayout.primitives.fet import nmos, pmos
from gdsfactory.component import Component
from glayout.util.comp_utils import align_comp_to_port, evaluate_bbox
import math


def generate_pattern_current_mirror(m_ref: int, m_outputs: list[int], nrows=1):


    m_half_ref = m_ref/nrows/2
    m_half_outputs = [output/nrows/2 for output in m_outputs]

    half_array_r = [0] *int(m_half_ref)
    half_array_l = [0] *int(m_half_ref)

    count_even = 0
    for index,quantity in enumerate(m_half_outputs):
        if quantity%2 ==0:
            half_array_r += [ index+1 ]*int(quantity)
            half_array_l += [ index+1 ]*int(quantity)
        else:
            count_even += 1
            operation = math.floor if count_even%2 == 0 else math.ceil

            half_array_r += [ index+1 ]*operation(quantity)
            half_array_l += [ index+1 ]*(int(quantity*2) -
                                         operation(quantity))

    array =  half_array_l[::-1] + half_array_r

    dim2_array = []
    c_array = array
    for nrows  in range(nrows):
        # If we apply the reverse for next rows it loses alignment and is prone
        # to DRC errors
        #c_array.reverse()
        #n_array = c_array.copy()
        dim2_array = dim2_array + [c_array]

    return dim2_array

def simple_current_mirror(pdk, fet_type="nmos", domain="3p3", width=3, length=1, fingers=1,
                          with_dnwell = False, with_tie = True,
                          with_substrate_tap=False,
                          m_ref= 2 , m_outputs= [2, 2], nrows=1,
                          prefix="ref",
                          is_src_shared =True,
                          is_diode_connected=True,
                          is_bs_connected=True):


    pattern_index= generate_pattern_current_mirror(m_ref,
                                                   m_outputs,
                                                   nrows=nrows)
    pattern = [[prefix + str(index) for index in sublist] for sublist in pattern_index]

    print(f"Generated pattern: {pattern}")

    generator = nmos if fet_type=="nmos" else pmos

    multipliers = (len(pattern[0]), len(pattern))

    component =  generator(pdk,
                     domain=domain,
                     width= width,
                     length=length,
                     fingers=fingers,
                     multipliers=multipliers,
                     with_dnwell=with_dnwell,
                     with_tie=with_tie,
                     with_substrate_tap=with_substrate_tap,
                     pattern=pattern,
                     is_gate_shared=True,
                     is_src_shared=is_src_shared)

    if (is_diode_connected):
        diode_prefix = prefix + str(0)
        print(f"Using {diode_prefix}")
        indexes = [ n for n, element in
                   enumerate(pattern[0])
                   if element == diode_prefix]

        print(f"got indexes {indexes}")
        dside = "N" if fet_type == "nmos" else "S"
        for index in indexes:
            drain_port_name = "col_" + str(index) + "_" + pattern[0][index] + "_drain_" + dside
            gate_port_name = "col_" + str(index) + "_gate_" + dside

            ref= component << c_route(pdk,
                                 component.ports[drain_port_name],
                                 component.ports[gate_port_name],
                                 viaoffset=(True,False),
                                 extension=0
                                 )
            component.add_ports(ref.get_ports_list(),
                                              prefix="_".join(["route",
                                                               str(index),
                                                               "diode"]))

    # short circuit bulk with source
    if (is_bs_connected and is_src_shared):
        sside = "S" if fet_type == "nmos" else "N"
        bside = "N" if fet_type == "nmos" else "S"

        ref_bulk_port = ("tie_" + sside + "_array_row0_col0_top_met_"
                         + bside)

        for index in range(len(pattern[0])):
            src_port_name = ("col_" + str(index)
                             +"_source_" + sside)

            bs_route_ref = component << straight_route(pdk,
                                                       component.ports[src_port_name],
                                                       component.ports[ref_bulk_port])

            component.add_ports(bs_route_ref.get_ports_list(),
                                prefix="bs_route_"+str(index)+"_")


    return component



def cascoded_current_mirror (pdk, fet_type="nmos", domain="3p3",
                             width=3, length=1, fingers=1,
                             width_cascode=3, length_cascode=1, fingers_cascode=1,
                          with_dnwell = False, with_tie = True,
                          with_substrate_tap=False,
                          m_ref= 2 , m_outputs= [2, 2], nrows=1,
                          prefix="ref",
                          is_simple_cascode=False,
                          short_gate_drain_cascode=True):


    pattern_index= generate_pattern_current_mirror(m_ref,
                                                   m_outputs,
                                                   nrows=nrows)
    pattern = [[prefix + str(index) for index in sublist] for sublist in pattern_index]

    print(f"Generated pattern: {pattern}")

    generator = nmos if fet_type=="nmos" else pmos

    multipliers = (len(pattern[0]), len(pattern))


    mirror = simple_current_mirror(pdk, fet_type=fet_type,
                                      domain=domain,
                             width=width, length=length, fingers=fingers,
                          with_dnwell = with_dnwell, with_tie = with_tie,
                          with_substrate_tap=with_substrate_tap,
                          m_ref= m_ref , m_outputs= m_outputs, nrows=nrows,
                          prefix=prefix,
                          is_src_shared =True,
                          is_diode_connected=is_simple_cascode,
                          is_bs_connected=True)

    cascode = simple_current_mirror(pdk, fet_type=fet_type,
                                      domain=domain,
                             width=width_cascode,
                          length=length_cascode,
                          fingers=fingers_cascode,
                          with_dnwell = with_dnwell, with_tie = with_tie,
                          with_substrate_tap=with_substrate_tap,
                          m_ref= m_ref , m_outputs= m_outputs, nrows=nrows,
                          prefix=prefix,
                          is_src_shared =False,
                          is_diode_connected=is_simple_cascode,
                          is_bs_connected=False)

    dside = "N" if fet_type == "nmos" else "S"
    sside = "S" if fet_type == "nmos" else "N"
    factor = 1 if fet_type == "nmos" else -1

    component = Component()

    mirror_ref = component << mirror
    cascode_ref = component << cascode

    distance = 0.7

    shift = (mirror.ymax - cascode.ymin) if fet_type=="nmos" else (cascode.ymax - mirror.ymin)

    cascode_ref.movey(factor*pdk.snap_to_2xgrid(shift + distance))

    component.add_ports(mirror_ref.get_ports_list(), prefix="m_")
    component.add_ports(cascode_ref.get_ports_list(), prefix="c_")


    for index, element in enumerate(pattern[0]):
        findex = pattern[0].index(element)
        source_port = "c_col_" + str(index) + "_" + element + "_source_" + sside
        drain_port = "m_route_" + element + "_" +  str(findex) + "_draincon_" + "W"

        distance_target = component.ports[drain_port].center[0]-component.ports[source_port].center[0]
        ref_route = component << L_route(pdk,
                                    component.ports[source_port],
                                    component.ports[drain_port])
        component.add_ports(ref_route.get_ports_list(), prefix="cm_route_"+
                            str(index)+"_")

    if short_gate_drain_cascode:
        ref_left = "m_col_0_multiplier_0_dummy_L_gsdcon_top_met_W"
        ref_right = f"m_col_{len(pattern[0])-1}_multiplier_0_dummy_R_gsdcon_top_met_E"

        gate_port_l = "m_route_0_gatecon_W"
        gate_port_r =  f"m_route_{len(pattern[0])-2}_gatecon_E"

        distance_left = (component.ports[ref_left].center[0] -
                                    component.ports[gate_port_l].center[0])

        distance_right = (component.ports[ref_right].center[0] -
                                    component.ports[gate_port_r].center[0])

        findex = pattern[0].index(prefix + "0")
        drain_port_l = "c_route_" + prefix + "0_" + str(findex) + "_draincon_W"
        drain_port_r = "c_route_" + prefix + "0_" + str(findex) + "_draincon_E"

        wroute = component << c_route(pdk,
                                     component.ports[gate_port_l],
                                     component.ports[drain_port_l],
                                     cglayer="met3",extension=-distance_left)

        eroute = component << c_route(pdk,
                                     component.ports[gate_port_r],
                                     component.ports[drain_port_r],
                                     cglayer="met3",extension=distance_right)

        component.add_ports(wroute.get_ports_list(), prefix="gd_route_W_"+"_")
        component.add_ports(eroute.get_ports_list(), prefix="gd_route_E_"+"_")

    return component

def wide_swing_current_mirror(pdk, fet_type="nmos", domain="3p3",
                             width=3, length=1, fingers=1,
                             width_cascode=3, length_cascode=1, fingers_cascode=1,
                             width_cascode_ref=3, length_cascode_ref=1,
                              fingers_cascode_ref=1,
                              multipliers_cascode_ref=(1,2),
                          with_dnwell = False, with_tie = True,
                          with_substrate_tap=False,
                          m_ref= 2 , m_outputs= [2, 2], nrows=1,
                          prefix="ref",
                          short_gate_drain_cascode=True,
                          distance_ref=2,
                         ):


    component = cascoded_current_mirror(pdk, fet_type=fet_type,
                          domain=domain,
                          width=width, length=length, fingers=fingers,
                          width_cascode=width_cascode,
                                        length_cascode=length_cascode,
                                        fingers_cascode=fingers_cascode,
                          with_dnwell = with_dnwell, with_tie = with_tie,
                          with_substrate_tap=with_substrate_tap,
                          m_ref= m_ref , m_outputs= m_outputs, nrows=nrows,
                          prefix=prefix,
                          is_simple_cascode=False,
                          short_gate_drain_cascode=short_gate_drain_cascode
    )

    cascode_ref = fet_unit(pdk,
                     fet_type=fet_type,
                     domain=domain,
                     width= width_cascode_ref,
                     length=length_cascode_ref,
                     fingers=fingers_cascode_ref,
                     multipliers=multipliers_cascode_ref,
                     with_dnwell=with_dnwell,
                     with_tie=with_tie,
                     with_substrate_tap=with_substrate_tap,
                     with_dummy = True,
                     is_bs_connected=True,
                     is_diode_connected=True)

    height_wo_ref = component.ymax
    cascode_ref_height = cascode_ref.ymax

    cascode_align = component.ports["c_tie_W_array_row0_col0_top_met_W"]
    reference_align = component.ports["m_tie_W_array_row0_col0_top_met_W"]

    selected_align = (cascode_align if cascode_align.center[0] <
                    reference_align.center[0] else reference_align)

    ref = component <<align_comp_to_port(cascode_ref,
                       selected_align,
                       alignment=("l",None),rtr_comp_ref=False)

    ref.movex(-pdk.util_max_metal_seperation()- pdk.snap_to_2xgrid(distance_ref))
    ref.movey(height_wo_ref-cascode_ref_height)

    component.add_ports(ref.get_ports_list(), prefix="cref_")

    dside = "N" if fet_type == "nmos" else "S"

    port_gate_cref = "cref_col_" + str(0) + "_gate_" + dside
    port_gate_c = "c_route_0_gatecon_W"

    route_ref = component << L_route(pdk,
                                     component.ports[port_gate_cref],
                                     component.ports[port_gate_c],
                                     )

    component.add_ports(route_ref.get_ports_list(), prefix="gg_route")

    return component


def fet_unit(pdk, fet_type="nmos", domain="3p3",
                             width=3, length=1, fingers=1,
                              multipliers=(1,2),
                          with_dnwell = False, with_tie = True,
                          with_substrate_tap=False,
                          prefix="ref",
                          is_diode_connected=False,
                          is_bs_connected=False,
                          is_cap_connected=False,
                          with_dummy = False,
                            ):

    generator = nmos if fet_type=="nmos" else pmos


    if len(multipliers )>1:
        pattern = [[prefix]*multipliers[0]]*multipliers[1]
    else:
        pattern = None
    component = generator(pdk,
                     domain=domain,
                     width= width,
                     length=length,
                     fingers=fingers,
                     multipliers=multipliers,
                     with_dnwell=with_dnwell,
                     with_tie=with_tie,
                     with_substrate_tap=with_substrate_tap,
                     pattern=pattern,
                     with_dummy=with_dummy,
                     is_gate_shared=True,
                     is_src_shared=True)


    sside = "S" if fet_type == "nmos" else "N"
    bside = "N" if fet_type == "nmos" else "S"
    dside = "N" if fet_type == "nmos" else "S"

    ref_bulk_port = ("tie_" + sside + "_array_row0_col0_top_met_"
                     + bside)

    for index in range(len(pattern[0])):

        if is_bs_connected:
            src_port_name = ("col_" + str(index)
                             +"_source_" + sside)

            bs_route_ref = component << straight_route(pdk,
                                                       component.ports[src_port_name],
                                                       component.ports[ref_bulk_port])

            component.add_ports(bs_route_ref.get_ports_list(),
                                prefix="bs_route_"+str(index)+"_")

        if is_diode_connected:
            drain_port_name = ("col_" + str(index) + "_" +
                               pattern[0][index] + "_drain_" + dside)
            gate_port_name = "col_" + str(index) + "_gate_" + dside

            ref= component << c_route(pdk,
                                 component.ports[drain_port_name],
                                 component.ports[gate_port_name],
                                 viaoffset=(True,False),
                                 extension=0
                                 )
            component.add_ports(ref.get_ports_list(),
                                              prefix="_".join(["route",
                                                               str(index),
                                                               "diode"]))
        if is_cap_connected:

            ds_port_name = ("col_" + str(index) + "_" +
                               pattern[0][index] + "_drain_" + sside)

            src_route_name = ("col_" + str(index) +
                                "_source_" + sside)

            ds_route_ref = component << c_route(pdk,
                                                       component.ports[ds_port_name],
                                                       component.ports[src_route_name],
                                                 extension=0)

            component.add_ports(ds_route_ref.get_ports_list(),
                                prefix="ds_route_"+str(index)+"_")

    return component
