from glayout import MappedPDK, gf180
from glayout import nmos, pmos, tapring,via_stack, multiplier
from n_fets_fingers import n_transistor_clustered

from glayout.spice.netlist import Netlist
from glayout.routing import c_route,L_route,straight_route

from gdsfactory.cell import cell
from gdsfactory.component import Component, copy
from gdsfactory.components.rectangle import rectangle
from gdsfactory.routing.route_quad import route_quad
from gdsfactory.routing.route_sharp import route_sharp

from gdsfactory.component import Component
from gdsfactory.component_reference import ComponentReference
from gdsfactory.cell import cell
from gdsfactory import Component
from gdsfactory.components import text_freetype, rectangle

from glayout.util.comp_utils import evaluate_bbox, prec_center, align_comp_to_port, prec_ref_center,movex,movey
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.util.port_utils import set_port_orientation, rename_ports_by_orientation, create_private_ports, add_ports_perimeter, get_orientation
from itertools import product

###### Only Required for IIC-OSIC Docker
import os
import subprocess
from pathlib import Path
# Run a shell, source .bashrc, then printenv
cmd = 'bash -c "source ~/.bashrc && printenv"'
result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
env_vars = {}
for line in result.stdout.splitlines():
    if '=' in line:
        key, value = line.split('=', 1)
        env_vars[key] = value

# Now, update os.environ with these
os.environ.update(env_vars)
###############################################################################
from typing import Optional, Union
import time

