from glayout import MappedPDK, sky130, gf180
from glayout import nmos, pmos, tapring, via_stack

# from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from n_fets_interdigitized import n_transistor_interdigitized
from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory.components import text_freetype, rectangle
from pathlib import Path

from glayout.routing import c_route, L_route, straight_route
from glayout.spice.netlist import Netlist

from glayout.util.port_utils import add_ports_perimeter, rename_ports_by_orientation
from glayout.util.comp_utils import (
    evaluate_bbox,
    prec_center,
    prec_ref_center,
    align_comp_to_port,
)
from glayout.util.snap_to_grid import component_snap_to_grid
from gdsfactory.port import Port
from typing import Optional, Union

###### Only Required for IIC-OSIC Docker
import os
import subprocess

# Run a shell, source .bashrc, then printenv
cmd = 'bash -c "source ~/.bashrc && printenv"'
result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
env_vars = {}
for line in result.stdout.splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        env_vars[key] = value

# Now, update os.environ with these
os.environ.update(env_vars)


# @validate_arguments
def generate_input_stage_netlist(
    pdk: MappedPDK,
    prefix: str,
    instance_name: str,
    CM_size: tuple[float, float, int],  # (width, length, multipliers)
    source_net_in: str,
    gate_net_en: str,  # Auxiliary node
    drain_net_out_vin: str,
    drain_net_out_vcm: str,
    drain_net_out_bcm: str,
    drain_net_out_ccm: str,
    transistor_type: str = "nfet",
    bulk_net: str = None,
    proposed_ground: str = None,  # Proposed ground net
    dummy: bool = True,
    subckt_only: bool = False,
    show_netlist: bool = False,
    **kwargs,
) -> Netlist:
    """Generate a netlist for a regulated cascode current mirror."""

    if bulk_net is None:
        bulk_net = "VDD" if transistor_type.lower() == "pfet" else "VSS"

    width = CM_size[0]
    length = CM_size[1]
    multipliers = CM_size[2]
    fingers = CM_size[3]  # Number of fingers of the interdigitized fets
    mtop = multipliers * fingers if subckt_only else 1
    # mtop = multipliers * 2 if dummy else multipliers  # Double the multiplier to account for the dummies

    model_name = pdk.models[transistor_type.lower()]

    circuit_name = prefix
    # Take only unique NET names
    nodes =[
                source_net_in,
                gate_net_en,
                drain_net_out_vin,
                drain_net_out_vcm,
                drain_net_out_bcm,
                drain_net_out_ccm,
                bulk_net,
            ]
    source_netlist = f".subckt {circuit_name} {' '.join(nodes)}\n"

    # Proposed ground connection (commented)
    # source_netlist += f"V{proposed_ground}1 ({proposed_ground} {bulk_net}) 0\n"

    # Generating six transistors:
    middle_gate = "VMG"
    middleB_bottomB = "VMBB"
    middleC_bottomC = "VMBC"
    middleD_bottomD = "VMBD"
    middleE_bottomE = "VMBE"

    source_netlist += (
        f"X{prefix}_TA {middle_gate} {gate_net_en} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_TB {middle_gate} {gate_net_en} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_TC {middle_gate} {gate_net_en} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_TD {middle_gate} {gate_net_en} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_MA {middle_gate} {middle_gate} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_MB {middleB_bottomB} {middle_gate} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_MC {middleC_bottomC} {middle_gate} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_MD {middleD_bottomD} {middle_gate} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_ME {middleE_bottomE} {middle_gate} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_BA {source_net_in} {source_net_in} {middle_gate} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_BB {drain_net_out_vcm} {source_net_in} {middleB_bottomB} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_BC {drain_net_out_bcm} {source_net_in} {middleC_bottomC} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_BD {drain_net_out_ccm} {source_net_in} {middleD_bottomD} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    source_netlist += (
        f"X{prefix}_BE {drain_net_out_vin} {source_net_in} {middleE_bottomE} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    if dummy:
        source_netlist += (
            f"X{prefix}_DUMMY {bulk_net} {bulk_net} {bulk_net} {bulk_net} "
            f"{model_name} l={length} w={width} m={6}\n"
        )

    source_netlist += ".ends " + circuit_name

    instance_format = "X{name} {nodes} {circuit_name} l={length} w={width} m={mult}"

    topnet = Netlist(
        circuit_name=circuit_name,
        nodes=nodes,
        source_netlist=source_netlist,
        instance_format=instance_format,
        parameters={
            "model": model_name,
            "width": width,
            "length": length,
            "mult": multipliers,
        },
    )

    if show_netlist:
        generated_netlist_for_lvs = topnet.generate_netlist()
        print("Generated netlist :\n", generated_netlist_for_lvs)

        file_path_local_storage = "./gen_netlist.txt"
        try:
            with open(file_path_local_storage, "w") as file:
                file.write(generated_netlist_for_lvs)
        except Exception:
            print(
                "Verify the file availability and type: ",
                generated_netlist_for_lvs,
                type(generated_netlist_for_lvs),
            )

    return topnet


# @validate_arguments
def input_stage(
    pdk: MappedPDK,
    Width: float = 1,
    Length: Optional[float] = 1,
    num_cols: int = 1,
    fingers: int = 1,
    multipliers: int = 1,
    type: Optional[str] = "pfet",
    with_substrate_tap: Optional[bool] = False,
    with_tie: Optional[bool] = True,
    with_dummy: Optional[bool] = False,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    show_netlist: Optional[bool] = False,
    add_labels = True,
    **kwargs,
) -> Component:
    """An instantiable self biased casoded current mirror that returns a Component object."""

    pdk.activate()
    maxmet_sep = pdk.util_max_metal_seperation()
    n_well_sep = maxmet_sep
    psize = (0.35, 0.35)

    # Create the current mirror component
    top_level = Component(name="input_stage")
    top_level.name = "input_stage"
    Length = Length if Length is not None else pdk.get_grule("poly")["min_width"]
    top_ref = prec_ref_center(top_level)

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # BOTTOM CURRENT MIRRORS
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    currm_bottom = n_transistor_interdigitized(
        pdk,
        device="pfet",
        numcols=1,
        n_devices=5,
        with_substrate_tap=False,
        with_tie=False,
        width=Width,
        length=Length,
    )

    currm_bottom = top_level << currm_bottom
    currm_bottom.name = "currm_bottom"

    currm_bottom_ref = prec_ref_center(currm_bottom)
    currm_bottom_ref.move(top_ref.center)
    top_level.add(currm_bottom_ref)

    top_level.add_ports(currm_bottom_ref.get_ports_list(), prefix="currm_bottom_")

    dist_DS = (
        abs(
            top_level.ports[f"currm_bottom_A_0_drain_E"].center[0]
            - top_level.ports[f"currm_bottom_A_0_drain_W"].center[0]
        )
        / 2
    )

    dist_GS = (
        abs(
            top_level.ports[f"currm_bottom_A_0_gate_E"].center[0]
            - top_level.ports[f"currm_bottom_A_0_gate_W"].center[0]
        )
        / 2
    )

    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    viam1m2 = via_stack(pdk, "met1", "met2", centered=True)

    bottomA_drain_via = top_level << viam2m3
    bottomA_drain_via.move(top_level.ports[f"currm_bottom_A_0_drain_W"].center).movex(
        dist_DS
    )

    bottomA_gate_via = top_level << viam2m3
    bottomA_gate_via.move(top_level.ports[f"currm_bottom_A_0_gate_W"].center).movex(
        dist_GS
    )

    top_level << straight_route(
        pdk,
        bottomA_drain_via.ports["top_met_N"],
        bottomA_gate_via.ports["top_met_S"],
        glayer1="met3",
        glayer2="met3",
    )

    poly_to_met2_via = via_stack(pdk, glayer1="poly", glayer2="met2", centered=True)

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # MIDDLE CURRENT MIRRORS
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    currm_middle = n_transistor_interdigitized(
        pdk,
        device="pfet",
        numcols=1,
        n_devices=5,
        with_substrate_tap=False,
        with_tie=False,
        width=Width,
        length=Length,
    )

    currm_middle = top_level << currm_middle
    currm_middle.name = "currm_middle"

    currm_middle_ref = prec_ref_center(currm_middle)
    currm_middle_ref.move(top_ref.center).movey(
        evaluate_bbox(currm_bottom_ref)[1] + 2 * n_well_sep
    )
    top_level.add(currm_middle_ref)

    top_level.add_ports(currm_middle_ref.get_ports_list(), prefix="currm_middle_")

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # TOP CURRENT MIRRORS
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    currm_top = n_transistor_interdigitized(
        pdk,
        device="pfet",
        numcols=1,
        n_devices=4,
        with_substrate_tap=False,
        with_tie=False,
        width=Width,
        length=Length,
    )

    currm_top = top_level << currm_top
    currm_top.name = "currm_top"

    currm_top_ref = prec_ref_center(currm_top)
    currm_top_ref.move(currm_middle.center).movey(
        evaluate_bbox(currm_middle_ref)[1] + 2 * n_well_sep
    )
    top_level.add(currm_top_ref)

    top_level.add_ports(currm_top_ref.get_ports_list(), prefix="currm_top_")

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # INTERCONNECTIONS
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    bottomA_source_via = top_level << viam2m3
    bottomA_source_via.move(
        top_level.ports[f"currm_bottom_A_0_source_W"].center
    ).movex(-dist_DS)

    top_level << straight_route(
        pdk,
        bottomA_source_via.ports["top_met_W"],
        top_level.ports[f"currm_bottom_A_0_source_E"],
        glayer1="met2",
        glayer2="met2",
    )

    middleA_drain_via = top_level << viam2m3
    middleA_drain_via.move(
        top_level.ports[f"currm_middle_A_0_drain_W"].center
    ).movex(-dist_DS)

    top_level << straight_route(
        pdk,
        middleA_drain_via.ports["top_met_W"],
        top_level.ports[f"currm_middle_A_0_drain_E"],
        glayer1="met2",
        glayer2="met2",
    )

    bottom_middle_route = straight_route(
        pdk,
        bottomA_source_via.ports["top_met_S"],
        middleA_drain_via.ports["top_met_N"],
        glayer1="met3",
        glayer2="met3",
    )

    bottom_middle_ref = top_level << bottom_middle_route
    bottom_middle_route.name = "bottomAsource_to_middleAdrain"

    middleA_gate_via = top_level << viam2m3
    middleA_gate_via.move(
        (bottom_middle_ref.center[0], top_level.ports[f"currm_middle_A_0_gate_W"].center[1])
    )

    top_level << straight_route(
        pdk,
        middleA_gate_via.ports["top_met_W"],
        top_level.ports[f"currm_middle_A_0_gate_W"],
        glayer1="met2",
        glayer2="met2",
    )

    letters = ["B", "C", "D", "E"]
    for letter in letters:
        bottomL_source_via = top_level << viam2m3
        bottomL_source_via.move(
            top_level.ports[f"currm_bottom_{letter}_0_source_W"].center
        ).movex(dist_DS)

        middleL_drain_via = top_level << viam2m3
        middleL_drain_via.move(
            top_level.ports[f"currm_middle_{letter}_0_drain_W"].center
        ).movex(dist_DS)

        top_level << straight_route(
            pdk,
            bottomL_source_via.ports["top_met_S"],
            middleL_drain_via.ports["top_met_N"],
            glayer1="met3",
            glayer2="met3",
        )

    middleE_gate_via = top_level << viam2m3
    middleE_gate_via.move(
        top_level.ports[f"currm_middle_E_0_gate_W"].center
    ).movex(dist_GS + 1.5 * dist_DS)

    top_level << straight_route(
        pdk,
        middleE_gate_via.ports["top_met_E"],
        top_level.ports[f"currm_middle_E_0_gate_W"],
        glayer1="met2",
        glayer2="met2",
    )

    topD_drain_via = top_level << viam2m3
    topD_drain_via.move(
        (middleE_gate_via.center[0], top_level.ports[f"currm_top_D_0_drain_W"].center[1])
    )

    top_level << straight_route(
        pdk,
        topD_drain_via.ports["top_met_E"],
        top_level.ports[f"currm_top_D_0_drain_W"],
        glayer1="met2",
        glayer2="met2",
    )

    middle_top_route = straight_route(
        pdk,
        middleE_gate_via.ports["top_met_S"],
        topD_drain_via.ports["top_met_N"],
        glayer1="met3",
        glayer2="met3",
    )

    middle_top_ref = top_level << middle_top_route
    middle_top_route.name = "middleEgate_to_topdrains"

    topA_drain_via = top_level << viam2m3
    topA_drain_via.move(
        (middle_top_ref.center[0], top_level.ports[f"currm_top_A_0_drain_W"].center[1])
    )

    topB_drain_via = top_level << viam2m3
    topB_drain_via.move(
        (middle_top_ref.center[0], top_level.ports[f"currm_top_B_0_drain_W"].center[1])
    )

    topC_drain_via = top_level << viam2m3
    topC_drain_via.move(
        (middle_top_ref.center[0], top_level.ports[f"currm_top_C_0_drain_W"].center[1])
    )

    top_level << straight_route(
        pdk,
        top_level.ports[f"currm_top_A_0_drain_E"],
        topA_drain_via.ports["top_met_E"],
        glayer2="met2",
    )

    top_level << straight_route(
        pdk,
        top_level.ports[f"currm_top_B_0_drain_E"],
        topB_drain_via.ports["top_met_E"],
        glayer2="met2",
    )

    top_level << straight_route(
        pdk,
        top_level.ports[f"currm_top_C_0_drain_E"],
        topC_drain_via.ports["top_met_E"],
        glayer2="met2",
    )

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # TAP RING
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    snap = pdk.snap_to_2xgrid

    core = top_level.copy()  # so we don't mutate while measuring
    core_flat = core.flatten()  # include all placed children

    xmin, xmax = core_flat.xmin, core_flat.xmax
    ymin, ymax = core_flat.ymin, core_flat.ymax

    core_w = xmax - xmin
    core_h = ymax - ymin

    cx = snap((xmin + xmax) / 2)
    cy = snap((ymin + ymax) / 2)

    # Adding tapring
    if with_tie:
        well, sdglayer = "nwell", "n+s/d"
        tap_separation = max(
            maxmet_sep, pdk.get_grule("active_diff", "active_tap")["min_separation"]
        )
        tap_separation += pdk.get_grule(sdglayer, "active_tap")["min_enclosure"]
        tap_encloses = (
            (snap(4 * tap_separation + core_w)),
            (snap(4 * tap_separation + core_h)),
        )
        tie_ref = top_level << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer=sdglayer,
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        tie_ref.move((cx, cy))
        top_level.add_ports(tie_ref.get_ports_list(), prefix="welltie_")

    # add pwell
    top_level.add_padding(
        default=pdk.get_grule(well, "active_tap")["min_enclosure"],
        layers=[pdk.get_glayer(well)],
    )
    top_level = add_ports_perimeter(top_level, layer=pdk.get_glayer(well), prefix="well_")

    # add the substrate tap if specified
    if with_substrate_tap:
        substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")[
            "min_separation"
        ]
        substrate_tap_enclosure = (
            (snap(4 * substrate_tap_separation + core_w)),
            (snap(4 * substrate_tap_separation + core_h)),
        )
        ringtoadd = tapring(
            pdk,
            enclosed_rectangle=substrate_tap_enclosure,
            sdlayer="p+s/d",
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        substrate_tap_ring_ref = top_level << ringtoadd
        substrate_tap_ring_ref.move((cx, cy))
        top_level.add_ports(
            substrate_tap_ring_ref.get_ports_list(), prefix="substrate_tap_"
        )

    # Connect well ties to well
    try:
        top_level << straight_route(
            pdk,
            top_level.ports["currm_bottom_A_0_dummy_L_gsdcon_top_met_W"],
            top_level.ports["welltie_W_top_met_W"],
            glayer2="met1",
        )

        top_level << straight_route(
            pdk,
            top_level.ports[
                f"currm_bottom_E_{num_cols - 1}_dummy_R_gsdcon_top_met_E"
            ],
            top_level.ports["welltie_E_top_met_E"],
            glayer2="met1",
        )

        top_level << straight_route(
            pdk,
            top_level.ports["currm_middle_A_0_dummy_L_gsdcon_top_met_W"],
            top_level.ports["welltie_W_top_met_W"],
            glayer2="met1",
        )

        top_level << straight_route(
            pdk,
            top_level.ports[
                f"currm_middle_E_{num_cols - 1}_dummy_R_gsdcon_top_met_E"
            ],
            top_level.ports["welltie_E_top_met_E"],
            glayer2="met1",
        )

        top_level << straight_route(
            pdk,
            top_level.ports["currm_top_A_0_dummy_L_gsdcon_top_met_W"],
            top_level.ports["welltie_W_top_met_W"],
            glayer2="met1",
        )

        top_level << straight_route(
            pdk,
            top_level.ports[
                f"currm_top_D_{num_cols - 1}_dummy_R_gsdcon_top_met_E"
            ],
            top_level.ports["welltie_E_top_met_E"],
            glayer2="met1",
        )

    except KeyError:
        pass

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # CONNECT SOURCES TO VDD
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    dist_ring = abs(
        top_level.ports["welltie_W_top_met_W"].center[0]
        - top_level.ports["welltie_W_top_met_E"].center[0]
    ) / 2

    letters = ["A", "B", "C", "D", "E"]
    for letter in letters:
        middleL_source_via = top_level << viam1m2
        middleL_source_via.move(
            (
                top_level.ports["welltie_W_top_met_W"].center[0],
                top_level.ports[f"currm_middle_{letter}_0_source_W"].center[1],
            )
        ).movex(dist_ring)

        top_level << straight_route(
            pdk,
            top_level.ports[f"currm_middle_{letter}_0_source_W"],
            middleL_source_via.ports["top_met_W"],
            glayer2="met2",
        )

        if letter != "E":
            topL_source_via = top_level << viam1m2
            topL_source_via.move(
                (
                    top_level.ports["welltie_W_top_met_W"].center[0],
                    top_level.ports[f"currm_top_{letter}_0_source_W"].center[1],
                )
            ).movex(dist_ring)

            top_level << straight_route(
                pdk,
                top_level.ports[f"currm_top_{letter}_0_source_W"],
                topL_source_via.ports["top_met_W"],
                glayer2="met2",
            )

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # CONNECT GATES TO ENABLE AND INPUT
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    letters = ["A", "B", "C", "D", "E"]
    for letter in letters:
        bottomL_gate_input_via = top_level << viam1m2
        bottomL_gate_input_via.move(
            (
                top_level.ports["welltie_W_top_met_W"].center[0],
                top_level.ports[f"currm_bottom_{letter}_0_gate_W"].center[1],
            )
        ).movex(dist_ring - 2 * dist_DS)
        top_level.add_ports(bottomL_gate_input_via.get_ports_list(), prefix=f"IN_{letter}_")

        top_level << straight_route(
            pdk,
            top_level.ports[f"currm_bottom_{letter}_0_gate_W"],
            bottomL_gate_input_via.ports["top_met_W"],
            glayer2="met2",
        )

        if letter != "E":
            topL_gate_enable_via = top_level << viam1m2
            topL_gate_enable_via.move(
                (
                    top_level.ports["welltie_W_top_met_W"].center[0],
                    top_level.ports[f"currm_top_{letter}_0_gate_W"].center[1],
                )
            ).movex(dist_ring - 2 * dist_DS)
            top_level.add_ports(topL_gate_enable_via.get_ports_list(), prefix=f"EN_{letter}_")

            top_level << straight_route(
                pdk,
                top_level.ports[f"currm_top_{letter}_0_gate_W"],
                topL_gate_enable_via.ports["top_met_W"],
                glayer2="met2",
            )

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # CONNECT BOTTOM DRAINS TO OTHER STAGES
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    for letter in letters:
        if letter != "A":
            bottomL_drain_via = top_level << viam1m2
            bottomL_drain_via.move(
                (
                    top_level.ports["welltie_E_top_met_E"].center[0],
                    top_level.ports[f"currm_bottom_{letter}_0_drain_E"].center[1],
                )
            ).movex(-dist_ring + 2 * dist_DS)
            top_level.add_ports(bottomL_drain_via.get_ports_list(), prefix=f"OUT_{letter}_")

            top_level << straight_route(
                pdk,
                top_level.ports[f"currm_bottom_{letter}_0_drain_E"],
                bottomL_drain_via.ports["top_met_W"],
                glayer2="met2",
            )

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # CONNECTING INPUTS AND EN
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    top_level << straight_route(
        pdk, top_level.ports[f"IN_A_top_met_N"], top_level.ports["IN_B_top_met_S"], glayer2="met1"
    )
    top_level << straight_route(
        pdk, top_level.ports[f"IN_B_top_met_N"], top_level.ports[f"IN_C_top_met_S"], glayer2="met1"
    )
    top_level << straight_route(
        pdk, top_level.ports[f"IN_C_top_met_N"], top_level.ports[f"IN_D_top_met_S"], glayer2="met1"
    )
    top_level << straight_route(
        pdk, top_level.ports[f"IN_D_top_met_N"], top_level.ports[f"IN_E_top_met_S"], glayer2="met1"
    )

    top_level << straight_route(
        pdk, top_level.ports[f"EN_A_top_met_N"], top_level.ports[f"EN_B_top_met_S"], glayer2="met1"
    )
    top_level << straight_route(
        pdk, top_level.ports[f"EN_B_top_met_N"], top_level.ports[f"EN_C_top_met_S"], glayer2="met1"
    )
    top_level << straight_route(
        pdk, top_level.ports[f"EN_C_top_met_N"], top_level.ports[f"EN_D_top_met_S"], glayer2="met1"
    )
    

    stages = ["bottom", "middle"]
    letters = ["A", "B", "C", "D", "E"]

    for stage in stages:
        for letter in letters:
            default_gate_via_x = (
                top_level.ports[f"currm_{stage}_{letter}_0_gate_W"].center[0] + dist_GS
            )
            for let in [l for l in letters if l != letter]:
                gate_via = top_level << poly_to_met2_via
                gate_via.move(
                    (default_gate_via_x, top_level.ports[f"currm_{stage}_{let}_0_gate_W"].center[1])
                )

    for letter in letters[:-1]:
        default_gate_via_x = (
            top_level.ports[f"currm_top_{letter}_0_gate_W"].center[0] + dist_GS
        )
        for let in [l for l in letters[:-1] if l != letter]:
            gate_via = top_level << poly_to_met2_via
            gate_via.move(
                (default_gate_via_x, top_level.ports[f"currm_top_{let}_0_gate_W"].center[1])
            )

    top_level = component_snap_to_grid(rename_ports_by_orientation(top_level))

    top_level.info["netlist"] = generate_input_stage_netlist(
        pdk=pdk,
        prefix="INPUT",
        instance_name=top_level.name,
        CM_size=(Width, Length, num_cols, fingers),  # (width, length, multipliers, fingers)
        transistor_type=type,
        source_net_in="VIN",  # Input drain connected to IREF
        gate_net_en="EN",  # Auxiliary node
        drain_net_out_vin="VOUT_VIN",
        drain_net_out_vcm="VOUT_VCM",
        drain_net_out_bcm="VOUT_BCM",
        drain_net_out_ccm="VOUT_CCM",
        bulk_net="VSS" if type.lower() == "nfet" else "VDD",
        subckt_only=True,
        show_netlist=show_netlist,
    )

    if add_labels:
        return add_cm_labels(top_level, pdk)
    else:
        return top_level


def add_cm_labels(cm_in: Component, pdk: MappedPDK) -> Component:
    cm_in.unlock()

    psize = (0.35, 0.35)
    move_info = []

    # VIN
    vinlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    vinlabel.add_label(text="VIN", layer=pdk.get_glayer("met2_label"))
    move_info.append((vinlabel, cm_in.ports["IN_A_top_met_N"], None))

    # EN
    venlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    venlabel.add_label(text="EN", layer=pdk.get_glayer("met2_label"))
    move_info.append((venlabel, cm_in.ports["EN_A_top_met_N"], None))

    # VOUT VCM
    voutvcmlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutvcmlabel.add_label(text="VOUT_VCM", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutvcmlabel, cm_in.ports["OUT_B_top_met_N"], None))

    # VOUT BCM
    voutbcmlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutbcmlabel.add_label(text="VOUT_BCM", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutbcmlabel, cm_in.ports["OUT_C_top_met_N"], None))

    # VOUT CCM
    voutccmlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutccmlabel.add_label(text="VOUT_CCM", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutccmlabel, cm_in.ports["OUT_D_top_met_N"], None))

    # VOUT VIN
    voutvinlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutvinlabel.add_label(text="VOUT_VIN", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutvinlabel, cm_in.ports["OUT_E_top_met_N"], None))

    # VDD (well tie)
    vddlabel = rectangle(layer=pdk.get_glayer("met1_pin"), size=psize, centered=True).copy()
    vddlabel.add_label(text="VDD", layer=pdk.get_glayer("met1_label"))
    move_info.append((vddlabel, cm_in.ports["welltie_N_top_met_N"], None))

    for comp, prt, alignment in move_info:
        alignment = ("c", "b") if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        cm_in.add(compref)

    return cm_in.flatten()



if __name__ == "__main__":
    selected_pdk = gf180
    comp = input_stage(
        selected_pdk, num_cols=1, Width=10, Length=2, with_substrate_tap=False, show_netlist=False
    )
    
    comp.name = "INPUT_STAGE"
    comp.show()
    # Write the current mirror layout to a GDS file
    comp.write_gds("GDS/input_stage.gds")

    # Generate the netlist for the current mirror
    print(comp.info["netlist"].generate_netlist())

    # DRC Checks
    drc_result = selected_pdk.drc_magic(comp, comp.name, output_file=Path("DRC/"))

    # LVS Checks
    netgen_lvs_result = selected_pdk.lvs_netgen(
        comp, comp.name, output_file_path=Path("LVS/"), copy_intermediate_files=True
    )