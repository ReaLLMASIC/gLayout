from glayout import MappedPDK, sky130, gf180
from glayout import nmos, pmos, multiplier, tapring, via_stack, via_array

from glayout.spice.netlist import Netlist
from glayout.routing import c_route, L_route, straight_route

from gdsfactory.cell import cell
from gdsfactory.component import Component, copy
from gdsfactory.components.rectangle import rectangle
from gdsfactory.routing.route_quad import route_quad
from gdsfactory.routing.route_sharp import route_sharp

from glayout.util.comp_utils import (
    align_comp_to_port,
    evaluate_bbox,
    movex,
    movey,
    prec_ref_center,
    prec_array,
)
from glayout.util.port_utils import (
    add_ports_perimeter,
    get_orientation,
    print_ports,
    rename_ports_by_list,
    rename_ports_by_orientation,
    set_port_orientation,
)
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.placement.common_centroid_ab_ba import common_centroid_ab_ba

from gdsfactory.functions import transformed
from gdsfactory.components import text_freetype
from gdsfactory.components.rectangular_ring import rectangular_ring
from typing import Optional, Union, Literal
import time
import copy


def macro_two_transistor_placement_Onchip(
    pdk: MappedPDK,
    deviceA_and_B: Literal["nfet", "pfet"],
    width_route_mult: float = 1,
    with_substrate_tap: bool = False,
    with_tie: bool = True,
    width1: float = 1,
    length1: float = 2,
    fingers1: int = 1,
    matriz: list = [[1, 2, 1], [2, 1, 2]],
    with_dummy: bool = False,
    with_lvt_layer: bool = True,
    full_output_size: bool = False,
    **kwargs,
) -> Component:
    # This code was made by Sebastian Suarez y Jose Algarin, UIS Electronic engineering students
    """Two transistors Placement generator
    args:
    pdk = pdk to use
    deviceA_and_B = the device to place for both transistors (either nfet or pfet)
    width_route_mult = thickness of metal routes escaled (int only)
    with_substrate_tap = add substrate tap
    with_tie = Add Bulk connections
    width1 = expands the transistor A in the y direction
    width2 = expands the transistor B in the y direction
    length1 = transitor A length
    length2 = transitor B length
    fingers1 = introduces additional fingers to transistor A (sharing s/d) of width=width1
    fingers2 = introduces additional fingers to transistor B (sharing s/d) of width=width2
    matriz = Devices array for placement
    with_dummy =  Add dummys around placement
    with_lvt_layer = add lvt layer

    ports (one port for each edge),
    ****NOTE: source is below drain:
    A_source_... all edges (met3 vertical met4 horizontal)
    B_source_... all edges (met3 vertical met4 horizontal)
    A_gate_... all edges (met3 vertical met4 horizontal)
    B_gate_... all edges (met3 vertical met4 horizontal)
    A_drain_... all edges (met3 vertical met4 horizontal)
    B_drain_... all edges (met3 vertical met4 horizontal)
    bulk_... all edges (met3 vertical met4 horizontal)
    """
    pdk_gf180 = False
    pdk_sky130 = True
    if pdk is gf180:
        pdk_gf180 = True
        pdk_sky130 = False
    elif pdk is sky130:
        pdk_gf180 = False
        pdk_sky130 = True

    if width_route_mult > 5 or width_route_mult < 0:
        raise ValueError("width_route is out of range")

    matplace = Component()
    matriz = copy.deepcopy(matriz)
    enable_B = False
    for fila in matriz:
        for transistor in fila:
            if transistor == 2:
                enable_B = True
                break
    # Add dummys to array (matriz)
    if with_dummy:
        len_matriz_with_dumys = len(matriz[0]) + 2
        for row in matriz:
            row.insert(0, 0)
            row.append(0)
        matriz.insert(0, [0] * len_matriz_with_dumys)
        matriz.insert(len(matriz), [0] * len_matriz_with_dumys)
    # Check if rows are are odd or even
    if (len(matriz)) % 2 == 0:
        middle_transistor = len(matriz) // 2
        even = True
    else:
        even = False
    matrizT = [list(fila) for fila in zip(*matriz)]
    # Overwrite kwargs for needed options
    kwargs["sdlayer"] = "n+s/d" if deviceA_and_B == "nfet" else "p+s/d"
    kwargs["pdk"] = pdk
    kwargs["dummy"] = (False, False)
    # Insert modifications for dummies
    kwargs["routing"] = False
    kwargs["gate_route_extension"] = pdk.snap_to_2xgrid(0)
    if with_dummy:
        dummy_single_down = multiplier(
            width=width1, length=length1, fingers=1, gate_down=True, **kwargs
        )
        dummy_single_up = multiplier(
            width=width1, length=length1, fingers=1, gate_up=True, **kwargs
        )
        devDT = multiplier(
            width=width1, length=length1, fingers=fingers1, gate_up=True, **kwargs
        )
        devDB = multiplier(
            width=width1, length=length1, fingers=fingers1, gate_down=True, **kwargs
        )
    # Insert modifications for device A
    kwargs["routing"] = True
    devA_gate_extension = (
        abs(pdk.get_grule("met2")["min_separation"] + devDT.ports["gate_W"].width)
        if with_dummy
        else abs(pdk.get_grule("met2")["min_separation"])
    )
    devA_sd_extension = abs(pdk.get_grule("met2")["min_separation"])
    kwargs["gate_route_extension"] = pdk.snap_to_2xgrid(devA_gate_extension)
    kwargs["sd_route_extension"] = pdk.snap_to_2xgrid(devA_sd_extension)
    devA = multiplier(
        width=width1, length=length1, fingers=fingers1, rmult=width_route_mult, **kwargs
    )
    # Insert kwarg modfications for device B
    devB_sd_extension = abs(
        devA.ports["drain_N"].center[1] - devA.ports["diff_N"].center[1]
    )
    devB_gate_extension = (
        abs(2 * (pdk.get_grule("met2")["min_separation"] + devA.ports["gate_W"].width))
        if with_dummy
        else abs(
            2 * pdk.get_grule("met2")["min_separation"] + devA.ports["gate_W"].width
        )
    )
    kwargs["sd_route_extension"] = pdk.snap_to_2xgrid(devB_sd_extension)
    kwargs["gate_route_extension"] = pdk.snap_to_2xgrid(devB_gate_extension)
    devB = multiplier(
        width=width1, length=length1, fingers=fingers1, rmult=width_route_mult, **kwargs
    )
    # Create the array of transistors
    transistors = list()
    for i in range(len(matriz)):
        transistors_in_row = list()
        for j in range(len(matriz[i])):
            if i == 0 or i == len(matriz) - 1:  # first and last row
                if j == 0 or j == len(matriz[i]) - 1:  # first and last column
                    # corner transistors
                    if matriz[i][j] == 0 and i == 0:
                        # small dummy
                        transistors_in_row.append(matplace << dummy_single_down)
                    elif matriz[i][j] == 0 and i == len(matriz) - 1:
                        # small dummy
                        transistors_in_row.append(matplace << dummy_single_up)
                    else:
                        if matriz[i][j] == 1:
                            transistors_in_row.append(matplace << devA)
                        elif matriz[i][j] == 2:
                            transistors_in_row.append(matplace << devB)
                elif i == 0:  # first row
                    # first row transistors
                    if matriz[i][j] == 0:
                        # dummy
                        transistors_in_row.append(matplace << devDB)
                    else:
                        if matriz[i][j] == 1:
                            transistors_in_row.append(matplace << devA)
                        elif matriz[i][j] == 2:
                            transistors_in_row.append(matplace << devB)
                else:  # last row
                    # last row transistors
                    if matriz[i][j] == 0:
                        # dummy
                        transistors_in_row.append(matplace << devDT)
                    else:
                        if matriz[i][j] == 1:
                            transistors_in_row.append(matplace << devA)
                        elif matriz[i][j] == 2:
                            transistors_in_row.append(matplace << devB)
            else:  # middle rows
                if matriz[i][j] == 0:
                    # small dummy
                    transistors_in_row.append(matplace << dummy_single_down)
                else:
                    if matriz[i][j] == 1:
                        transistors_in_row.append(matplace << devA)
                    elif matriz[i][j] == 2:
                        transistors_in_row.append(matplace << devB)

        # Add the transistors in the row
        transistors.append(transistors_in_row)
    # min separation
    min_separation_x = pdk.snap_to_2xgrid(pdk.get_grule("p+s/d")["min_separation"])
    if pdk == sky130:
        min_separation = pdk.get_grule("poly")["min_separation"]
    elif pdk == gf180:
        min_separation = pdk.get_grule("met2")["min_separation"]
    for i in range(len(transistors)):
        # Move the transistors in y direction
        if i == 0:
            # first row dont move
            ymove = 0
        else:  # find max y size in the row
            distance_center2bottom_ref = transistors[i][0].bbox[0][1]  # Temporal
            distance_center2top_pre_ref = (
                transistors[i - 1][0].bbox[1][1] - ymove
            )  # Temporal // Minus the ymove because this one was already moved
            for k in range(len(transistors[i])):
                distance_center2bottom_temp = transistors[i][k].bbox[0][
                    1
                ]  # distance center to bottom of the transistor that will be moved
                distance_center2top_pre_temp = (
                    transistors[i - 1][k].bbox[1][1] - ymove
                )  # distance center to top of the transistor above the one that will be moved
                if (
                    distance_center2bottom_temp < distance_center2bottom_ref
                ):  # minus because the distance is negative
                    distance_center2bottom_ref = distance_center2bottom_temp
                if distance_center2top_pre_temp > distance_center2top_pre_ref:
                    distance_center2top_pre_ref = distance_center2top_pre_temp

            ymove_temp = (
                abs(distance_center2bottom_ref)
                + abs(distance_center2top_pre_ref)
                + min_separation
            )
            ymove += ymove_temp
            if even and i == middle_transistor:
                # If even need more space in the middle row for the output
                extra_space = pdk.snap_to_2xgrid(
                    evaluate_bbox(via_stack(pdk, "met2", "met3"))[1]
                    + 2 * pdk.get_grule("met2")["min_separation"]
                )
                ymove += extra_space
        for j in range(len(transistors[i])):
            size_transistor = evaluate_bbox(transistors[i][j])
            # Move the transistors in x direction
            if j == 0:
                # first transistor dont move
                xmove = 0
            else:
                pre_last_size = evaluate_bbox(transistors[i][j - 1])
                # rest of transistors
                xmove += (size_transistor[0] + pre_last_size[0]) / 2 + min_separation_x
            transistors[i][j].movex(pdk.snap_to_2xgrid(xmove))
            transistors[i][j].movey(pdk.snap_to_2xgrid(ymove))
            if matriz[i][j] == 0:
                devletter = "D"
            elif matriz[i][j] == 1:
                devletter = "A"
            elif matriz[i][j] == 2:
                devletter = "B"

            prefix = devletter + "i" + str(int(i)) + "_j" + str(int(j)) + ""
            matplace.add_ports(transistors[i][j].get_ports_list(), prefix=prefix)

    matplace = rename_ports_by_orientation(matplace)

    # Define dictionaries to organize ports by type and orientation
    ports_A = {
        "source_W": [],
        "source_E": [],
        "drain_W": [],
        "drain_E": [],
        "gate_W": [],
        "gate_E": [],
    }
    ports_B = {
        "source_W": [],
        "source_E": [],
        "drain_W": [],
        "drain_E": [],
        "gate_W": [],
        "gate_E": [],
    }
    ports_D = {
        "source_W": [],
        "source_E": [],
        "drain_W": [],
        "drain_E": [],
        "gate_W": [],
        "gate_E": [],
    }

    # List of device types and ports to be searched
    busqueda = [
        ("A", "source"),
        ("A", "drain"),
        ("A", "gate"),
        ("B", "source"),
        ("B", "drain"),
        ("B", "gate"),
        ("D", "source"),
        ("D", "drain"),
        ("D", "gate"),
    ]
    # Cycle through every combination of device and port
    for dispositivo, puerto in busqueda:
        for i in range(len(matriz)):  # Iterate over the matrix rows
            # Get all ports in row i with W and E orientation
            encontrados_W = [
                name
                for name in matplace.ports
                if f"{dispositivo}i{i}" in name
                and f"{puerto}_W" in name
                and "row" not in name
            ]
            encontrados_E = [
                name
                for name in matplace.ports
                if f"{dispositivo}i{i}" in name
                and f"{puerto}_E" in name
                and "row" not in name
            ]
            # Assign the corresponding row only if there are found elements
            if dispositivo == "A":
                if encontrados_W:
                    ports_A[f"{puerto}_W"].append(encontrados_W)
                if encontrados_E:
                    ports_A[f"{puerto}_E"].append(encontrados_E)
            elif dispositivo == "B":
                if encontrados_W:
                    ports_B[f"{puerto}_W"].append(encontrados_W)
                if encontrados_E:
                    ports_B[f"{puerto}_E"].append(encontrados_E)
            elif dispositivo == "D":
                if encontrados_W:
                    ports_D[f"{puerto}_W"].append(encontrados_W)
                if encontrados_E:
                    ports_D[f"{puerto}_E"].append(encontrados_E)

    # Component centering
    matplace_centered = Component()
    matplace_ref = matplace_centered << transformed(prec_ref_center(matplace))
    matplace_centered.add_ports(matplace_ref.get_ports_list())
    dims = evaluate_bbox(matplace_centered)
    xmove = pdk.snap_to_2xgrid(dims[0] / 2)
    if pdk == sky130:
        min_separation = pdk.snap_to_2xgrid(
            (
                pdk.get_grule("met3")["min_separation"]
                + pdk.get_grule("met3")["min_width"]
                + pdk.get_grule("via3")["min_separation"]
                + pdk.get_grule("via3")["min_width"]
            )
        )
    elif pdk == gf180:
        min_separation = pdk.snap_to_2xgrid(
            (
                pdk.get_grule("met3")["min_separation"]
                + pdk.get_grule("met3")["min_width"]
                + pdk.get_grule("via3")["min_separation"]
                + evaluate_bbox(via_stack(pdk, "met2", "met3"))[1]
            )
        )

    # Rings
    # Define configurations according to transistor type
    device_config = {
        "nfet": {
            "sdlayer": "p+s/d",
            "well_layer": "pwell",
            "tap_enclosure_rule": "p+s/d",
        },
        "pfet": {
            "sdlayer": "n+s/d",
            "well_layer": "nwell",
            "tap_enclosure_rule": "n+s/d",
            "substrate_tap_layer": "p+s/d",
        },
    }

    # Obtaining the correct configuration
    config = device_config.get(deviceA_and_B)
    # Add tie if necessary
    if with_tie:
        tie_layers = ["met2", "met1"]

        tap_separation = max(
            pdk.get_grule("met2")["min_separation"],
            pdk.get_grule("met1")["min_separation"],
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule(config["tap_enclosure_rule"], "active_tap")[
            "min_enclosure"
        ]

        tap_encloses = (
            2 * (tap_separation + matplace_centered.xmax),
            2 * (tap_separation + matplace_centered.ymax),
        )
        tapring_ref = matplace_centered << create_tapring_onchip(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer=config["sdlayer"],
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
            with_lvt_layer=with_lvt_layer,
        )
        matplace_centered.add_ports(tapring_ref.get_ports_list(), prefix="tie_")
        if with_dummy:
            first_mos_ds = matplace_centered.ports[
                "Di0_j0leftsd_met_array_row0_col0_top_met_W"
            ]
            first_mos_gate = matplace_centered.ports["Di0_j0gate_W"]
            first_mos_ds_R = matplace_centered.ports[
                "Di0_j"
                + str(len(matrizT) - 1)
                + "row0_col"
                + str(fingers1 - 1)
                + "_rightsd_met_array_row0_col0_top_met_E"
            ]
            first_mos_gate_R = matplace_centered.ports[
                "Di0_j" + str(len(matrizT) - 1) + "gate_E"
            ]
            last_mos_ds = matplace_centered.ports[
                "Di" + str(len(matriz) - 1) + "_j0leftsd_met_array_row0_col0_top_met_W"
            ]
            last_mos_gate = matplace_centered.ports[
                "Di" + str(len(matriz) - 1) + "_j0gate_W"
            ]
            last_mos_ds_R = matplace_centered.ports[
                "Di"
                + str(len(matriz) - 1)
                + "_j"
                + str(len(matrizT) - 1)
                + "row0_col"
                + str(fingers1 - 1)
                + "_rightsd_met_array_row0_col0_top_met_E"
            ]
            last_mos_gate_R = matplace_centered.ports[
                "Di" + str(len(matriz) - 1) + "_j" + str(len(matrizT) - 1) + "gate_E"
            ]
            tie_left_W = matplace_centered.ports["tie_W_array_row0_col0_top_met_W"]
            tie_right = matplace_centered.ports["tie_E_array_row0_col0_top_met_E"]
            width_route_dummy = 1 if width1 >= 1 else width1
            for i in range(len(matriz)):
                if i == 0:
                    # First Dummys
                    matplace_centered << straight_route(
                        pdk, first_mos_ds_R, tie_left_W, width=width_route_dummy
                    )
                    matplace_centered << straight_route(
                        pdk, first_mos_ds, tie_right, width=width_route_dummy
                    )
                    matplace_centered << straight_route(
                        pdk, first_mos_gate_R, tie_left_W
                    )
                    matplace_centered << straight_route(pdk, first_mos_gate, tie_right)
                elif i == len(matriz) - 1:
                    # Last Dummys
                    matplace_centered << straight_route(
                        pdk, last_mos_ds_R, tie_left_W, width=width_route_dummy
                    )
                    matplace_centered << straight_route(
                        pdk, last_mos_ds, tie_right, width=width_route_dummy
                    )
                    matplace_centered << straight_route(
                        pdk, last_mos_gate_R, tie_left_W
                    )
                    matplace_centered << straight_route(pdk, last_mos_gate, tie_right)
                else:
                    matplace_centered << straight_route(
                        pdk,
                        matplace_centered.ports[
                            "Di"
                            + str(i)
                            + "_j0row0_col"
                            + str(fingers1 - 1)
                            + "_rightsd_met_array_row0_col0_top_met_E"
                        ],
                        tie_left_W,
                        width=width_route_dummy,
                    )
                    matplace_centered << straight_route(
                        pdk,
                        matplace_centered.ports[
                            "Di"
                            + str(i)
                            + "_j"
                            + str(len(matriz[0]) - 1)
                            + "leftsd_met_array_row0_col0_top_met_W"
                        ],
                        tie_right,
                        width=width_route_dummy,
                    )
                    matplace_centered << straight_route(
                        pdk,
                        matplace_centered.ports["Di" + str(i) + "_j0gate_E"],
                        tie_left_W,
                    )
                    matplace_centered << straight_route(
                        pdk,
                        matplace_centered.ports[
                            "Di" + str(i) + "_j" + str(len(matriz[0]) - 1) + "gate_W"
                        ],
                        tie_right,
                    )

    # Add well
    matplace_centered.add_padding(
        layers=(pdk.get_glayer(config["well_layer"]),),
        default=pdk.get_grule(config["well_layer"], "active_tap")["min_enclosure"],
    )

    # Adding taps on the perimeter
    matplace_centered = add_ports_perimeter(
        matplace_centered, layer=pdk.get_glayer(config["well_layer"]), prefix="well_"
    )
    dims_post_tie = evaluate_bbox(matplace_centered)

    # Add substrate tap if necessary
    if deviceA_and_B == "pfet":
        if with_substrate_tap:
            substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")[
                "min_separation"
            ]
            substrate_tap_encloses = (
                2 * (substrate_tap_separation + matplace_centered.xmax),
                2 * (substrate_tap_separation + matplace_centered.ymax),
            )
            ringtoadd = create_tapring_onchip(
                pdk,
                enclosed_rectangle=substrate_tap_encloses,
                sdlayer=config["substrate_tap_layer"],
                horizontal_glayer="met2",
                vertical_glayer="met1",
                with_lvt_layer=False,
            )
            tapring_ref = matplace_centered << ringtoadd
            matplace_centered.add_ports(
                tapring_ref.get_ports_list(), prefix="substratetap_"
            )

    # Creation of ports and lanes for column routing
    via = via_stack(pdk, "met1", "met2")
    dims = evaluate_bbox(matplace_centered)
    xmove = pdk.snap_to_2xgrid(dims[0] / 2)
    min_separation = pdk.snap_to_2xgrid(
        matplace_centered.ports[ports_A["drain_W"][0][0]].width
        + pdk.get_grule("met3")["min_separation"]
    )
    if enable_B:
        name_vias = [
            ["A_drain_L", -1 * min_separation - xmove],
            ["A_drain_R", 1 * min_separation + xmove],
            ["A_source_L", -2 * min_separation - xmove],
            ["A_source_R", 2 * min_separation + xmove],
            ["A_gate_L", -6 * min_separation - xmove],
            ["A_gate_R", 3 * min_separation + xmove],
            ["B_drain_L", -4 * min_separation - xmove],
            ["B_drain_R", 4 * min_separation + xmove],
            ["B_source_L", -5 * min_separation - xmove],
            ["B_source_R", 5 * min_separation + xmove],
            ["B_gate_L", -3 * min_separation - xmove],
            ["B_gate_R", 6 * min_separation + xmove],
        ]
    else:
        name_vias = [
            ["A_drain_L", -1 * min_separation - xmove],
            ["A_drain_R", 1 * min_separation + xmove],
            ["A_source_L", -2 * min_separation - xmove],
            ["A_source_R", 2 * min_separation + xmove],
            ["A_gate_L", -3 * min_separation - xmove],
            ["A_gate_R", 3 * min_separation + xmove],
        ]

    via_met12 = list()
    via_met23 = list()
    # check if center up and center down transistor are different size
    center_transistor = (len(matriz) // 2, len(matriz) // 2 - 1)
    up_transistors = matriz[center_transistor[0]]
    down_transistors = matriz[center_transistor[1]]
    no_dummys_up = [x for x in up_transistors if x != 0]
    no_dummys_down = [x for x in down_transistors if x != 0]

    if all(x == 1 for x in no_dummys_down) and all(x == 2 for x in no_dummys_up):
        not_middle = True
    elif all(x == 2 for x in no_dummys_down) and all(x == 1 for x in no_dummys_up):
        not_middle = True
    else:
        not_middle = False

    if even and not_middle:
        ypos = (
            devA.ports["source_W"].width * 2 + pdk.get_grule("met2")["min_separation"]
        )
    elif even and not_middle == False:
        ypos = 0
    else:
        center_transistor = len(matriz) // 2
        if with_dummy:
            ypos = (
                matplace_centered.ports[
                    "Di" + str(center_transistor) + "_j0gate_S"
                ].center[1]
                + evaluate_bbox(dummy_single_down)[1] / 2
                + 1 * pdk.get_grule("met2")["min_separation"]
            )
        else:
            if matriz[center_transistor][0] == 1:
                devletter_center = "A"
                ypos = (
                    evaluate_bbox(devA)[1] / 2
                    + 1 * pdk.get_grule("met2")["min_separation"]
                )
            elif matriz[center_transistor][0] == 2:
                devletter_center = "B"
                ypos = (
                    evaluate_bbox(devB)[1] / 2
                    + 3 * pdk.get_grule("met2")["min_separation"]
                )
            ypos += matplace_centered.ports[
                str(devletter_center) + "i" + str(center_transistor) + "_j0gate_S"
            ].center[1]

    for via, pos in name_vias:
        via_met12.append(
            matplace_centered << via_stack(pdk, "met1", "met2", centered=True)
        )
        via_met12[-1].movex(pos)
        via_met12[-1].movey(ypos)
        matplace_centered.add_ports(via_met12[-1].get_ports_list(), prefix=via + "_12_")
        via_met23.append(
            matplace_centered << via_stack(pdk, "met2", "met3", centered=True)
        )
        via_met23[-1].movex(pos)
        via_met23[-1].movey(ypos)
        matplace_centered.add_ports(via_met23[-1].get_ports_list(), prefix=via + "_23_")
    widht_route_vertical = matplace_centered.ports[ports_A["drain_W"][0][0]].width

    for i in range(len(ports_A["drain_E"])):
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_A["drain_W"][i][0]],
            matplace_centered.ports["A_drain_L_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_A["drain_E"][i][0]],
            matplace_centered.ports["A_drain_R_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_A["source_W"][i][0]],
            matplace_centered.ports["A_source_L_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_A["source_E"][i][0]],
            matplace_centered.ports["A_source_R_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_A["gate_W"][i][0]],
            matplace_centered.ports["A_gate_L_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_A["gate_E"][i][0]],
            matplace_centered.ports["A_gate_R_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
    for i in range(len(ports_B["drain_E"])):
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_B["drain_W"][i][0]],
            matplace_centered.ports["B_drain_L_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_B["drain_E"][i][0]],
            matplace_centered.ports["B_drain_R_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_B["source_W"][i][0]],
            matplace_centered.ports["B_source_L_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_B["source_E"][i][0]],
            matplace_centered.ports["B_source_R_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_B["gate_W"][i][0]],
            matplace_centered.ports["B_gate_L_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )
        matplace_centered << L_route(
            pdk,
            matplace_centered.ports[ports_B["gate_E"][i][0]],
            matplace_centered.ports["B_gate_R_12_bottom_met_N"],
            hwidth=widht_route_vertical,
        )

    dims = evaluate_bbox(matplace_centered)
    size_out_ports = evaluate_bbox(via_stack(pdk, "met3", "met4"))
    min_separation = pdk.snap_to_2xgrid(pdk.get_grule("met4")["min_separation"])

    # Gate port
    gateA = matplace_centered << via_stack(pdk, "met3", "met4")
    gateA_bot = matplace_centered << via_stack(pdk, "met2", "met3")
    gateA.movex(pdk.snap_to_2xgrid(-dims[0] / 2 - min_separation))
    gateA_bot.movex(pdk.snap_to_2xgrid(-dims[0] / 2 - min_separation))
    gateA.movey(ypos)
    gateA_bot.movey(ypos)
    matplace_centered.add_ports(gateA_bot.get_ports_list(), prefix="A_gate_bot_")
    matplace_centered.add_ports(gateA.get_ports_list(), prefix="A_gate_")
    if enable_B:
        gateB = matplace_centered << via_stack(pdk, "met3", "met4")
        gateB_bot = matplace_centered << via_stack(pdk, "met2", "met3")
        gateB.movex(pdk.snap_to_2xgrid(dims[0] / 2 + min_separation))
        gateB_bot.movex(pdk.snap_to_2xgrid(dims[0] / 2 + min_separation))
        gateB.movey(ypos)
        gateB_bot.movey(ypos)
        matplace_centered.add_ports(gateB_bot.get_ports_list(), prefix="B_gate_bot_")
        matplace_centered.add_ports(gateB.get_ports_list(), prefix="B_gate_")

    # Source port
    sourceA = matplace_centered << via_stack(pdk, "met3", "met4")
    sourceA.movey(pdk.snap_to_2xgrid(-dims[1] / 2 - size_out_ports[0] / 2)).movex(
        pdk.snap_to_2xgrid(-min_separation - size_out_ports[0] / 2)
    )
    matplace_centered.add_ports(sourceA.get_ports_list(), prefix="A_source_")
    if enable_B:
        sourceB = matplace_centered << via_stack(pdk, "met3", "met4")
        sourceB.movey(
            pdk.snap_to_2xgrid(-dims[1] / 2 - 1.5 * size_out_ports[0] - min_separation)
        ).movex(pdk.snap_to_2xgrid(min_separation + size_out_ports[0] / 2))
        matplace_centered.add_ports(sourceB.get_ports_list(), prefix="B_source_")

    # Drain port
    drainA = matplace_centered << via_stack(pdk, "met3", "met4")
    if with_substrate_tap and deviceA_and_B == "pfet":
        drainA.movey(pdk.snap_to_2xgrid(dims[1] / 2 + size_out_ports[0] / 2)).movex(
            pdk.snap_to_2xgrid(-min_separation - size_out_ports[0] / 2)
        )
    elif with_substrate_tap == False or deviceA_and_B == "nfet":
        drainA.movey(
            pdk.snap_to_2xgrid(
                dims[1] / 2
                + size_out_ports[0] / 2
                + pdk.get_grule("met5")["min_separation"]
                + pdk.get_grule("active_tap", "mcon")["min_enclosure"]
            )
        ).movex(pdk.snap_to_2xgrid(-min_separation - size_out_ports[0] / 2))
    matplace_centered.add_ports(drainA.get_ports_list(), prefix="A_drain_")
    if enable_B:
        drainB = matplace_centered << via_stack(pdk, "met3", "met4")
        if with_substrate_tap and deviceA_and_B == "pfet":
            drainB.movey(
                pdk.snap_to_2xgrid(
                    dims[1] / 2 + 1.5 * size_out_ports[0] + min_separation
                )
            ).movex(pdk.snap_to_2xgrid(min_separation + size_out_ports[0] / 2))
        elif with_substrate_tap == False or deviceA_and_B == "nfet":
            drainB.movey(
                pdk.snap_to_2xgrid(
                    dims[1] / 2
                    + 1.5 * size_out_ports[0]
                    + min_separation
                    + pdk.get_grule("met5")["min_separation"]
                    + pdk.get_grule("active_tap", "mcon")["min_enclosure"]
                )
            ).movex(pdk.snap_to_2xgrid(min_separation + size_out_ports[0] / 2))
        matplace_centered.add_ports(drainB.get_ports_list(), prefix="B_drain_")

    matplace_centered = rename_ports_by_orientation(matplace_centered)
    # Gates routes
    matplace_centered << straight_route(
        pdk,
        matplace_centered.ports["A_gate_L_23_bottom_met_W"],
        matplace_centered.ports["A_gate_bot_bottom_met_E"],
    )
    if enable_B:
        matplace_centered << straight_route(
            pdk,
            matplace_centered.ports["B_gate_R_23_bottom_met_E"],
            matplace_centered.ports["B_gate_bot_bottom_met_W"],
        )
    # Source routes
    L1 = matplace_centered << L_route(
        pdk,
        matplace_centered.ports["A_source_L_23_top_met_S"],
        matplace_centered.ports["A_source_top_met_W"],
        hwidth=widht_route_vertical,
    )
    L2 = matplace_centered << L_route(
        pdk,
        matplace_centered.ports["A_source_R_23_top_met_S"],
        matplace_centered.ports["A_source_top_met_E"],
        hwidth=widht_route_vertical,
    )
    if enable_B:
        L3 = matplace_centered << L_route(
            pdk,
            matplace_centered.ports["B_source_L_23_top_met_S"],
            matplace_centered.ports["B_source_top_met_W"],
            hwidth=widht_route_vertical,
        )
        L4 = matplace_centered << L_route(
            pdk,
            matplace_centered.ports["B_source_R_23_top_met_S"],
            matplace_centered.ports["B_source_top_met_E"],
            hwidth=widht_route_vertical,
        )
    # Drain routes
    L5 = matplace_centered << L_route(
        pdk,
        matplace_centered.ports["A_drain_L_23_top_met_N"],
        matplace_centered.ports["A_drain_top_met_W"],
        hwidth=widht_route_vertical,
    )
    L6 = matplace_centered << L_route(
        pdk,
        matplace_centered.ports["A_drain_R_23_top_met_N"],
        matplace_centered.ports["A_drain_top_met_E"],
        hwidth=widht_route_vertical,
    )
    if enable_B:
        L7 = matplace_centered << L_route(
            pdk,
            matplace_centered.ports["B_drain_L_23_top_met_N"],
            matplace_centered.ports["B_drain_top_met_W"],
            hwidth=widht_route_vertical,
        )
        L8 = matplace_centered << L_route(
            pdk,
            matplace_centered.ports["B_drain_R_23_top_met_N"],
            matplace_centered.ports["B_drain_top_met_E"],
            hwidth=widht_route_vertical,
        )

    component = Component()
    component << matplace_centered

    # Get all ports of the original component
    all_ports = matplace_centered.ports
    if enable_B:
        filtros = [
            "A_source_",
            "B_source_",
            "A_drain_",
            "B_drain_",
            "A_gate_",
            "B_gate_",
        ]
    else:
        filtros = ["A_source_", "A_gate_", "A_drain_"]
    # Filter only the ones you need (by name, coordinates, etc.)
    selected_ports = dict()
    for filtro in filtros:
        buscar_w = filtro + "top_met_W"
        buscar_e = filtro + "top_met_E"
        buscar_n = filtro + "bottom_met_N"
        buscar_s = filtro + "bottom_met_S"
        selected_ports = {
            name: port
            for name, port in all_ports.items()
            if buscar_w in name
            or buscar_e in name
            or buscar_n in name
            or buscar_s in name
        }  # Ejemplo: solo los que tienen 'in' en su nombre
        for name, port in selected_ports.items():
            new_name = filtro + name[-1]  # Add prefix
            component.add_port(
                new_name,
                port.center,
                port.width,
                port.orientation,
                layer=port.layer,
                port_type="electrical",
            )
    if with_tie:
        buscar = [
            "tie_N_top_met_W",
            "tie_N_top_met_N",
            "tie_N_top_met_E",
            "tie_N_top_met_S",
            "tie_S_top_met_W",
            "tie_S_top_met_N",
            "tie_S_top_met_E",
            "tie_S_top_met_S",
            "tie_E_top_met_W",
            "tie_E_top_met_N",
            "tie_E_top_met_E",
            "tie_E_top_met_S",
            "tie_W_top_met_W",
            "tie_W_top_met_N",
            "tie_W_top_met_E",
            "tie_W_top_met_S",
        ]
        selected_ports = dict()
        for busqueda in buscar:
            new_port = {
                name: port
                for name, port in all_ports.items()
                if busqueda in name and "row" not in name
            }
            selected_ports.update(new_port)
        for name, port in selected_ports.items():
            posicion = {"N": "up", "S": "down", "E": "right", "W": "left"}
            new_name = "bulk_" + posicion[name[4]] + "_" + name[-1]
            component.add_port(
                new_name,
                port.center,
                port.width,
                port.orientation,
                layer=port.layer,
                port_type="electrical",
            )
    if full_output_size:
        if pdk_sky130:
            ports_list = [
                L1.ports["bottom_layer_W"],
                L1.ports["bottom_layer_N"],
                L2.ports["bottom_layer_E"],
                L2.ports["bottom_layer_S"],
                L5.ports["bottom_layer_W"],
                L5.ports["bottom_layer_N"],
                L6.ports["bottom_layer_E"],
                L6.ports["bottom_layer_S"],
            ]
            names = ["A_source_T_", "A_drain_T_"]
            if enable_B:
                ports_list += [
                    L3.ports["bottom_layer_W"],
                    L3.ports["bottom_layer_N"],
                    L4.ports["bottom_layer_E"],
                    L4.ports["bottom_layer_S"],
                    L7.ports["bottom_layer_W"],
                    L7.ports["bottom_layer_N"],
                    L8.ports["bottom_layer_E"],
                    L8.ports["bottom_layer_S"],
                ]
                names += ["B_source_T_", "B_drain_T_"]
        elif pdk_gf180:
            ports_list = [
                L1.ports["bottom_lay_W"],
                L1.ports["bottom_lay_N"],
                L2.ports["bottom_lay_E"],
                L2.ports["bottom_lay_S"],
                L5.ports["bottom_lay_W"],
                L5.ports["bottom_lay_N"],
                L6.ports["bottom_lay_E"],
                L6.ports["bottom_lay_S"],
            ]
            names = ["A_source_T_", "A_drain_T_"]
            if enable_B:
                ports_list += [
                    L3.ports["bottom_lay_W"],
                    L3.ports["bottom_lay_N"],
                    L4.ports["bottom_lay_E"],
                    L4.ports["bottom_lay_S"],
                    L7.ports["bottom_lay_W"],
                    L7.ports["bottom_lay_N"],
                    L8.ports["bottom_lay_E"],
                    L8.ports["bottom_lay_S"],
                ]
                names += ["B_source_T_", "B_drain_T_"]

        for i in range(len(names)):
            component.add_port(
                names[i] + "W",
                ports_list[4 * i].center,
                ports_list[4 * i].width,
                ports_list[4 * i].orientation,
                layer=ports_list[4 * i].layer,
                port_type="electrical",
            )
            component.add_port(
                names[i] + "N",
                ports_list[4 * i + 1].center,
                ports_list[4 * i + 1].width,
                ports_list[4 * i + 1].orientation,
                layer=ports_list[4 * i + 1].layer,
                port_type="electrical",
            )
            component.add_port(
                names[i] + "E",
                ports_list[4 * i + 2].center,
                ports_list[4 * i + 2].width,
                ports_list[4 * i + 2].orientation,
                layer=ports_list[4 * i + 2].layer,
                port_type="electrical",
            )
            component.add_port(
                names[i] + "S",
                ports_list[4 * i + 3].center,
                ports_list[4 * i + 3].width,
                ports_list[4 * i + 3].orientation,
                layer=ports_list[4 * i + 3].layer,
                port_type="electrical",
            )

    return component.flatten()


def interdigitado_placement_Onchip(
    pdk: MappedPDK,
    deviceA_and_B: Literal["nfet", "pfet"],
    output: Literal["metal", "via"] = "metal",
    output_separation: tuple[Optional[float], Optional[float]] = (0, 0),
    width: float = 1,
    length: float = 2,
    fingers: int = 1,
    with_dummy: bool = False,
    with_lvt_layer: bool = True,
    with_tie: bool = True,
    with_substrate_tap: bool = False,
    gate_common: bool = True,
    routed: bool = False,
    common_route: Optional[Union[bool, tuple[Optional[bool], Optional[bool]]]] = (
        False,
        False,
    ),
    array: list = [[1, 2, 3]],
    **kwargs,
) -> Component:
    interdigitado = Component()
    array = copy.deepcopy(array)
    max_output = max(array[0])
    # Add dummys to array
    if with_dummy:
        column = len(array[0])

        horizontal = [0] * (column + 2)
        array_column = [[0] + row + [0] for row in array]

        array = [horizontal] + array_column + [horizontal]
    arrayT = [list(fila) for fila in zip(*array)]
    # Multiplier's arguments
    kwargs["sdlayer"] = "n+s/d" if deviceA_and_B == "nfet" else "p+s/d"
    kwargs["pdk"] = pdk
    kwargs["dummy"] = (False, False)
    kwargs["routing"] = False
    reference = multiplier(
        width=width, length=length, fingers=fingers, gate_down=True, **kwargs
    )
    gate_extension_ref = abs(
        pdk.get_grule("met2")["min_separation"] + reference.ports["gate_W"].width
    )
    if gate_common == False:
        reference = list()
        for i in range(max_output):
            gate_extension = gate_extension_ref * i
            kwargs["gate_route_extension"] = pdk.snap_to_2xgrid(gate_extension)
            reference.append(
                multiplier(
                    width=width,
                    length=length,
                    fingers=fingers,
                    gate_down=True,
                    **kwargs,
                )
            )

    # dummy reference
    if with_dummy:
        kwargs["gate_route_extension"] = 0
        dummy_single_up = multiplier(
            width=width, length=length, fingers=1, gate_up=True, **kwargs
        )
        dummy_single_down = multiplier(
            width=width, length=length, fingers=1, gate_down=True, **kwargs
        )
        dummy_up = multiplier(
            width=width, length=length, fingers=fingers, gate_up=True, **kwargs
        )
        dummy_down = multiplier(
            width=width, length=length, fingers=fingers, gate_down=True, **kwargs
        )
    # min separation
    if pdk == sky130:
        min_separation = pdk.get_grule("poly")["min_separation"]
    elif pdk == gf180:
        min_separation = pdk.get_grule("met2")["min_separation"]
    # Create the array of transistors
    transistors = list()
    for i in range(len(array)):
        transistors_in_row = list()
        for j in range(len(array[i])):
            if i == 0 or i == len(array) - 1:  # first and last row
                if j == 0 or j == len(array[i]) - 1:  # first and last column
                    # corner transistors
                    if array[i][j] == 0 and i == 0:
                        # small dummy
                        transistors_in_row.append(interdigitado << dummy_single_down)
                    elif array[i][j] == 0 and i == len(array) - 1:
                        # small dummy
                        transistors_in_row.append(interdigitado << dummy_single_up)
                    else:
                        if gate_common:
                            transistors_in_row.append(interdigitado << reference)
                        else:
                            transistors_in_row.append(
                                interdigitado << reference[array[i][j] - 1]
                            )
                elif i == 0:  # first row
                    # first row transistors
                    if array[i][j] == 0:
                        # dummy
                        transistors_in_row.append(interdigitado << dummy_down)
                    else:
                        if gate_common:
                            transistors_in_row.append(interdigitado << reference)
                        else:
                            transistors_in_row.append(
                                interdigitado << reference[array[i][j] - 1]
                            )
                else:  # last row
                    # last row transistors
                    if array[i][j] == 0:
                        # dummy
                        transistors_in_row.append(interdigitado << dummy_up)
                    else:
                        if gate_common:
                            transistors_in_row.append(interdigitado << reference)
                        else:
                            transistors_in_row.append(
                                interdigitado << reference[array[i][j] - 1]
                            )
            else:  # middle rows
                if array[i][j] == 0:
                    # small dummy
                    transistors_in_row.append(interdigitado << dummy_single_up)
                else:
                    if gate_common:
                        transistors_in_row.append(interdigitado << reference)
                    else:
                        transistors_in_row.append(
                            interdigitado << reference[array[i][j] - 1]
                        )
        # Add the transistors in the row
        transistors.append(transistors_in_row)
    min_separation_x = pdk.get_grule("p+s/d")["min_separation"] + 0.01
    # [0][1] = distance center to bottom
    # [1][1] = distance center to top
    # Move the transistors
    for i in range(len(transistors)):
        # Move the transistors in y direction
        if i == 0:
            # first row dont move
            ymove = 0
        else:  # find max y size in the row
            distance_center2bottom_ref = transistors[i][0].bbox[0][1]  # Temporal
            distance_center2top_pre_ref = (
                transistors[i - 1][0].bbox[1][1] - ymove
            )  # Temporal // Minus the ymove because this one was already moved
            ymove_temp = (
                abs(distance_center2bottom_ref)
                + abs(distance_center2top_pre_ref)
                + min_separation
            )
            for k in range(len(transistors[i])):
                distance_center2bottom_temp = transistors[i][k].bbox[0][
                    1
                ]  # distance center to bottom of the transistor that will be moved
                distance_center2top_pre_temp = (
                    transistors[i - 1][k].bbox[1][1] - ymove
                )  # distance center to top of the transistor above the one that will be moved
                ymove_temp_2 = (
                    abs(distance_center2bottom_temp)
                    + abs(distance_center2top_pre_temp)
                    + min_separation
                )
                if ymove_temp_2 > ymove_temp:
                    ymove_temp = ymove_temp_2
            ymove += (
                ymove_temp
                if i == 1 or i == len(transistors) - 1
                else ymove_temp + 3 * evaluate_bbox(via_stack(pdk, "met1", "met2"))[1]
            )
        for j in range(len(transistors[i])):
            size_transistor = evaluate_bbox(transistors[i][j])
            # Move the transistors in x direction
            if j == 0:
                # first transistor dont move
                xmove = 0
            else:
                pre_last_size = evaluate_bbox(transistors[i][j - 1])
                # rest of transistors
                xmove += (size_transistor[0] + pre_last_size[0]) / 2 + min_separation_x
            transistors[i][j].movex(pdk.snap_to_2xgrid(xmove))
            transistors[i][j].movey(pdk.snap_to_2xgrid(ymove))
            interdigitado.add_ports(
                transistors[i][j].get_ports_list(),
                prefix=str(i) + str(j) + "_" + str(array[i][j]) + "_",
            )

    # Center the component
    interdigitado = center_component_with_ports(interdigitado)
    ##RINGS
    # Define configurations according to transistor type
    device_config = {
        "nfet": {
            "sdlayer": "p+s/d",
            "well_layer": "pwell",
            "tap_enclosure_rule": "p+s/d",
        },
        "pfet": {
            "sdlayer": "n+s/d",
            "well_layer": "nwell",
            "tap_enclosure_rule": "n+s/d",
            "substrate_tap_layer": "p+s/d",
        },
    }

    # Obtaining the correct configuration
    config = device_config.get(deviceA_and_B)
    # Add tie if necessary
    if with_tie:
        tie_layers = ["met2", "met1"]

        tap_separation = max(
            pdk.get_grule("met2")["min_separation"],
            pdk.get_grule("met1")["min_separation"],
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule(config["tap_enclosure_rule"], "active_tap")[
            "min_enclosure"
        ]

        tap_encloses = (
            2 * (tap_separation + interdigitado.xmax),
            2 * (tap_separation + interdigitado.ymax),
        )
        tapring_ref = interdigitado << create_tapring_onchip(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer=config["sdlayer"],
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
            with_lvt_layer=with_lvt_layer,
        )
        interdigitado.add_ports(tapring_ref.get_ports_list(), prefix="tie_")
        if with_dummy:
            first_mos_ds = interdigitado.ports[
                "00_0_leftsd_met_array_row0_col0_top_met_W"
            ]
            first_mos_gate = interdigitado.ports["00_0_gate_W"]
            first_mos_ds_R = interdigitado.ports[
                "0"
                + str(len(arrayT) - 1)
                + "_0_"
                + "row0_col0_rightsd_met_array_row0_col0_top_met_E"
            ]
            first_mos_gate_R = interdigitado.ports[
                "0" + str(len(arrayT) - 1) + "_0_gate_E"
            ]
            last_mos_ds = interdigitado.ports[
                str(len(array) - 1) + "0_0_leftsd_met_array_row0_col0_top_met_W"
            ]
            last_mos_gate = interdigitado.ports[str(len(array) - 1) + "0_0_gate_W"]
            last_mos_ds_R = interdigitado.ports[
                str(len(array) - 1)
                + str(len(arrayT) - 1)
                + "_0_row0_col0_rightsd_met_array_row0_col0_top_met_E"
            ]
            last_mos_gate_R = interdigitado.ports[
                str(len(array) - 1) + str(len(arrayT) - 1) + "_0_gate_E"
            ]
            tie_left_W = interdigitado.ports["tie_W_array_row0_col0_top_met_W"]
            tie_right = interdigitado.ports["tie_E_array_row0_col0_top_met_E"]
            width_route_dummy = 1 if width >= 1 else width
            for i in range(len(array)):
                if i == 0:
                    # First Dummys
                    interdigitado << straight_route(
                        pdk, first_mos_ds_R, tie_left_W, width=width_route_dummy
                    )
                    interdigitado << straight_route(
                        pdk, first_mos_ds, tie_right, width=width_route_dummy
                    )
                    interdigitado << straight_route(pdk, first_mos_gate_R, tie_left_W)
                    interdigitado << straight_route(pdk, first_mos_gate, tie_right)
                elif i == len(array) - 1:
                    # Last Dummys
                    interdigitado << straight_route(
                        pdk, last_mos_ds_R, tie_left_W, width=width_route_dummy
                    )
                    interdigitado << straight_route(
                        pdk, last_mos_ds, tie_right, width=width_route_dummy
                    )
                    interdigitado << straight_route(pdk, last_mos_gate_R, tie_left_W)
                    interdigitado << straight_route(pdk, last_mos_gate, tie_right)
                else:
                    interdigitado << straight_route(
                        pdk,
                        interdigitado.ports[
                            str(i)
                            + "0_0_row0_col0_rightsd_met_array_row0_col0_top_met_E"
                        ],
                        tie_left_W,
                        width=width_route_dummy,
                    )
                    interdigitado << straight_route(
                        pdk,
                        interdigitado.ports[
                            str(i)
                            + str(len(array[0]) - 1)
                            + "_0_leftsd_met_array_row0_col0_top_met_W"
                        ],
                        tie_right,
                        width=width_route_dummy,
                    )
                    interdigitado << straight_route(
                        pdk, interdigitado.ports[str(i) + "0_0_gate_E"], tie_left_W
                    )
                    interdigitado << straight_route(
                        pdk,
                        interdigitado.ports[
                            str(i) + str(len(array[0]) - 1) + "_0_gate_W"
                        ],
                        tie_right,
                    )

    # Add well
    interdigitado.add_padding(
        layers=(pdk.get_glayer(config["well_layer"]),),
        default=pdk.get_grule(config["well_layer"], "active_tap")["min_enclosure"],
    )

    # Adding taps on the perimeter
    interdigitado = add_ports_perimeter(
        interdigitado, layer=pdk.get_glayer(config["well_layer"]), prefix="well_"
    )
    dims_post_tie = evaluate_bbox(interdigitado)

    # Add substrate tap if necessary
    if deviceA_and_B == "pfet":
        if with_substrate_tap:
            substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")[
                "min_separation"
            ]
            substrate_tap_encloses = (
                2 * (substrate_tap_separation + interdigitado.xmax),
                2 * (substrate_tap_separation + interdigitado.ymax),
            )
            ringtoadd = create_tapring_onchip(
                pdk,
                enclosed_rectangle=substrate_tap_encloses,
                sdlayer=config["substrate_tap_layer"],
                horizontal_glayer="met2",
                vertical_glayer="met1",
                with_lvt_layer=False,
            )
            tapring_ref = interdigitado << ringtoadd
            interdigitado.add_ports(
                tapring_ref.get_ports_list(), prefix="substratetap_"
            )
    # Output port
    T_not_dummy = 0
    size_interdigitado = evaluate_bbox(interdigitado)
    min_separation_met3 = pdk.get_grule("met3")["min_separation"]
    size_transistor = (
        evaluate_bbox(reference) if gate_common else evaluate_bbox(reference[0])
    )

    for i in range(len(array)):
        for j in range(len(array[i])):
            if array[i][j] == 0:
                continue
            else:
                T_not_dummy += 1
                port_reference_top = interdigitado.ports[
                    str(i) + str(j) + "_" + str(array[i][j]) + "_leftsd_top_met_N"
                ]
                port_reference_bottom = interdigitado.ports[
                    str(i) + str(j) + "_" + str(array[i][j]) + "_leftsd_top_met_S"
                ]
                port_referenceg_left = (
                    interdigitado.ports["11_" + str(array[1][1]) + "_gate_W"]
                    if with_dummy
                    else interdigitado.ports["00_" + str(array[0][0]) + "_gate_W"]
                )
                port_referenceg_right = interdigitado.ports[
                    str(i) + str(j) + "_" + str(array[i][j]) + "_gate_E"
                ]
                # port_reference_top.width = port_reference_bottom.width
                rect = rectangle(
                    (port_reference_top.width, port_reference_bottom.width),
                    layer=pdk.get_glayer("met3"),
                )
                via = via_stack(pdk, "met2", "met3")
                output_port = rect if output == "metal" else via
                rectg = rectangle(
                    (port_referenceg_left.width, port_referenceg_right.width),
                    layer=pdk.get_glayer("met2"),
                )
                size_rect = evaluate_bbox(rect)
                size_rectg = evaluate_bbox(rectg)
                size_via = evaluate_bbox(via)
                size_output = size_rect if output == "metal" else size_via
                salidas_row = list()
                drain = 0
                source = 0
                for k in range(fingers + 1):
                    salidas_row.append(interdigitado << output_port)
                    reference = (
                        port_reference_top if k % 2 == 0 else port_reference_bottom
                    )
                    separation = (
                        min_separation_met3 + size_output[1] + output_separation[0]
                        if k % 2 == 0
                        else min_separation_met3 + size_output[1] + output_separation[1]
                    )
                    if gate_common:
                        distance_out_ring = (
                            size_interdigitado[1] / 2 - size_transistor[1] / 2
                            if k % 2 == 0
                            else size_interdigitado[1] / 2
                            - size_transistor[1] / 2
                            + gate_extension_ref
                        )
                    else:
                        distance_out_ring = (
                            size_interdigitado[1] / 2 - size_transistor[1] / 2
                            if k % 2 == 0
                            else size_interdigitado[1] / 2
                            - size_transistor[1] / 2
                            + gate_extension_ref * max_output
                        )
                    ymove = (
                        distance_out_ring + separation * (array[i][j])
                        if k % 2 == 0
                        else -1 * (distance_out_ring + separation * (array[i][j]))
                    )
                    align_comp_to_port(salidas_row[-1], reference)
                    if common_route[0] and k % 2 == 0:
                        ymove -= separation * (array[i][j] - 1)
                    elif common_route[1] and k % 2 == 1:
                        ymove += separation * (array[i][j] - 1)
                    salidas_row[-1].movey(pdk.snap_to_2xgrid(ymove))
                    output_port_name = "e2" if output == "metal" else "top_met_S"
                    # print(salidas_row[-1].get_ports_list())
                    interdigitado << straight_route(
                        pdk,
                        salidas_row[-1].ports[output_port_name],
                        reference,
                        glayer1="met3",
                        glayer2="met2",
                    )
                    prefix = (
                        "drain_"
                        + str(j)
                        + "_"
                        + str(array[i][j])
                        + "_"
                        + str(drain)
                        + "_"
                        if k % 2 == 0
                        else "source_"
                        + str(j)
                        + "_"
                        + str(array[i][j])
                        + "_"
                        + str(source)
                        + "_"
                    )
                    interdigitado.add_ports(
                        salidas_row[-1].get_ports_list(), prefix=prefix
                    )
                    if k == fingers:
                        break
                    drain += 1 if k % 2 == 0 else 0
                    source += 1 if k % 2 == 1 else 0
                    port_reference_top = interdigitado.ports[
                        str(i)
                        + str(j)
                        + "_"
                        + str(array[i][j])
                        + "_row0_col"
                        + str(k)
                        + "_rightsd_top_met_N"
                    ]
                    port_reference_bottom = interdigitado.ports[
                        str(i)
                        + str(j)
                        + "_"
                        + str(array[i][j])
                        + "_row0_col"
                        + str(k)
                        + "_rightsd_top_met_S"
                    ]
    if gate_common:
        salidas_gate = list()
        for i in range(2):
            salidas_gate.append(interdigitado << output_port)
            referenceg = port_referenceg_left if i == 0 else port_referenceg_right
            align_comp_to_port(salidas_gate[-1], referenceg)
            separationg = min_separation_met3 + size_rectg[0]
            if with_dummy:
                distance_out_ring = (
                    size_interdigitado[0] / 2
                    - ((len(array[0])) / 2 - 1) * size_transistor[0]
                )
            else:
                distance_out_ring = 2 * separationg
            xmove = (
                -distance_out_ring - separationg
                if i == 0
                else distance_out_ring + separationg
            )
            salidas_gate[-1].movex(pdk.snap_to_2xgrid(xmove))
            prefix = "gate1_" if i == 0 else "gate2_"
            interdigitado.add_ports(salidas_gate[-1].get_ports_list(), prefix=prefix)
        interdigitado = rename_ports_by_orientation(interdigitado)
        ports_gate = (
            ["gate2_E", "gate1_W"]
            if output == "metal"
            else ["gate2_bottom_met_E", "gate1_bottom_met_W"]
        )
        interdigitado << straight_route(
            pdk,
            interdigitado.ports[ports_gate[0]],
            interdigitado.ports[ports_gate[1]],
            glayer1="met2",
            glayer2="met2",
        )

    # Save ports
    component = Component()
    component << interdigitado
    all_ports = interdigitado.ports

    ports = list()

    if with_tie:
        buscar = [
            "tie_N_top_met_W",
            "tie_N_top_met_N",
            "tie_N_top_met_E",
            "tie_N_top_met_S",
            "tie_S_top_met_W",
            "tie_S_top_met_N",
            "tie_S_top_met_E",
            "tie_S_top_met_S",
            "tie_E_top_met_W",
            "tie_E_top_met_N",
            "tie_E_top_met_E",
            "tie_E_top_met_S",
            "tie_W_top_met_W",
            "tie_W_top_met_N",
            "tie_W_top_met_E",
            "tie_W_top_met_S",
        ]
        selected_ports = dict()
        for busqueda in buscar:
            new_port = {
                name: port
                for name, port in all_ports.items()
                if busqueda in name and "row" not in name
            }
            selected_ports.update(new_port)
        for name, port in selected_ports.items():
            posicion = {"N": "up", "S": "down", "E": "right", "W": "left"}
            new_name = "bulk_" + posicion[name[4]] + "_" + name[-1]
            component.add_port(
                new_name,
                port.center,
                port.width,
                port.orientation,
                layer=port.layer,
                port_type="electrical",
            )

    ports = list()
    name = list()
    for i in range(len(array)):
        for j in range(len(array[i])):
            if array[i][j] == 0:
                continue
            else:
                drain = 0
                source = 0
                for k in range(fingers + 1):
                    if k % 2 == 0:
                        if output == "metal":
                            ports.append(
                                "drain_"
                                + str(j)
                                + "_"
                                + str(array[i][j])
                                + "_"
                                + str(drain)
                                + "_"
                            )
                            name.append(
                                "drain_"
                                + str(j)
                                + "_"
                                + str(array[i][j])
                                + "_"
                                + str(drain)
                                + "_"
                            )
                        elif output == "via":
                            ports.append(
                                "drain_"
                                + str(j)
                                + "_"
                                + str(array[i][j])
                                + "_"
                                + str(drain)
                                + "_top_met_"
                            )
                            name.append(
                                "drain_"
                                + str(j)
                                + "_"
                                + str(array[i][j])
                                + "_"
                                + str(drain)
                                + "_"
                            )
                        drain += 1
                    else:
                        if output == "metal":
                            ports.append(
                                "source_"
                                + str(j)
                                + "_"
                                + str(array[i][j])
                                + "_"
                                + str(source)
                                + "_"
                            )
                            name.append(
                                "source_"
                                + str(j)
                                + "_"
                                + str(array[i][j])
                                + "_"
                                + str(source)
                                + "_"
                            )
                        elif output == "via":
                            ports.append(
                                "source_"
                                + str(j)
                                + "_"
                                + str(array[i][j])
                                + "_"
                                + str(source)
                                + "_top_met_"
                            )
                            name.append(
                                "source_"
                                + str(j)
                                + "_"
                                + str(array[i][j])
                                + "_"
                                + str(source)
                                + "_"
                            )
                        source += 1
    if gate_common:
        gate_names = (
            ["gate1_", "gate2_"]
            if output == "metal"
            else ["gate1_top_met_", "gate2_top_met_"]
        )
        ports.append(gate_names[0])
        ports.append(gate_names[1])
        name.append("gate1_")
        name.append("gate2_")
    else:
        all_ports = interdigitado.ports
        selected_ports = {
            name: port
            for name, port in all_ports.items()
            if "gate" in name and "row" not in name and "_0_" not in name
        }
        for name_original, port in selected_ports.items():
            new_name = name_original[1:]
            component.add_port(
                new_name,
                port.center,
                port.width,
                port.orientation,
                layer=port.layer,
                port_type="electrical",
            )

        # ports.append
    # Add ports to component
    for i in range(len(ports)):
        filtrar_puertos(interdigitado, component, ports[i], name[i])
    # port name format metal output
    # source/drain + position + type transistor + output number(if there are more than one finger)
    # port name format via output
    # source/drain + position + type transistor + output number(if there are more than one finger) + top_met_
    # port name format common gate
    # gate1_ left gate_2 right
    # port name format not common gate
    # postion + type transistor + gate + direction
    # center component
    # component = center_component_with_ports(component)
    return component  # return interdigitado


def interdigitado_cascode_placement_Onchip(
    pdk: MappedPDK,
    deviceA_and_B: Literal["nfet", "pfet"],
    output: Literal["metal", "via"] = "metal",
    output_separation: float = 0,
    width: float = 1,
    length: float = 2,
    fingers: int = 1,
    with_dummy: bool = False,
    with_lvt_layer: bool = True,
    with_tie: bool = True,
    with_substrate_tap: bool = False,
    common_route: Optional[Union[bool, tuple[Optional[bool], Optional[bool]]]] = (
        False,
        False,
    ),
    array: list = [[1, 2, 3]],
    **kwargs,
) -> Component:
    interdigitado = Component()
    max_array = max(array[0])
    array = copy.deepcopy(array)
    if output != "metal" and output != "via":
        raise ValueError("Output must be metal or via")
    # Duplicate the array
    array = array * 2
    # Add dummys to array
    if with_dummy:
        column = len(array[0])

        horizontal = [0] * (column + 2)
        array_column = [[0] + row + [0] for row in array]

        array = [horizontal] + array_column + [horizontal]
    arrayT = [list(fila) for fila in zip(*array)]
    # Multiplier's arguments
    kwargs["sdlayer"] = "n+s/d" if deviceA_and_B == "nfet" else "p+s/d"
    kwargs["pdk"] = pdk
    kwargs["dummy"] = (False, False)
    kwargs["routing"] = False
    reference = multiplier(
        width=width, length=length, fingers=fingers, gate_down=True, **kwargs
    )
    # dummy reference
    if with_dummy:
        dummy_single_up = multiplier(
            width=width, length=length, fingers=1, gate_up=True, **kwargs
        )
        dummy_single_down = multiplier(
            width=width, length=length, fingers=1, gate_down=True, **kwargs
        )
        dummy_up = multiplier(
            width=width, length=length, fingers=fingers, gate_up=True, **kwargs
        )
        dummy_down = multiplier(
            width=width, length=length, fingers=fingers, gate_down=True, **kwargs
        )
    # min separation
    if pdk == sky130:
        min_separation = pdk.get_grule("poly")["min_separation"]
    elif pdk == gf180:
        min_separation = pdk.get_grule("met2")["min_separation"]
    # Create the array of transistors
    transistors = list()
    for i in range(len(array)):
        transistors_in_row = list()
        for j in range(len(array[i])):
            if i == 0 or i == len(array) - 1:  # first and last row
                if j == 0 or j == len(array[i]) - 1:  # first and last column
                    # corner transistors
                    if array[i][j] == 0 and i == 0:
                        # small dummy
                        transistors_in_row.append(interdigitado << dummy_single_down)
                    elif array[i][j] == 0 and i == len(array) - 1:
                        # small dummy
                        transistors_in_row.append(interdigitado << dummy_single_up)
                    else:
                        transistors_in_row.append(interdigitado << reference)
                elif i == 0:  # first row
                    # first row transistors
                    if array[i][j] == 0:
                        # dummy
                        transistors_in_row.append(interdigitado << dummy_down)
                    else:
                        transistors_in_row.append(interdigitado << reference)
                else:  # last row
                    # last row transistors
                    if array[i][j] == 0:
                        # dummy
                        transistors_in_row.append(interdigitado << dummy_up)
                    else:
                        transistors_in_row.append(interdigitado << reference)
            else:  # middle rows
                if array[i][j] == 0:
                    # small dummy
                    transistors_in_row.append(interdigitado << dummy_single_up)
                else:
                    transistors_in_row.append(interdigitado << reference)
        # Add the transistors in the row
        transistors.append(transistors_in_row)
    min_separation_x = pdk.get_grule("p+s/d")["min_separation"] + 0.01
    # [0][1] = distance center to bottom
    # [1][1] = distance center to top
    # Move the transistors
    for i in range(len(transistors)):
        # Move the transistors in y direction
        if i == 0:
            # first row dont move
            ymove = 0
        else:  # find max y size in the row
            distance_center2bottom_ref = transistors[i][0].bbox[0][1]  # Temporal
            distance_center2top_pre_ref = (
                transistors[i - 1][0].bbox[1][1] - ymove
            )  # Temporal // Minus the ymove because this one was already moved
            ymove_temp = (
                abs(distance_center2bottom_ref)
                + abs(distance_center2top_pre_ref)
                + min_separation
            )
            for k in range(len(transistors[i])):
                distance_center2bottom_temp = transistors[i][k].bbox[0][
                    1
                ]  # distance center to bottom of the transistor that will be moved
                distance_center2top_pre_temp = (
                    transistors[i - 1][k].bbox[1][1] - ymove
                )  # distance center to top of the transistor above the one that will be moved
                ymove_temp_2 = (
                    abs(distance_center2bottom_temp)
                    + abs(distance_center2top_pre_temp)
                    + min_separation
                )
                if ymove_temp_2 > ymove_temp:
                    ymove_temp = ymove_temp_2
            ymove += (
                ymove_temp
                if i == 1 or i == len(transistors) - 1
                else ymove_temp
                + 3 * evaluate_bbox(via_stack(pdk, "met1", "met2"))[1]
                + (evaluate_bbox(via_stack(pdk, "met1", "met2"))[1] * (max_array - 1))
            )
        for j in range(len(transistors[i])):
            size_transistor = evaluate_bbox(transistors[i][j])
            # Move the transistors in x direction
            if j == 0:
                # first transistor dont move
                xmove = 0
            else:
                pre_last_size = evaluate_bbox(transistors[i][j - 1])
                # rest of transistors
                xmove += (size_transistor[0] + pre_last_size[0]) / 2 + min_separation_x
            transistors[i][j].movex(pdk.snap_to_2xgrid(xmove))
            transistors[i][j].movey(pdk.snap_to_2xgrid(ymove))

            interdigitado.add_ports(
                transistors[i][j].get_ports_list(),
                prefix=str(i) + str(j) + "_" + str(array[i][j]) + "_",
            )
    # Center the component
    interdigitado = center_component_with_ports(interdigitado)
    ##RINGS
    # Define configurations according to transistor type
    device_config = {
        "nfet": {
            "sdlayer": "p+s/d",
            "well_layer": "pwell",
            "tap_enclosure_rule": "p+s/d",
        },
        "pfet": {
            "sdlayer": "n+s/d",
            "well_layer": "nwell",
            "tap_enclosure_rule": "n+s/d",
            "substrate_tap_layer": "p+s/d",
        },
    }

    # Obtaining the correct configuration
    config = device_config.get(deviceA_and_B)
    # Add tie if necessary
    if with_tie:
        tie_layers = ["met2", "met1"]

        tap_separation = max(
            pdk.get_grule("met2")["min_separation"],
            pdk.get_grule("met1")["min_separation"],
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule(config["tap_enclosure_rule"], "active_tap")[
            "min_enclosure"
        ]

        tap_encloses = (
            2 * (tap_separation + interdigitado.xmax),
            2 * (tap_separation + interdigitado.ymax),
        )
        tapring_ref = interdigitado << create_tapring_onchip(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer=config["sdlayer"],
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
            with_lvt_layer=with_lvt_layer,
        )
        interdigitado.add_ports(tapring_ref.get_ports_list(), prefix="tie_")
        if with_dummy:
            first_mos_ds = interdigitado.ports[
                "00_0_leftsd_met_array_row0_col0_top_met_W"
            ]
            first_mos_gate = interdigitado.ports["00_0_gate_W"]
            first_mos_ds_R = interdigitado.ports[
                "0"
                + str(len(arrayT) - 1)
                + "_0_"
                + "row0_col0_rightsd_met_array_row0_col0_top_met_E"
            ]
            first_mos_gate_R = interdigitado.ports[
                "0" + str(len(arrayT) - 1) + "_0_gate_E"
            ]
            last_mos_ds = interdigitado.ports[
                str(len(array) - 1) + "0_0_leftsd_met_array_row0_col0_top_met_W"
            ]
            last_mos_gate = interdigitado.ports[str(len(array) - 1) + "0_0_gate_W"]
            last_mos_ds_R = interdigitado.ports[
                str(len(array) - 1)
                + str(len(arrayT) - 1)
                + "_0_row0_col0_rightsd_met_array_row0_col0_top_met_E"
            ]
            last_mos_gate_R = interdigitado.ports[
                str(len(array) - 1) + str(len(arrayT) - 1) + "_0_gate_E"
            ]
            tie_left_W = interdigitado.ports["tie_W_array_row0_col0_top_met_W"]
            tie_right = interdigitado.ports["tie_E_array_row0_col0_top_met_E"]
            width_route_dummy = 1 if width >= 1 else width
            for i in range(len(array)):
                if i == 0:
                    # First Dummys
                    interdigitado << straight_route(
                        pdk, first_mos_ds_R, tie_left_W, width=width_route_dummy
                    )
                    interdigitado << straight_route(
                        pdk, first_mos_ds, tie_right, width=width_route_dummy
                    )
                    interdigitado << straight_route(pdk, first_mos_gate_R, tie_left_W)
                    interdigitado << straight_route(pdk, first_mos_gate, tie_right)
                elif i == len(array) - 1:
                    # Last Dummys
                    interdigitado << straight_route(
                        pdk, last_mos_ds_R, tie_left_W, width=width_route_dummy
                    )
                    interdigitado << straight_route(
                        pdk, last_mos_ds, tie_right, width=width_route_dummy
                    )
                    interdigitado << straight_route(pdk, last_mos_gate_R, tie_left_W)
                    interdigitado << straight_route(pdk, last_mos_gate, tie_right)
                else:
                    interdigitado << straight_route(
                        pdk,
                        interdigitado.ports[
                            str(i)
                            + "0_0_row0_col0_rightsd_met_array_row0_col0_top_met_E"
                        ],
                        tie_left_W,
                        width=width_route_dummy,
                    )
                    interdigitado << straight_route(
                        pdk,
                        interdigitado.ports[
                            str(i)
                            + str(len(array[0]) - 1)
                            + "_0_leftsd_met_array_row0_col0_top_met_W"
                        ],
                        tie_right,
                        width=width_route_dummy,
                    )
                    interdigitado << straight_route(
                        pdk, interdigitado.ports[str(i) + "0_0_gate_E"], tie_left_W
                    )
                    interdigitado << straight_route(
                        pdk,
                        interdigitado.ports[
                            str(i) + str(len(array[0]) - 1) + "_0_gate_W"
                        ],
                        tie_right,
                    )

    # Add well
    interdigitado.add_padding(
        layers=(pdk.get_glayer(config["well_layer"]),),
        default=pdk.get_grule(config["well_layer"], "active_tap")["min_enclosure"],
    )

    # Adding taps on the perimeter
    interdigitado = add_ports_perimeter(
        interdigitado, layer=pdk.get_glayer(config["well_layer"]), prefix="well_"
    )
    dims_post_tie = evaluate_bbox(interdigitado)

    # Add substrate tap if necessary
    if deviceA_and_B == "pfet":
        if with_substrate_tap:
            substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")[
                "min_separation"
            ]
            substrate_tap_encloses = (
                2 * (substrate_tap_separation + interdigitado.xmax),
                2 * (substrate_tap_separation + interdigitado.ymax),
            )
            ringtoadd = create_tapring_onchip(
                pdk,
                enclosed_rectangle=substrate_tap_encloses,
                sdlayer=config["substrate_tap_layer"],
                horizontal_glayer="met2",
                vertical_glayer="met1",
                with_lvt_layer=False,
            )
            tapring_ref = interdigitado << ringtoadd
            interdigitado.add_ports(
                tapring_ref.get_ports_list(), prefix="substratetap_"
            )

    # Outputs and routing
    size_interdigitado = evaluate_bbox(interdigitado)
    min_separation_met3 = pdk.get_grule("met3")["min_separation"]
    min_separation_met2 = pdk.get_grule("met2")["min_separation"]
    T_not_dummy = 0
    up = False
    down = False
    salidas_gate = list()

    for i in range(len(array)):
        for j in range(len(array[i])):
            if (i == 1 and with_dummy) or (i == 0 and with_dummy == False):
                # print('down')
                down = True
                up = False
            elif (i == len(array) - 2 and with_dummy) or (
                i == len(array) - 1 and with_dummy == False
            ):
                up = True
                down = False
                # print('up')
            else:
                up = False
                down = False

            if array[i][j] == 0:
                continue
            else:
                T_not_dummy += 1
                size_transistor = evaluate_bbox(transistors[i][j])
                port_reference_top = interdigitado.ports[
                    str(i) + str(j) + "_" + str(array[i][j]) + "_leftsd_top_met_N"
                ]
                port_reference_bottom = interdigitado.ports[
                    str(i) + str(j) + "_" + str(array[i][j]) + "_leftsd_top_met_S"
                ]
                port_referenceg_left = (
                    interdigitado.ports["11_" + str(array[1][1]) + "_gate_W"]
                    if with_dummy
                    else interdigitado.ports["00_" + str(array[0][0]) + "_gate_W"]
                )
                port_referenceg_right = interdigitado.ports[
                    str(i) + str(j) + "_" + str(array[i][j]) + "_gate_E"
                ]
                # port_reference_top.width = port_reference_bottom.width
                rect = rectangle(
                    (port_reference_top.width, port_reference_bottom.width),
                    layer=pdk.get_glayer("met3"),
                )
                rect_hor = rectangle(
                    (port_reference_top.width, port_reference_bottom.width),
                    layer=pdk.get_glayer("met2"),
                )
                via = via_stack(pdk, "met2", "met3")
                via_hor = via_stack(pdk, "met1", "met2")
                output_port = rect if output == "metal" else via
                rectg = rectangle(
                    (port_referenceg_left.width, port_referenceg_right.width),
                    layer=pdk.get_glayer("met2"),
                )
                size_rect = evaluate_bbox(rect)
                size_rectg = evaluate_bbox(rectg)
                size_via = evaluate_bbox(via)
                size_output = size_rect if output == "metal" else size_via
                size_via_hor = evaluate_bbox(via_hor)
                salidas_row = list()
                middle_port = list()
                drain = 0
                source = 0
                for k in range(fingers + 1):
                    if up and k % 2 == 0:
                        # print('placement up')
                        salidas_row.append(interdigitado << output_port)
                        reference = port_reference_top
                        separation = (
                            min_separation_met3 + size_output[1] + output_separation
                        )
                        distance_out_ring = (
                            size_interdigitado[1] / 2 - size_transistor[1]
                        )
                        ymove = distance_out_ring + separation * (array[i][j])
                        align_comp_to_port(salidas_row[-1], reference)
                        if common_route[0] and k % 2 == 0:
                            ymove -= separation * (array[i][j] - 1)
                        salidas_row[-1].movey(pdk.snap_to_2xgrid(ymove))
                        output_port_name = "e2" if output == "metal" else "top_met_S"
                        # print(salidas_row[-1].get_ports_list())
                        interdigitado << straight_route(
                            pdk,
                            salidas_row[-1].ports[output_port_name],
                            reference,
                            glayer1="met3",
                            glayer2="met2",
                        )
                        prefix = (
                            "drain_"
                            + str(i)
                            + str(j)
                            + "_"
                            + str(array[i][j])
                            + "_"
                            + str(drain)
                            + "_"
                        )
                        interdigitado.add_ports(
                            salidas_row[-1].get_ports_list(), prefix=prefix
                        )
                        drain += 1
                    elif up and k % 2 == 1:
                        # print(k,'ruteo')
                        # print('no break')
                        middle_port.append(interdigitado << via_hor)
                        move_middle_port = [
                            port_ruteo_top.center[0],
                            port_gate_top.center[1]
                            - (size_output[1] + size_via_hor[1]) / 2
                            - min_separation_met2,
                        ]
                        middle_port[-1].movex(
                            pdk.snap_to_2xgrid(move_middle_port[0])
                        ).movey(pdk.snap_to_2xgrid(move_middle_port[1]))
                        extra_movey = (min_separation_met2 + size_via_hor[1]) * (
                            array[i][j] - 1
                        )
                        middle_port[-1].movey(pdk.snap_to_2xgrid(-extra_movey))
                        interdigitado << straight_route(
                            pdk, port_ruteo_top, port_ruteo_bot
                        )
                        interdigitado.add_ports(
                            middle_port[-1].get_ports_list(),
                            prefix="middle_"
                            + str(i)
                            + str(j)
                            + "_"
                            + str(array[i][j])
                            + "_"
                            + str(k)
                            + "_",
                        )

                    elif down and k % 2 == 0:
                        # print('placement down')
                        salidas_row.append(interdigitado << output_port)
                        reference = port_reference_bottom
                        separation = (
                            min_separation_met3 + size_output[1] + output_separation
                        )
                        distance_out_ring = (
                            size_interdigitado[1] / 2 - size_transistor[1] / 2
                        )
                        ymove = -1 * (distance_out_ring + separation * (array[i][j]))
                        align_comp_to_port(salidas_row[-1], reference)
                        if common_route[1] and k % 2 == 0:
                            ymove += separation * (array[i][j])
                        salidas_row[-1].movey(
                            pdk.snap_to_2xgrid(ymove - output_separation)
                        )
                        output_port_name = "e2" if output == "metal" else "top_met_S"
                        # print(salidas_row[-1].get_ports_list())
                        interdigitado << straight_route(
                            pdk,
                            salidas_row[-1].ports[output_port_name],
                            reference,
                            glayer1="met3",
                            glayer2="met2",
                        )
                        prefix = (
                            "source_"
                            + str(i)
                            + str(j)
                            + "_"
                            + str(array[i][j])
                            + "_"
                            + str(source)
                            + "_"
                        )
                        interdigitado.add_ports(
                            salidas_row[-1].get_ports_list(), prefix=prefix
                        )
                        source += 1
                    if k == fingers:
                        break
                    port_reference_top = interdigitado.ports[
                        str(i)
                        + str(j)
                        + "_"
                        + str(array[i][j])
                        + "_row0_col"
                        + str(k)
                        + "_rightsd_top_met_N"
                    ]
                    port_reference_bottom = interdigitado.ports[
                        str(i)
                        + str(j)
                        + "_"
                        + str(array[i][j])
                        + "_row0_col"
                        + str(k)
                        + "_rightsd_top_met_S"
                    ]
                    if up:
                        port_ruteo_top = interdigitado.ports[
                            str(i)
                            + str(j)
                            + "_"
                            + str(array[i][j])
                            + "_row0_col"
                            + str(k)
                            + "_rightsd_top_met_S"
                        ]
                        port_gate_top = interdigitado.ports[
                            str(i) + str(j) + "_" + str(array[i][j]) + "_gate_E"
                        ]
                        port_ruteo_bot = interdigitado.ports[
                            str(i - 1)
                            + str(j)
                            + "_"
                            + str(array[i][j])
                            + "_row0_col"
                            + str(k)
                            + "_rightsd_top_met_S"
                        ]
    rows = len(array)
    cols = len(array[0])
    output_port = rect_hor if output == "metal" else via
    # Ruteo intermedio
    ports_name = [name for name in interdigitado.ports if "middle" in name]
    # print(ports_name)
    for i in range(max_array + 1):
        port_inicial = [
            name
            for name in interdigitado.ports
            if "middle_" in name
            and "_" + str(i) + "_1_" in name
            and "top_met_E" in name
        ]
        if len(port_inicial) > 1:
            interdigitado << straight_route(
                pdk,
                interdigitado.ports[port_inicial[0]],
                interdigitado.ports[port_inicial[-1]],
            )
        # print(port_inicial)

    # Ruteo gate
    for i in range(rows):
        if ((i > 0 and i < rows - 1) and with_dummy) or with_dummy == False:
            port_referenceg_left = (
                interdigitado.ports[str(i) + "1_" + str(array[1][1]) + "_gate_W"]
                if with_dummy
                else interdigitado.ports[str(i) + "0_" + str(array[0][0]) + "_gate_W"]
            )
            port_referenceg_right = (
                interdigitado.ports[
                    str(i) + str(cols - 2) + "_" + str(array[i][cols - 2]) + "_gate_E"
                ]
                if with_dummy
                else interdigitado.ports[
                    str(i) + str(cols - 1) + "_" + str(array[i][cols - 1]) + "_gate_E"
                ]
            )
            salidas_gate.append(interdigitado << output_port)
            salidas_gate.append(interdigitado << output_port)
            # referenceg = port_referenceg_left if l == 0 else port_referenceg_right
            align_comp_to_port(salidas_gate[-1], port_referenceg_left)
            align_comp_to_port(salidas_gate[-2], port_referenceg_right)
            separationg = min_separation_met3 + size_rectg[0]
            if with_dummy:
                distance_out_ring = (
                    size_interdigitado[0] / 2
                    - ((len(array[0])) / 2 - 1) * size_transistor[0]
                )
            else:
                distance_out_ring = 2 * separationg
            # xmove = -distance_out_ring -separationg if l==0 else distance_out_ring+separationg
            xmove_left = -distance_out_ring - separation
            xmove_right = distance_out_ring + separation
            salidas_gate[-1].movex(pdk.snap_to_2xgrid(xmove_left))
            salidas_gate[-2].movex(pdk.snap_to_2xgrid(xmove_right))
            # prefix = 'gate1_' if i==0 else 'gate2_'
            prefix_left = "gate_" + str(i) + "_l_"
            prefix_right = "gate_" + str(i) + "_r_"
            interdigitado.add_ports(
                salidas_gate[-1].get_ports_list(), prefix=prefix_left
            )
            interdigitado.add_ports(
                salidas_gate[-2].get_ports_list(), prefix=prefix_right
            )
            interdigitado = rename_ports_by_orientation(interdigitado)
            ports_gate = (
                ["gate_" + str(i) + "_l_E", "gate_" + str(i) + "_r_W"]
                if output == "metal"
                else [
                    "gate_" + str(i) + "_l_bottom_met_E",
                    "gate_" + str(i) + "_r_bottom_met_W",
                ]
            )
            interdigitado << straight_route(
                pdk,
                interdigitado.ports[ports_gate[0]],
                interdigitado.ports[ports_gate[1]],
                glayer1="met2",
                glayer2="met2",
            )

    # Save ports
    component = Component()
    component << interdigitado
    all_ports = interdigitado.ports

    ports = list()

    if with_tie:
        buscar = [
            "tie_N_top_met_W",
            "tie_N_top_met_N",
            "tie_N_top_met_E",
            "tie_N_top_met_S",
            "tie_S_top_met_W",
            "tie_S_top_met_N",
            "tie_S_top_met_E",
            "tie_S_top_met_S",
            "tie_E_top_met_W",
            "tie_E_top_met_N",
            "tie_E_top_met_E",
            "tie_E_top_met_S",
            "tie_W_top_met_W",
            "tie_W_top_met_N",
            "tie_W_top_met_E",
            "tie_W_top_met_S",
        ]
        selected_ports = dict()
        for busqueda in buscar:
            new_port = {
                name: port
                for name, port in all_ports.items()
                if busqueda in name and "row" not in name
            }
            selected_ports.update(new_port)
        for name, port in selected_ports.items():
            posicion = {"N": "up", "S": "down", "E": "right", "W": "left"}
            new_name = "bulk_" + posicion[name[4]] + "_" + name[-1]
            component.add_port(
                new_name,
                port.center,
                port.width,
                port.orientation,
                layer=port.layer,
                port_type="electrical",
            )

    ports = list()
    name = list()
    for i in range(len(array)):
        for j in range(len(array[i])):
            if array[i][j] == 0:
                continue
            else:
                out_source = 0
                out_drain = 0
                if (i == 1 and with_dummy) or (
                    i == 0 and with_dummy == False
                ):  # or i==rows-1)
                    for k in range(fingers + 1):
                        if k % 2 == 0:
                            if output == "metal":
                                ports.append(
                                    "source_"
                                    + str(i)
                                    + str(j)
                                    + "_"
                                    + str(array[i][j])
                                    + "_"
                                    + str(out_source)
                                    + "_"
                                )
                                name.append(
                                    "source_"
                                    + str(i)
                                    + str(j)
                                    + "_"
                                    + str(array[i][j])
                                    + "_"
                                    + str(out_source)
                                    + "_"
                                )
                            elif output == "via":
                                ports.append(
                                    "source_"
                                    + str(i)
                                    + str(j)
                                    + "_"
                                    + str(array[i][j])
                                    + "_"
                                    + str(out_source)
                                    + "_top_met_"
                                )
                                name.append(
                                    "source_"
                                    + str(i)
                                    + str(j)
                                    + "_"
                                    + str(array[i][j])
                                    + "_"
                                    + str(out_source)
                                    + "_"
                                )
                            out_source += 1
                if (i == rows - 2 and with_dummy) or (
                    i == rows - 1 and with_dummy == False
                ):
                    for k in range(fingers + 1):
                        if k % 2 == 0:
                            if output == "metal":
                                ports.append(
                                    "drain_"
                                    + str(i)
                                    + str(j)
                                    + "_"
                                    + str(array[i][j])
                                    + "_"
                                    + str(out_drain)
                                    + "_"
                                )
                                name.append(
                                    "drain_"
                                    + str(i)
                                    + str(j)
                                    + "_"
                                    + str(array[i][j])
                                    + "_"
                                    + str(out_drain)
                                    + "_"
                                )
                            elif output == "via":
                                ports.append(
                                    "drain_"
                                    + str(i)
                                    + str(j)
                                    + "_"
                                    + str(array[i][j])
                                    + "_"
                                    + str(out_drain)
                                    + "_top_met_"
                                )
                                name.append(
                                    "drain_"
                                    + str(i)
                                    + str(j)
                                    + "_"
                                    + str(array[i][j])
                                    + "_"
                                    + str(out_drain)
                                    + "_"
                                )
                            out_drain += 1

    for i in range(rows):
        if ((i > 0 and i < rows - 1) and with_dummy) or with_dummy == False:
            name_gate = (
                ["gate_" + str(i) + "_l_", "gate_" + str(i) + "_r_"]
                if output == "metal"
                else [
                    "gate_" + str(i) + "_l_top_met_",
                    "gate_" + str(i) + "_r_top_met_",
                ]
            )
            ports.append(name_gate[0])
            ports.append(name_gate[1])
            name.append("gate_" + str(i) + "_l_")
            name.append("gate_" + str(i) + "_r_")

    for i in range(len(ports)):
        filtrar_puertos(interdigitado, component, ports[i], name[i])
    # port name format metal output
    # source/drain + position + type transistor + output number(if there are more than one finger)
    # port name format via output
    # source/drain + position + type transistor + output number(if there are more than one finger) + top_met_
    # center component
    component = center_component_with_ports(component)
    return component  # return interdigitado


def create_tapring_onchip(
    pdk: MappedPDK,
    enclosed_rectangle=(2.0, 4.0),
    sdlayer: str = "p+s/d",
    horizontal_glayer: str = "met2",
    vertical_glayer: str = "met1",
    sides: tuple[bool, bool, bool, bool] = (True, True, True, True),
    with_lvt_layer=False,  # New input variable
) -> Component:
    """ptapring produce a p substrate / pwell tap rectanglular ring
    This ring will legally enclose a rectangular shape
    args:
    pdk: MappedPDK is the pdk to use
    enclosed_rectangle: tuple is the (width, hieght) of the area to enclose
    ****NOTE: the enclosed_rectangle will be the enclosed dimensions of active_tap
    horizontal_glayer: string=met2, layer used over the ring horizontally
    vertical_glayer: string=met1, layer used over the ring vertically
    sides: instead of creating the ring on all sides, only create it on the specified sides (W,N,E,S)
    ports:
    Narr_... all ports in top via array
    Sarr_... all ports in bottom via array
    Earr_... all ports in right via array
    Warr_... all ports in left via array
    bl_corner_...all ports in bottom left L route
    """
    enclosed_rectangle = pdk.snap_to_2xgrid(enclosed_rectangle, return_type="float")
    # check layers, activate pdk, create top cell
    pdk.has_required_glayers(
        [sdlayer, "active_tap", "mcon", horizontal_glayer, vertical_glayer]
    )
    pdk.activate()
    ptapring = Component()
    if not "met" in horizontal_glayer or not "met" in vertical_glayer:
        raise ValueError("both horizontal and vertical glayers should be metals")
    # check that ring is not too small
    min_gap_tap = pdk.get_grule("active_tap")["min_separation"]
    if enclosed_rectangle[0] < min_gap_tap:
        raise ValueError("ptapring must be larger than " + str(min_gap_tap))
    # create active tap
    tap_width = max(
        pdk.get_grule("active_tap")["min_width"],
        2 * pdk.get_grule("active_tap", "mcon")["min_enclosure"]
        + pdk.get_grule("mcon")["width"],
    )
    ptapring << rectangular_ring(
        enclosed_size=enclosed_rectangle,
        width=tap_width,
        centered=True,
        layer=pdk.get_glayer("active_tap"),
    )
    # create p plus area
    pp_enclosure = pdk.get_grule("active_tap", sdlayer)["min_enclosure"]
    pp_width = 2 * pp_enclosure + tap_width
    pp_enclosed_rectangle = [dim - 2 * pp_enclosure for dim in enclosed_rectangle]
    ptapring << rectangular_ring(
        enclosed_size=pp_enclosed_rectangle,
        width=pp_width,
        centered=True,
        layer=pdk.get_glayer(sdlayer),
    )

    ###########################################################################################################################################################
    # Create a LVT layer for LVT transistors from schematic design
    if pdk is sky130:
        # create 65/44 area
        con = (65, 44)
        ptapring << rectangular_ring(
            enclosed_size=enclosed_rectangle,
            width=tap_width,
            centered=True,
            layer=con,
        )

        if with_lvt_layer:
            # create lvt area for nmos
            lvt_layer = (125, 44)
            ptapring << rectangle(
                size=enclosed_rectangle,
                centered=True,
                layer=lvt_layer,
            )
    ###########################################################################################################################################################

    # create via arrs
    via_width_horizontal = evaluate_bbox(
        via_stack(pdk, "active_tap", horizontal_glayer)
    )[0]
    arr_size_horizontal = enclosed_rectangle[0]
    horizontal_arr = via_array(
        pdk,
        "active_tap",
        horizontal_glayer,
        (arr_size_horizontal, via_width_horizontal),
        minus1=True,
        lay_every_layer=True,
    )
    # Create via vertical
    via_width_vertical = evaluate_bbox(via_stack(pdk, "active_tap", vertical_glayer))[1]
    arr_size_vertical = enclosed_rectangle[1]
    vertical_arr = via_array(
        pdk,
        "active_tap",
        vertical_glayer,
        (via_width_vertical, arr_size_vertical),
        minus1=True,
        lay_every_layer=True,
    )

    # add via arrs
    refs_prefixes = list()
    if sides[1]:
        metal_ref_n = ptapring << horizontal_arr
        metal_ref_n.movey(round(0.5 * (enclosed_rectangle[1] + tap_width), 4))
        refs_prefixes.append((metal_ref_n, "N_"))
    if sides[2]:
        metal_ref_e = ptapring << vertical_arr
        metal_ref_e.movex(round(0.5 * (enclosed_rectangle[0] + tap_width), 4))
        refs_prefixes.append((metal_ref_e, "E_"))
    if sides[3]:
        metal_ref_s = ptapring << horizontal_arr
        metal_ref_s.movey(round(-0.5 * (enclosed_rectangle[1] + tap_width), 4))
        refs_prefixes.append((metal_ref_s, "S_"))
    if sides[0]:
        metal_ref_w = ptapring << vertical_arr
        metal_ref_w.movex(round(-0.5 * (enclosed_rectangle[0] + tap_width), 4))
        refs_prefixes.append((metal_ref_w, "W_"))
    # connect vertices
    if sides[1] and sides[0]:
        tlvia = ptapring << L_route(
            pdk, metal_ref_n.ports["top_met_W"], metal_ref_w.ports["top_met_N"]
        )
        refs_prefixes += [(tlvia, "tl_")]
    if sides[1] and sides[2]:
        trvia = ptapring << L_route(
            pdk, metal_ref_n.ports["top_met_E"], metal_ref_e.ports["top_met_N"]
        )
        refs_prefixes += [(trvia, "tr_")]
    if sides[3] and sides[0]:
        blvia = ptapring << L_route(
            pdk, metal_ref_s.ports["top_met_W"], metal_ref_w.ports["top_met_S"]
        )
        refs_prefixes += [(blvia, "bl_")]
    if sides[3] and sides[2]:
        brvia = ptapring << L_route(
            pdk, metal_ref_s.ports["top_met_E"], metal_ref_e.ports["top_met_S"]
        )
        refs_prefixes += [(brvia, "br_")]
    # add ports, flatten and return
    for ref_, prefix in refs_prefixes:
        ptapring.add_ports(ref_.get_ports_list(), prefix=prefix)
    return component_snap_to_grid(ptapring)


def __gen_fingers_macro(
    pdk: MappedPDK,
    rmult: int,
    fingers: int,
    length: float,
    width: float,
    poly_height: float,
    sdlayer: str,
    inter_finger_topmet: str,
) -> Component:
    """internal use: returns an array of fingers"""
    length = pdk.snap_to_2xgrid(length)
    width = pdk.snap_to_2xgrid(width)
    poly_height = pdk.snap_to_2xgrid(poly_height)
    # sizing_ref_viastack = via_stack(pdk, "active_diff", "met1")  This variable is not used
    # figure out poly (gate) spacing: s/d metal doesnt overlap transistor, s/d min seperation criteria is met
    sd_viaxdim = rmult * evaluate_bbox(via_stack(pdk, "active_diff", "met1"))[0]
    poly_spacing = (
        2 * pdk.get_grule("poly", "mcon")["min_separation"]
        + pdk.get_grule("mcon")["width"]
    )
    poly_spacing = max(sd_viaxdim, poly_spacing)
    met1_minsep = pdk.get_grule("met1")["min_separation"]
    poly_spacing += met1_minsep if length < met1_minsep else 0
    # create a single finger
    finger = Component("finger")
    gate = finger << rectangle(
        size=(length, poly_height), layer=pdk.get_glayer("poly"), centered=True
    )
    sd_viaarr = via_array(
        pdk,
        "active_diff",
        "met1",
        size=(sd_viaxdim, width),
        minus1=True,
        lay_bottom=False,
    ).copy()
    interfinger_correction = via_array(
        pdk,
        "met1",
        inter_finger_topmet,
        size=(None, width),
        lay_every_layer=True,
        num_vias=(1, None),
    )

    ###########################################################################################################################################################
    sd_viaarr_ref = finger << sd_viaarr
    sd_viaarr_ref_met_top = (
        finger << interfinger_correction
    )  # Separate vias are added to save the ports of the inter_finger_topmetal metals.
    sd_viaarr_ref_met_top.movex((poly_spacing + length) / 2)
    sd_viaarr_ref.movex((poly_spacing + length) / 2)
    finger.add_ports(gate.get_ports_list(), prefix="gate_")
    finger.add_ports(sd_viaarr_ref.get_ports_list(), prefix="rightsd_")
    finger.add_ports(
        sd_viaarr_ref_met_top.get_ports_list(), prefix="rightsd_met_"
    )  # Right inter_finger_topmet metal ports are saved
    ###########################################################################################################################################################

    # create finger array
    fingerarray = prec_array(
        finger,
        columns=fingers,
        rows=1,
        spacing=(poly_spacing + length, 1),
        absolute_spacing=True,
    )
    sd_via_ref_left = fingerarray << sd_viaarr
    sd_via_ref_left_met_top = (
        fingerarray << interfinger_correction
    )  # A separate via array is added to store the ports of the inter_finger_topmet metals.
    sd_via_ref_left.movex(0 - (poly_spacing + length) / 2)
    sd_via_ref_left_met_top.movex(0 - (poly_spacing + length) / 2)
    fingerarray.add_ports(sd_via_ref_left.get_ports_list(), prefix="leftsd_")
    fingerarray.add_ports(
        sd_via_ref_left_met_top.get_ports_list(), prefix="leftsd_met_"
    )  # Left inter_finger_topmet metal ports are saved
    # center finger array and add ports
    centered_farray = Component()
    fingerarray_ref_center = prec_ref_center(fingerarray)
    centered_farray.add(fingerarray_ref_center)
    centered_farray.add_ports(fingerarray_ref_center.get_ports_list())
    # create diffusion and +doped region
    multiplier = rename_ports_by_orientation(centered_farray)
    diff_extra_enc = 2 * pdk.get_grule("mcon", "active_diff")["min_enclosure"]
    diff_dims = (diff_extra_enc + evaluate_bbox(multiplier)[0], width)
    diff = multiplier << rectangle(
        size=diff_dims, layer=pdk.get_glayer("active_diff"), centered=True
    )
    sd_diff_ovhg = pdk.get_grule(sdlayer, "active_diff")["min_enclosure"]
    sdlayer_dims = [dim + 2 * sd_diff_ovhg for dim in diff_dims]
    sdlayer_ref = multiplier << rectangle(
        size=sdlayer_dims, layer=pdk.get_glayer(sdlayer), centered=True
    )
    multiplier.add_ports(sdlayer_ref.get_ports_list(), prefix="plusdoped_")
    multiplier.add_ports(diff.get_ports_list(), prefix="diff_")

    return component_snap_to_grid(rename_ports_by_orientation(multiplier))


# drain is above source
def multiplier(
    pdk: MappedPDK,
    sdlayer: str,
    width: Optional[float] = 3,
    length: Optional[float] = None,
    fingers: int = 1,
    routing: bool = True,
    inter_finger_topmet: str = "met2",
    dummy: Union[bool, tuple[bool, bool]] = True,
    sd_route_topmet: str = "met2",
    gate_route_topmet: str = "met2",
    rmult: Optional[int] = None,
    sd_rmult: int = 1,
    gate_rmult: int = 1,
    interfinger_rmult: int = 1,
    sd_route_extension: float = 0,
    gate_route_extension: float = 0,
    dummy_routes: bool = True,
    gate_up: Optional[bool] = False,
    gate_down: Optional[bool] = False,
) -> Component:
    """Generic poly/sd vias generator
    args:
    pdk = pdk to use
    sdlayer = either p+s/d for pmos or n+s/d for nmos
    width = expands the transistor in the y direction
    length = transitor length (if left None defaults to min length)
    fingers = introduces additional fingers (sharing s/d) of width=width
    routing = true or false, specfies if sd should be connected
    inter_finger_topmet = top metal of the via array laid on the source/drain regions
    ****NOTE: routing metal is layed over the source drain regions regardless of routing option
    dummy = true or false add dummy active/plus doped regions
    sd_rmult = multiplies thickness of sd metal (int only)
    gate_rmult = multiplies gate by adding rows to the gate via array (int only)
    interfinger_rmult = multiplies thickness of source/drain routes between the gates (int only)
    sd_route_extension = float, how far extra to extend the source/drain connections (default=0)
    gate_route_extension = float, how far extra to extend the gate connection (default=0)
    dummy_routes: bool default=True, if true add add vias and short dummy poly,source,drain

    ports (one port for each edge),
    ****NOTE: source is below drain:
    gate_... all edges (top met route of gate connection)
    source_...all edges (top met route of source connections)
    drain_...all edges (top met route of drain connections)
    plusdoped_...all edges (area of p+s/d or n+s/d layer)
    diff_...all edges (diffusion region)
    rowx_coly_...all ports associated with finger array include gate_... and array_ (array includes all ports of the viastacks in the array)
    leftsd_...all ports associated with the left most via array
    dummy_L,R_N,E,S,W ports if dummy_routes=True
    """
    # error checking
    if "+s/d" not in sdlayer:
        raise ValueError("specify + doped region for multiplier")
    if not "met" in sd_route_topmet or not "met" in gate_route_topmet:
        raise ValueError("topmet specified must be metal layer")
    if rmult:
        if rmult < 1:
            raise ValueError("rmult must be positive int")
        sd_rmult = rmult
        gate_rmult = 1
        interfinger_rmult = (rmult - 1) or 1
    if sd_rmult < 1 or interfinger_rmult < 1 or gate_rmult < 1:
        raise ValueError("routing multipliers must be positive int")
    if fingers < 1:
        raise ValueError("number of fingers must be positive int")

    ###########################################################################################################################################################
    # Conditions to avoid double overlapping or duplication of gates in dummies
    if gate_up and gate_down:
        raise ValueError("Gate up and Down can't be at the same time")
    if routing and (gate_down or gate_up):
        raise ValueError("Gate up and Down can't be used with routing")
    ###########################################################################################################################################################

    # argument parsing and rule setup
    min_length = pdk.get_grule("poly")["min_width"]
    length = min_length if (length or min_length) <= min_length else length
    length = pdk.snap_to_2xgrid(length)
    min_width = max(min_length, pdk.get_grule("active_diff")["min_width"])
    width = min_width if (width or min_width) <= min_width else width
    width = pdk.snap_to_2xgrid(width)
    poly_height = width + 2 * pdk.get_grule("poly", "active_diff")["overhang"]
    # call finger array
    multiplier = __gen_fingers_macro(
        pdk,
        interfinger_rmult,
        fingers,
        length,
        width,
        poly_height,
        sdlayer,
        inter_finger_topmet,
    )
    # route all drains/ gates/ sources
    if routing:
        # place vias, then straight route from top port to via-botmet_N
        sd_N_port = multiplier.ports["leftsd_top_met_N"]
        sdvia = via_stack(pdk, "met1", sd_route_topmet)
        sdmet_hieght = sd_rmult * evaluate_bbox(sdvia)[1]
        sdroute_minsep = pdk.get_grule(sd_route_topmet)["min_separation"]
        sdvia_ports = list()
        for finger in range(fingers + 1):
            diff_top_port = movey(sd_N_port, destination=width / 2)
            # place sdvia such that metal does not overlap diffusion
            big_extension = sdroute_minsep + sdmet_hieght / 2 + sdmet_hieght
            sdvia_extension = big_extension if finger % 2 else sdmet_hieght / 2
            sdvia_ref = align_comp_to_port(sdvia, diff_top_port, alignment=("c", "t"))
            multiplier.add(
                sdvia_ref.movey(
                    sdvia_extension + pdk.snap_to_2xgrid(sd_route_extension)
                )
            )
            multiplier << straight_route(
                pdk, diff_top_port, sdvia_ref.ports["bottom_met_N"]
            )
            sdvia_ports += [sdvia_ref.ports["top_met_W"], sdvia_ref.ports["top_met_E"]]
            # get the next port (break before this if last iteration because port D.N.E. and num gates=fingers)
            if finger == fingers:
                break
            sd_N_port = multiplier.ports[f"row0_col{finger}_rightsd_top_met_N"]
            # route gates
            gate_S_port = multiplier.ports[f"row0_col{finger}_gate_S"]
            metal_seperation = pdk.util_max_metal_seperation()
            psuedo_Ngateroute = movey(
                gate_S_port.copy(), 0 - metal_seperation - gate_route_extension
            )
            psuedo_Ngateroute.y = pdk.snap_to_2xgrid(psuedo_Ngateroute.y)
            multiplier << straight_route(pdk, gate_S_port, psuedo_Ngateroute)
        # place route met: gate
        gate_width = (
            gate_S_port.center[0]
            - multiplier.ports["row0_col0_gate_S"].center[0]
            + gate_S_port.width
        )
        gate = rename_ports_by_list(
            via_array(
                pdk,
                "poly",
                gate_route_topmet,
                size=(gate_width, None),
                num_vias=(None, gate_rmult),
                no_exception=True,
                fullbottom=True,
            ),
            [("top_met_", "gate_")],
        )
        gate_ref = align_comp_to_port(
            gate.copy(),
            psuedo_Ngateroute,
            alignment=(None, "b"),
            layer=pdk.get_glayer("poly"),
        )
        multiplier.add(gate_ref)
        # place route met: source, drain
        sd_width = sdvia_ports[-1].center[0] - sdvia_ports[0].center[0]
        sd_route = rectangle(
            size=(sd_width, sdmet_hieght),
            layer=pdk.get_glayer(sd_route_topmet),
            centered=True,
        )
        source = align_comp_to_port(
            sd_route.copy(), sdvia_ports[0], alignment=(None, "c")
        )
        drain = align_comp_to_port(
            sd_route.copy(), sdvia_ports[2], alignment=(None, "c")
        )
        multiplier.add(source)
        multiplier.add(drain)
        # add ports
        multiplier.add_ports(drain.get_ports_list(), prefix="drain_")
        multiplier.add_ports(source.get_ports_list(), prefix="source_")
        multiplier.add_ports(gate_ref.get_ports_list(prefix="gate_"))

    ###########################################################################################################################################################
    # Added the option to place the gate above or below the component along with its connection ports as long as routing = False.
    if gate_down:
        for finger in range(fingers):
            gate_S_port = multiplier.ports[f"row0_col{finger}_gate_S"]
            metal_seperation = pdk.util_max_metal_seperation()
            psuedo_Ngateroute = movey(
                gate_S_port.copy(), 0 - metal_seperation - gate_route_extension
            )
            psuedo_Ngateroute.y = pdk.snap_to_2xgrid(psuedo_Ngateroute.y)
            multiplier << straight_route(pdk, gate_S_port, psuedo_Ngateroute)
        gate_width = (
            gate_S_port.center[0]
            - multiplier.ports["row0_col0_gate_S"].center[0]
            + gate_S_port.width
        )
        gate = rename_ports_by_list(
            via_array(
                pdk,
                "poly",
                gate_route_topmet,
                size=(gate_width, None),
                num_vias=(None, gate_rmult),
                no_exception=True,
                fullbottom=True,
            ),
            [("top_met_", "gate_")],
        )
        gate_ref = align_comp_to_port(
            gate.copy(),
            psuedo_Ngateroute,
            alignment=(None, "b"),
            layer=pdk.get_glayer("poly"),
        )
        multiplier.add(gate_ref)
        multiplier.add_ports(gate_ref.get_ports_list(prefix="gate_"))
    elif gate_up:
        for finger in range(fingers):
            gate_N_port = multiplier.ports[f"row0_col{finger}_gate_N"]
            metal_seperation = pdk.util_max_metal_seperation()
            psuedo_Ngateroute = movey(
                gate_N_port.copy(), 0 + metal_seperation + gate_route_extension
            )
            psuedo_Ngateroute.y = pdk.snap_to_2xgrid(psuedo_Ngateroute.y)
            multiplier << straight_route(pdk, gate_N_port, psuedo_Ngateroute)
        gate_width = (
            gate_N_port.center[0]
            - multiplier.ports["row0_col0_gate_N"].center[0]
            + gate_N_port.width
        )
        gate = rename_ports_by_list(
            via_array(
                pdk,
                "poly",
                gate_route_topmet,
                size=(gate_width, None),
                num_vias=(None, gate_rmult),
                no_exception=True,
                fullbottom=True,
            ),
            [("top_met_", "gate_")],
        )
        gate_ref = align_comp_to_port(
            gate.copy(),
            psuedo_Ngateroute,
            alignment=(None, "t"),
            layer=pdk.get_glayer("poly"),
        )
        multiplier.add(gate_ref)
        multiplier.add_ports(gate_ref.get_ports_list(prefix="gate_"))
    ###########################################################################################################################################################

    # create dummy regions
    if isinstance(dummy, bool):
        dummyl = dummyr = dummy
    else:
        dummyl, dummyr = dummy
    if dummyl or dummyr:
        dummy = __gen_fingers_macro(
            pdk,
            rmult=interfinger_rmult,
            fingers=1,
            length=length,
            width=width,
            poly_height=poly_height,
            sdlayer=sdlayer,
            inter_finger_topmet="met1",
        )
        dummyvia = dummy << via_stack(pdk, "poly", "met1", fullbottom=True)
        align_comp_to_port(
            dummyvia, dummy.ports["row0_col0_gate_S"], layer=pdk.get_glayer("poly")
        )
        dummy << L_route(
            pdk, dummyvia.ports["top_met_W"], dummy.ports["leftsd_top_met_S"]
        )
        dummy << L_route(
            pdk, dummyvia.ports["top_met_E"], dummy.ports["row0_col0_rightsd_top_met_S"]
        )
        dummy.add_ports(dummyvia.get_ports_list(), prefix="gsdcon_")
        dummy_space = pdk.get_grule(sdlayer)["min_separation"] + dummy.xmax
        sides = list()
        if dummyl:
            sides.append((-1, "dummy_L_"))
        if dummyr:
            sides.append((1, "dummy_R_"))
        for side, name in sides:
            dummy_ref = multiplier << dummy
            dummy_ref.movex(side * (dummy_space + multiplier.xmax))
            multiplier.add_ports(dummy_ref.get_ports_list(), prefix=name)
    return component_snap_to_grid(rename_ports_by_orientation(multiplier))


def layer_pin_and_label(pdk:MappedPDK, metal: str, label_or_pin: str):
    if not "met" in metal:
        raise ValueError("layer must be a metal")
    if label_or_pin not in ["label", "pin"]:
        raise ValueError("label_or_pin must be 'label' or 'pin'")

    if pdk is sky130:
        diccionario_label = {
            "met1": (67, 5),
            "met2": (68, 5),
            "met3": (69, 5),
            "met4": (70, 5),
            "met5": (71, 5),
        }
        diccionario_pin = {
            "met1": (67, 16),
            "met2": (68, 16),
            "met3": (69, 16),
            "met4": (70, 16),
            "met5": (71, 16),
        }
    
    elif pdk is gf180:
        diccionario_label = {
            "met1": (34, 10),
            "met2": (36, 10),
            "met3": (42, 10),
            "met4": (46, 10),
            "met5": (81, 10),
        }
        diccionario_pin = {
            "met1": (67, 16),
            "met2": (68, 16),
            "met3": (69, 16),
            "met4": (70, 16),
            "met5": (71, 16),
        }
    if label_or_pin == "label":
        layer = diccionario_label[metal]
    else:
        layer = diccionario_pin[metal]
    return layer


def pin_label_creation(pdk:MappedPDK, pin, label, met, componente, signal: bool = False):
    # Obtengo el ancho del port en x e y
    x_size = componente.ports[pin + "_N"].width
    y_size = componente.ports[pin + "_W"].width
    label_met = layer_pin_and_label(pdk, met, "label")
    pin_met = layer_pin_and_label(pdk, met, "pin")
    # Obtengo la posicion central del port
    pos = [
        componente.ports[pin + "_N"].center[0],
        componente.ports[pin + "_E"].center[1],
    ]
    # Calculo el centro del rectangulo con la layer del pian a agregar
    center = [pos[0] - y_size / 2, pos[1] - y_size / 2]
    # Creo el rectangulo para pin
    if pdk is sky130:
        pin_rectangle = rectangle(size=(y_size, y_size), layer=pin_met)
        # Agrego el pin y lo centro
        pin_t = componente << pin_rectangle
        pl = pin_t.bbox
        offset = -pl[0]
        pin_t.move(destination=offset)
        # Lo ubico a la posicion final calculada
        pin_t.movey(center[1]).movex(center[0])
        # Agrego los ports al componente
        componente.add_ports(pin_t.get_ports_list(), prefix=label + "_")
    # Agrego el label segun el metal
    componente.add_label(label, position=(pos[0], pos[1]), layer=label_met)
    if signal:
        print(f"Pin {pin} and label {label} created on component with metal {met}.")


def filtrar_puertos(
    componente_original,
    componente_filtrado,
    filtro,
    port_name: Optional[str] = None,
    signal: bool = False,
):
    if port_name is None:
        port_name = filtro
    all_ports = componente_original.ports
    buscar_w = filtro + "W"
    buscar_e = filtro + "E"
    buscar_n = filtro + "N"
    buscar_s = filtro + "S"
    if buscar_w not in all_ports:
        raise ValueError(f"Port not found")
    selected_ports = {
        name: port
        for name, port in all_ports.items()
        if buscar_w in name or buscar_e in name or buscar_n in name or buscar_s in name
    }  # Ejemplo: solo los que tienen 'in' en su nombre
    for name_original, port in selected_ports.items():
        new_name = port_name + name_original[-1]  # Add prefix
        componente_filtrado.add_port(
            new_name,
            port.center,
            port.width,
            port.orientation,
            layer=port.layer,
            port_type="electrical",
        )
    if signal:
        print(f"Port {port_name} filtered and added to the component.")


def center_component_with_ports(component: Component) -> Component:
    centered = Component()
    ref = centered << component

    # Calcular el desplazamiento necesario para centrar
    dx, dy = -component.center[0], -component.center[1]
    ref.move((dx, dy))  # Mueve la referencia al centro

    # Transformar y añadir los puertos
    for port in component.get_ports_list():
        new_port = port.copy()
        new_port.center = (port.center[0] + dx, port.center[1] + dy)
        centered.add_port(name=port.name, port=new_port)

    return centered


def Boundary_layer(pdk:MappedPDK, componente=Component(), layer=(235, 4)) -> Component:
    if pdk is sky130:
        layer=(235, 4)
    elif pdk is gf180:
        layer=(63,0)
    dimension = evaluate_bbox(componente)
    rectangle_boundary = rectangle(
        (dimension[0], dimension[1]), layer=layer, centered=True
    )
    rect_ref = componente << rectangle_boundary
    return rect_ref


def rails(
    pdk,
    component: Component,
    width: float,
    route_list: Optional[list] = None,
    specific_rail: Optional[list] = None,
) -> Component:

    if specific_rail != None:
        for info in specific_rail:
            if len(info) > 2:
                raise ValueError(
                    "Each component must be conformed by rail label and rail number (left to right)"
                )
    size_component = evaluate_bbox(component)
    rectangle_ref = rectangle(
        (width, size_component[1]), layer=pdk.get_glayer("met5"), centered=True
    )
    min_separation_met5 = pdk.get_grule("met5")["min_separation"]
    L = size_component[0]
    W = width
    s_min = min_separation_met5 if W < min_separation_met5 else W / 2
    separation = W
    n = 1
    while True:
        s_n = (L - (2 * n + 1) * W) / (2 * n)
        if s_n < s_min:
            n -= 1
            break
        if s_n < separation:
            separation = s_n
        n += 1
    n_rectangles = n * 2 + 1
    space = separation + width
    carril = list()
    rail_list = list()
    prefix_list = list()
    Available_space = dict()
    if specific_rail is not None:
        Available_space = {item[0]: [] for item in specific_rail}
    Available_space["VSS"] = []
    Available_space["VDD"] = []
    for i in range(n_rectangles):
        carril.append(component << rectangle_ref)
        carril[-1].movex(pdk.snap_to_2xgrid(-size_component[0] / 2 + width / 2))
        carril[-1].movex(pdk.snap_to_2xgrid(space * i))
        prefijo = None
        if specific_rail != None:
            for rail_info in specific_rail:
                for rail in rail_info[1]:
                    if i + 1 == rail:
                        prefijo = rail_info[0] + "_" + str(i + 1) + "_"
                        prefijo_label = rail_info[0]
                        rail_list.append(rail_info[0])
                        break
        if prefijo is None:
            if i % 2 == 0:
                prefijo = "VSS_" + str(i + 1) + "_"
                prefijo_label = 'VSS'
                rail_list.append("VSS")
            else:
                prefijo = "VDD_" + str(i + 1) + "_"
                prefijo_label = 'VDD'
                rail_list.append("VDD")
        prefix_list.append(prefijo)
        component.add_ports(carril[-1].ports, prefix=prefijo)
        component = rename_ports_by_orientation(component)
        pin_label_creation(pdk, prefijo[0:-1], prefijo_label, 'met5', component)
    
    ports = [
        name
        for name in component.ports
        if "Ref1_B_drain_T" in name or "Ref1_B_source_T" in name
    ]
    #print(ports)
    # Available spaces
    for i in range(len(rail_list)):
        Available_space[rail_list[i]].append(
            [
                component.ports[prefix_list[i] + "W"].center[0],
                component.ports[prefix_list[i] + "E"].center[0],
            ]
        )

    # Via conection
    via_ref = via_stack(pdk, "met4", "met5")
    min_separation_via5 = pdk.get_grule("via4")["min_separation"]
    separation = evaluate_bbox(via_ref)[0] + min_separation_via5
    for route in route_list:
        if (len(route)) != 2:
            raise ValueError(
                "Each route must be conformed by a port name and a rail name"
            )
        if route[1] not in Available_space:
            raise ValueError("The rail name must be in the specific rail list")
        port_E = route[0] + "E"
        port_W = route[0] + "W"
        # ports = [name for name in component.ports if 'Ref1_A_drain_T' in name]
        # print(ports)
        range_ports_available = [
            component.ports[port_W].center[0],
            component.ports[port_E].center[0],
        ]
        space_available = abs(range_ports_available[1] - range_ports_available[0])
        if space_available < separation:
            raise ValueError("There is not enough space to add the via")
        n_vias = int(space_available // separation)
        vias = list()
        for i in range(n_vias):
            movement_x = range_ports_available[0] + separation / 2 + separation * i
            movement_y = component.ports[port_W].center[1]
            for j in range(len(Available_space[route[1]])):
                if (
                    Available_space[route[1]][j][0] + evaluate_bbox(via_ref)[0] / 2
                    < movement_x
                    < Available_space[route[1]][j][1] - evaluate_bbox(via_ref)[0] / 2
                ):
                    vias.append(component << via_ref)
                    vias[-1].movex(movement_x).movey(movement_y)
                    # component.add_ports(vias[-1].ports, prefix=route[0]+'_via_')
                    break