def generate_biased_base_netlist(
    pdk: MappedPDK,
    prefix : str,
    CM_size: tuple[float, float, int, int],  # (width, length, multipliers, fingers)
    drain_net_in: str,
    drain_net_out: str,
    transistor_type: str = "nfet",
    bulk_net: str = None,
    dummy: bool = True,
    subckt_only: bool = False,
    show_netlist: bool = False,
    **kwargs,
) -> Netlist:
    """Generate a netlist for a current mirror."""

    if bulk_net is None:
        bulk_net = "VDD" if transistor_type.lower() == "pfet" else "VSS"

    width = CM_size[0]
    length = CM_size[1]
    multipliers = CM_size[2]
    fingers = CM_size[3]  # Number of fingers of the interdigitized fets
    mtop = fingers if subckt_only else 1
    # mtop = multipliers * 2 if dummy else multipliers  # Double the multiplier to account for the dummies

    model_name = pdk.models[transistor_type.lower()]

    circuit_name = prefix
    # Take only unique NET names
    nodes = [drain_net_in, drain_net_out, bulk_net]

    source_netlist = f".subckt {circuit_name} {' '.join(nodes)}\n"

    # Proposed ground connection (commented)
    # source_netlist += f"V{proposed_ground}1 ({proposed_ground} {bulk_net}) 0\n"

    # Generating four transistors (one on each side):
    top_bottomleft_net = "VTBL"
    top_bottomright_net = "VTBR"

    source_netlist += (
        f"X{prefix}_A {drain_net_in} {drain_net_in} {top_bottomleft_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )
    source_netlist += (
        f"X{prefix}_B {top_bottomleft_net} {top_bottomleft_net} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )
    source_netlist += (
        f"X{prefix}_C {drain_net_out} {drain_net_in} {top_bottomright_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={1}\n"
    )
    source_netlist += (
        f"X{prefix}_D {top_bottomright_net} {top_bottomleft_net} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={1}\n"
    )

    if dummy:
        source_netlist += (
            f"X{prefix}_DUMMY {bulk_net} {bulk_net} {bulk_net} {bulk_net} "
            f"{model_name} l={length} w={width} m={4}\n"
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
   
# @cell
def biased_base(
        pdk: MappedPDK,
        width:  tuple[float,float] = (1,1),
        length: Optional[float] = None,
        fingers: tuple[int,int] = (2,2),
        multipliers: tuple[int,int] = (1,1),
        device: Optional[str] = 'nfet',
        plus_minus_seperation: float = 0,
        with_substrate_tap: Optional[bool] = False,
        with_tie: Optional[bool] = True,
        with_dummy: Union[bool, tuple[bool, bool]] = True,
        tie_layers: tuple[str,str]=("met2","met1"),
        show_netlist: Optional[bool] = False,
        add_labels: Optional[bool] = False,
        **kwargs
    ) -> Component:
    """An instantiable self biased casoded current mirror that returns a Component object."""
    
    pdk.activate()
    maxmet_sep = pdk.util_max_metal_seperation()
    psize=(0.35,0.35)
    
    # Create the current mirror component
    top_level = Component(name="Biased Base")
    length = length if length is not None else pdk.get_grule('poly')['min_width']
    top_ref = prec_ref_center(top_level)

    if multipliers[1] > multipliers[0]:
        multipliers = (multipliers[1],multipliers[0])

    # Create the interdigitized fets
    if device.lower() == "pfet" or device.lower() == "pmos":
        currm1 = n_transistor_clustered(
            pdk,
            device="pfet",
            numcols=fingers[0],
            n_devices=1,
            width=width[0],
            # gate_route_extension=0,
            length=length,
            fingers=1,
            dummy=(True, 0),
            with_substrate_tap=False,
            with_tie=False,
        )
        currm2 = n_transistor_clustered(
            pdk,
            device="pfet",
            numcols=fingers[1],
            n_devices=1,
            width=width[0],
            # gate_route_extension=0,
            length=length,
            fingers=1,
            dummy=(0, True),
            with_substrate_tap=False,
            with_tie=False,
        )
        well, sdglayer = "nwell", "n+s/d"
    elif device.lower() == "nfet" or device.lower() == "nmos":
        currm1 = n_transistor_clustered(
            pdk,
            device="nfet",
            numcols=fingers[0],
            n_devices=1,
            width=width[0],
            # gate_route_extension=0,
            length=length,
            fingers=1,
            dummy=(True, 0),
            with_substrate_tap=False,
            with_tie=False,
        )
        currm2 = n_transistor_clustered(
            pdk,
            device="nfet",
            numcols=fingers[1],
            n_devices=1,
            width=width[0],
            # gate_route_extension=0,
            length=length,
            fingers=1,
            dummy=(0, True),
            with_substrate_tap=False,
            with_tie=False,
        )
        well, sdglayer = "pwell", "p+s/d"
    else:
        raise ValueError("type must be either nfet or pfet")
    
    # -------------------------------------------------------------------------
    # BOTTOM CURRENT MIRRORS
    # -------------------------------------------------------------------------
    viam1m2 = via_stack(pdk, glayer1="met1", glayer2="met2", centered=True)
    viam2m3 = via_stack(pdk, glayer1="met2", glayer2="met3", centered=True)

    core1 = currm1.copy().flatten()   # so we don't mutate while measuring

    xmin1, xmax1 = core1.xmin, core1.xmax
    ymin1, ymax1 = core1.ymin, core1.ymax

    core2 = currm2.copy().flatten()   # so we don't mutate while measuring

    xmin2, xmax2 = core2.xmin, core2.xmax
    ymin2, ymax2 = core2.ymin, core2.ymax

    sep = pdk.get_grule(sdglayer)["min_separation"]

    a_botl = prec_ref_center(currm1)
    top_level.add(a_botl)
    a_botl.move(top_ref.center)
    top_level.add_ports(a_botl.get_ports_list(), prefix="bottom_left_")

    b_botr = prec_ref_center(currm2)
    top_level.add(b_botr)
    # b_botr.move(top_ref.center).movex(evaluate_bbox(a_botl)[0]+maxmet_sep)
    b_botr.move(a_botl.center).movex((xmax1 - xmin1)/2 + (xmax2 - xmin2)/2 + 2*maxmet_sep + 2*sep)
    top_level.add_ports(b_botr.get_ports_list(), prefix="bottom_right_")

    # Connect gates of the two bottom blocks
    top_level << straight_route(pdk, top_level.ports["bottom_left_A_gate_E"], top_level.ports["bottom_right_A_gate_W"], glayer1="met2", glayer2="met2")

    dist_DS = (
        abs(
            top_level.ports[f"bottom_left_A_0_drain_E"].center[0]
            - top_level.ports[f"bottom_left_A_0_drain_W"].center[0]
        )
        / 2
    )

    dist_GS = (
        abs(
            top_level.ports[f"bottom_left_A_0_gate_E"].center[0]
            - top_level.ports[f"bottom_left_A_0_gate_W"].center[0]
        )
        / 2
    )

    # -------------------------------------------------------------------------
    # TOP CURRENT MIRRORS
    # -------------------------------------------------------------------------
    
    a_topl = prec_ref_center(currm1)
    top_level.add(a_topl)
    a_topl.move(a_botl.center).movey((ymax1 - ymin1) + 2*maxmet_sep + 2*sep)
    top_level.add_ports(a_topl.get_ports_list(), prefix="top_left_")

    b_topr = prec_ref_center(currm2)
    top_level.add(b_topr)
    b_topr.move(a_topl.center).movex((xmax1 - xmin1)/2 + (xmax2 - xmin2)/2 + 2*maxmet_sep + 2*sep)
    top_level.add_ports(b_topr.get_ports_list(), prefix="top_right_")

    # Connect gates of the two top blocks
    top_level << straight_route(pdk, top_level.ports["top_left_A_gate_E"], top_level.ports["top_right_A_gate_W"], glayer1="met2", glayer2="met2")

    # -------------------------------------------------------------------------
    # CONNECT BOTTOM AND TOP BLOCKS
    # -------------------------------------------------------------------------

    dist_SS = (
                abs(
                    top_level.ports[f"top_left_A_{0}_drain_W"].center[0]
                    - top_level.ports[f"top_left_A_{1}_source_E"].center[0]
                )
            )

    if device == "nfet":
        for idx in range(fingers[0]):
            topS = top_level << viam2m3
            topS.move(top_level.ports[f"top_left_A_{idx}_source_W"].center).movex(dist_DS)

            bottomD = top_level << viam2m3
            bottomD.move(top_level.ports[f"bottom_left_A_{idx}_drain_W"].center).movex(dist_DS)

            # Connect drain and gate of the left blocks
            if idx != fingers[0]-1:  # Skip last finger to avoid shorting the gate to drain
                top_drain_to_gate = top_level << viam2m3
                top_drain_to_gate.move(top_level.ports[f"top_left_A_{idx}_drain_W"].center).movex(dist_SS/2)

                top_gate = top_level << viam2m3
                top_gate.move((top_drain_to_gate.center[0], top_level.ports[f"top_left_A_{idx}_gate_W"].center[1]))

                top_level << straight_route(pdk, top_drain_to_gate.ports["top_met_S"], top_gate.ports["top_met_N"], glayer1="met3", glayer2="met3")

            bottom_drain_to_gate = top_level << viam2m3
            bottom_drain_to_gate.move(top_level.ports[f"bottom_left_A_{idx}_gate_W"].center).movex(dist_GS)

            top_level << straight_route(pdk, topS.ports["top_met_S"], bottom_drain_to_gate.ports["top_met_N"], glayer1="met3", glayer2="met3")

        for idx in range(fingers[1]):
            topS = top_level << viam2m3
            topS.move(top_level.ports[f"top_right_A_{idx}_source_W"].center).movex(dist_DS)

            bottomD = top_level << viam2m3
            bottomD.move(top_level.ports[f"bottom_right_A_{idx}_drain_W"].center).movex(dist_DS)
            top_level << straight_route(pdk, topS.ports["top_met_S"], bottomD.ports["top_met_N"], glayer1="met3", glayer2="met3")
    elif device == "pfet":

        for idx in range(fingers[0]):
            topD = top_level << viam2m3
            topD.move(top_level.ports[f"top_left_A_{idx}_drain_W"].center).movex(dist_DS)

            bottomS = top_level << viam2m3
            bottomS.move(top_level.ports[f"bottom_left_A_{idx}_source_W"].center).movex(dist_DS)
            top_level << straight_route(pdk, topD.ports["top_met_S"], bottomS.ports["top_met_N"], glayer1="met3", glayer2="met3")

            # Connect drain and gate of the left blocks
            if idx != fingers[0]-1:  # Skip last finger to avoid shorting the gate to drain
                top_drain_to_gate = top_level << viam2m3
                top_drain_to_gate.move(top_level.ports[f"bottom_left_A_{idx}_drain_W"].center).movex(dist_SS/2)

                top_gate = top_level << viam2m3
                top_gate.move((top_drain_to_gate.center[0], top_level.ports[f"bottom_left_A_{idx}_gate_W"].center[1]))

                top_level << straight_route(pdk, top_drain_to_gate.ports["top_met_S"], top_gate.ports["top_met_N"], glayer1="met3", glayer2="met3")

            bottom_drain_to_gate = top_level << viam2m3
            bottom_drain_to_gate.move(top_level.ports[f"top_left_A_{idx}_gate_W"].center).movex(dist_GS)

            if idx == 0:
                top_level.add_ports(bottom_drain_to_gate.get_ports_list(), prefix=f"GATE_CONN_")

        for idx in range(fingers[1]):
            topD = top_level << viam2m3
            topD.move(top_level.ports[f"top_right_A_{idx}_drain_W"].center).movex(dist_DS)

            bottomS = top_level << viam2m3
            bottomS.move(top_level.ports[f"bottom_right_A_{idx}_source_W"].center).movex(dist_DS)
            top_level << straight_route(pdk, topD.ports["top_met_S"], bottomS.ports["top_met_N"], glayer1="met3", glayer2="met3")

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
            sdlayer=sdglayer,
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
            top_level.ports["top_left_A_0_dummy_L_gsdcon_top_met_W"],
            top_level.ports["welltie_W_top_met_W"],
            glayer2="met1",
        )

        top_level << straight_route(
            pdk,
            top_level.ports[
                f"top_right_A_0_dummy_R_gsdcon_top_met_E"
            ],
            top_level.ports["welltie_E_top_met_E"],
            glayer2="met1",
        )

        top_level << straight_route(
            pdk,
            top_level.ports["bottom_left_A_0_dummy_L_gsdcon_top_met_W"],
            top_level.ports["welltie_W_top_met_W"],
            glayer2="met1",
        )

        top_level << straight_route(
            pdk,
            top_level.ports[
                f"bottom_right_A_0_dummy_R_gsdcon_top_met_E"
            ],
            top_level.ports["welltie_E_top_met_E"],
            glayer2="met1",
        )

    except KeyError:
        pass

    # -------------------------------------------------------------------------
    # CONNECT SOURCES TO TIE RING
    # -------------------------------------------------------------------------

    dist_ring = (
        abs(
            top_level.ports["welltie_W_top_met_W"].center[0]
            - top_level.ports["welltie_W_top_met_E"].center[0]
        )
        / 2
    )

    if device == "nfet":
        bottomA_source_via = top_level << viam1m2
        bottomA_source_via.move(
            (top_level.ports["welltie_W_top_met_E"].center[0], top_level.ports["bottom_left_A_0_source_W"].center[1])
        ).movex(-dist_ring)

        top_level << straight_route(
            pdk,
            top_level.ports["bottom_left_A_0_source_W"],
            bottomA_source_via.ports["top_met_W"],
            glayer2="met2",
        )

        bottomA_source_via = top_level << viam1m2
        bottomA_source_via.move(
            (top_level.ports["welltie_E_top_met_E"].center[0], top_level.ports["bottom_right_A_0_source_E"].center[1])
        ).movex(-dist_ring)

        top_level << straight_route(
            pdk,
            top_level.ports["bottom_right_A_0_source_E"],
            bottomA_source_via.ports["top_met_W"],
            glayer2="met2",
        )
    elif device == "pfet":
        bottomA_source_via = top_level << viam1m2
        bottomA_source_via.move(
            (top_level.ports["welltie_W_top_met_E"].center[0], top_level.ports["top_left_A_0_source_W"].center[1])
        ).movex(-dist_ring)

        top_level << straight_route(
            pdk,
            top_level.ports["top_left_A_0_source_W"],
            bottomA_source_via.ports["top_met_W"],
            glayer2="met2",
        )

        bottomA_source_via = top_level << viam1m2
        bottomA_source_via.move(
            (top_level.ports["welltie_E_top_met_E"].center[0], top_level.ports["top_right_A_0_source_E"].center[1])
        ).movex(-dist_ring) 

        top_level << straight_route(
            pdk,
            top_level.ports["top_right_A_0_source_E"],
            bottomA_source_via.ports["top_met_W"],
            glayer2="met2",
        )

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # CONNECT DRAINS TO OTHER STAGES
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    if device == "nfet":
        in_via = top_level << viam1m2
        in_via.move((top_level.ports["welltie_W_top_met_W"].center[0], top_level.ports["top_left_A_0_drain_W"].center[1])).movex(-dist_DS)
        top_level.add_ports(in_via.get_ports_list(), prefix=f"IN_")

        out_via = top_level << viam1m2
        out_via.move((top_level.ports["welltie_E_top_met_E"].center[0], top_level.ports["top_right_A_0_drain_E"].center[1])).movex(dist_DS)
        top_level.add_ports(out_via.get_ports_list(), prefix=f"OUT_")
        
        top_level << straight_route(pdk, top_level.ports["IN_top_met_E"], top_level.ports["top_left_A_0_drain_W"], glayer1="met2", glayer2="met2")
        top_level << straight_route(pdk, top_level.ports["OUT_top_met_W"], top_level.ports["top_right_A_0_drain_E"], glayer1="met2", glayer2="met2")

    else:  # pfet
        in_via = top_level << viam1m2
        in_via.move((top_level.ports["welltie_W_top_met_W"].center[0], top_level.ports["bottom_left_A_0_drain_W"].center[1])).movex(-dist_DS)
        top_level.add_ports(in_via.get_ports_list(), prefix=f"IN_")

        out_via = top_level << viam1m2
        out_via.move((top_level.ports["welltie_E_top_met_E"].center[0], top_level.ports["bottom_right_A_0_drain_E"].center[1])).movex(dist_DS)
        top_level.add_ports(out_via.get_ports_list(), prefix=f"OUT_")

        top_level << straight_route(pdk, top_level.ports["IN_top_met_E"], top_level.ports["bottom_left_A_0_drain_W"], glayer1="met2", glayer2="met2")
        top_level << straight_route(pdk, top_level.ports["OUT_top_met_W"], top_level.ports["bottom_right_A_0_drain_E"], glayer1="met2", glayer2="met2")

    # -------------------------------------------------------------------------
    # ADD IN/OUT PORTS
    # -------------------------------------------------------------------------
    

    top_level = component_snap_to_grid(rename_ports_by_orientation(top_level))

    top_level.info["netlist"] = generate_biased_base_netlist(
        pdk=pdk,
        prefix="BIASED_BASE",
        CM_size=(width[0], length, 1, fingers[0]),  # (width, length, multipliers, fingers)
        transistor_type=device,
        drain_net_in="VIN",  # Input drain connected to IREF
        drain_net_out="VOUT",
        bulk_net="VSS" if device.lower() == "nfet" else "VDD",
        subckt_only=True,
        show_netlist=show_netlist,
    )

    if add_labels:
        return add_cm_labels(top_level, pdk, bulk="VDD" if device.lower() == "pfet" else "VSS")
    else:
        return top_level


def add_cm_labels(cm_in: Component, pdk: MappedPDK, bulk: str) -> Component:
    cm_in.unlock()

    psize = (0.35, 0.35)
    move_info = []

    # VIN
    vinlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    vinlabel.add_label(text="VIN", layer=pdk.get_glayer("met2_label"))
    move_info.append((vinlabel, cm_in.ports["IN_top_met_N"], None))

    # VOUT 
    voutlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutlabel.add_label(text="VOUT", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutlabel, cm_in.ports["OUT_top_met_N"], None))

    # BULK (well tie)
    vddlabel = rectangle(layer=pdk.get_glayer("met1_pin"), size=psize, centered=True).copy()
    vddlabel.add_label(text=bulk, layer=pdk.get_glayer("met1_label"))
    move_info.append((vddlabel, cm_in.ports["welltie_N_top_met_N"], None))

    for comp, prt, alignment in move_info:
        alignment = ("c", "b") if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        cm_in.add(compref)

    return cm_in.flatten()

if __name__ == "__main__":
    selected_pdk = gf180

    comp =biased_base(selected_pdk,width=(8,8), length=1, multipliers=(1,1),fingers=(10,1), device="pfet", with_tie=True, add_labels=True, show_netlist=True)
    # comp.pprint_ports()
    # comp =add_lvcm_labels(comp,selected_pdk)
    comp.name = "BB"
    comp.show()

    comp.write_gds("./BB.gds")

    drc_result = selected_pdk.drc_magic(comp, comp.name, output_file=Path("DRC/"))
    
        
    netgen_lvs_result = selected_pdk.lvs_netgen(
        comp, comp.name, output_file_path=Path("LVS/"), copy_intermediate_files=True
    )
