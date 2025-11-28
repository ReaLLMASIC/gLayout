from pathlib import Path
from typing import Optional, Union, ClassVar, Any, Literal, Iterable, TypedDict

import os
import subprocess

from glayout import MappedPDK, sky130, gf180
from glayout import nmos, pmos, tapring, via_stack
from glayout.placement.two_transistor_interdigitized import (
    two_nfet_interdigitized,
    two_pfet_interdigitized,
)
from n_fets_interdigitized import n_transistor_interdigitized
from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory.components import text_freetype, rectangle
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

# ------ Only Required for IIC-OSIC Docker ------
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
def generate_current_mirror_netlist(
    pdk: MappedPDK,
    prefix : str,
    instance_name: str,
    CM_size: tuple[float, float, int],  # (width, length, multipliers)
    drain_net_in: str,
    drain_net_out: str,
    source_net_in: str,
    source_net_out: str,
    gate_net: str,
    transistor_type: str = "nfet",
    bulk_net: str = None,
    proposed_ground: str = None,  # Proposed ground net
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
    mtop = multipliers * fingers if subckt_only else 1
    # mtop = multipliers * 2 if dummy else multipliers  # Double the multiplier to account for the dummies

    model_name = pdk.models[transistor_type.lower()]

    circuit_name = prefix
    # Take only unique NET names
    nodes = [drain_net_in, drain_net_out, bulk_net]
    
    source_netlist = f".subckt {circuit_name} {' '.join(nodes)}\n"

    # Proposed ground connection (commented)
    # source_netlist += f"V{proposed_ground}1 ({proposed_ground} {bulk_net}) 0\n"

    # Generating only two transistors (one on each side):
    source_netlist += (
        f"X{prefix}_A {drain_net_in} {gate_net} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )
    source_netlist += (
        f"X{prefix}_B {drain_net_out} {gate_net} {bulk_net} {bulk_net} "
        f"{model_name} l={length} w={width} m={mtop}\n"
    )

    if dummy:
        source_netlist += (
            f"X{prefix}_DUMMY {bulk_net} {bulk_net} {bulk_net} {bulk_net} "
            f"{model_name} l={length} w={width} m={2}\n"
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
def current_mirror_base(
    pdk: MappedPDK,
    Width: float = 1,
    Length: Optional[float] = None,
    num_cols: int = 2,
    fingers: int = 1,
    type: Optional[str] = "nfet",
    with_substrate_tap: Optional[bool] = False,
    with_tie: Optional[bool] = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    with_dummy: Optional[bool] = True,
    show_netlist: Optional[bool] = False,
    add_labels = True,
    **kwargs,
) -> Component:
    """
    An instantiable current mirror that returns a Component object.
    The current mirror could be a two transistor interdigitized structure with a shorted source and gate.
    It can be instantiated with either nmos or pmos devices. It can also be instantiated with a dummy device,
    a substrate tap, and a tie layer, and is centered at the origin.
    Transistor A acts as the reference and Transistor B acts as the mirror fet.
    This current mirror is used to generate an exact copy of the reference current.
    [TODO] Needs to be checked for both pfet and nfet configurations.
    [TODO] It will be updated with multi-leg or stacked length parametrization in future.
    [TODO] There will also be a Regulated Cascoded block added to it.

    Args:
        pdk (MappedPDK): the process design kit to use
        Width (float): width of the interdigitized fets (same for both reference and mirror)
        Length (float): length of the interdigitized fets (same for both reference and mirror)
            Set to None to use the minimum length of the technology
        numcols (int): number of columns of the interdigitized fets
        fingers (int): number of fingers of interdigitized fets
        type (str): nfet or pfet
        with_dummy (bool): True places dummies on either side of the interdigitized fets
        with_substrate_tap (bool): place a substrate tapring
        with_tie (bool): place a tapring for tie layer
        tie_layers (tuple[str, str]): layers to use for the tie. Defaults to ("met2","met1").
        **kwargs: forwarded to the interdigitized builders
    Returns:
        Component: a current mirror component object
    """
    pdk.activate()
    maxmet_sep = pdk.util_max_metal_seperation()

    # Create the current mirror component
    top_level = Component(name="CurrentMirror")
    Length = Length if Length is not None else pdk.get_grule("poly")["min_width"]

    # Create the interdigitized fets
    if type.lower() in ("pfet", "pmos"):
        currm = n_transistor_interdigitized(
            pdk,
            device="pfet",
            numcols=num_cols,
            n_devices=2,
            width=Width,
            length=Length,
            fingers=fingers,
            with_substrate_tap=False,
            with_tie=False,
        )
        well, sdglayer = "nwell", "n+s/d"
    elif type.lower() in ("nfet", "nmos"):
        currm = n_transistor_interdigitized(
            pdk,
            device="nfet",
            numcols=num_cols,
            n_devices=2,
            width=Width,
            length=Length,
            fingers=fingers,
            with_substrate_tap=False,
            with_tie=False,
        )
        well, sdglayer = "pwell", "p+s/d"
    else:
        raise ValueError("type must be either nfet or pfet")

    # Add the interdigitized fets to the current mirror top component
    currm_ref = prec_ref_center(currm)
    top_level.add(currm_ref)
    top_level.add_ports(currm_ref.get_ports_list(), prefix="currm_")

    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    viam1m2 = via_stack(pdk, "met1", "met2", centered=True)

    dist_DS = abs(
        top_level.ports["currm_A_0_drain_E"].center[0]
        - top_level.ports["currm_A_0_drain_W"].center[0]
    ) / 2

    dist_GS = abs(
        top_level.ports["currm_A_0_gate_E"].center[0]
        - top_level.ports["currm_A_0_gate_W"].center[0]
    ) / 2

    bottomA_drain_via = top_level << viam2m3
    bottomA_drain_via.move(top_level.ports["currm_A_0_drain_W"].center).movex(dist_DS)

    bottomA_gate_via = top_level << viam2m3
    bottomA_gate_via.move(top_level.ports["currm_A_0_gate_W"].center).movex(dist_GS)

    bottomB_gate_via = top_level << viam2m3
    bottomB_gate_via.move(
        (bottomA_gate_via.center[0], top_level.ports["currm_B_0_gate_W"].center[1])
    )

    top_level << straight_route(
        pdk, bottomA_drain_via.ports["top_met_N"], bottomA_gate_via.ports["top_met_S"], glayer1="met3", glayer2="met3"
    )
    top_level << straight_route(
        pdk, bottomA_gate_via.ports["top_met_N"], bottomB_gate_via.ports["top_met_S"], glayer1="met3", glayer2="met3"
    )

    # -------------------------------------------------------------------------
    # TAP RING
    # -------------------------------------------------------------------------
    snap = pdk.snap_to_2xgrid

    core = top_level.copy()       # so we don't mutate while measuring
    core_flat = core.flatten()    # include all placed children

    xmin, xmax = core_flat.xmin, core_flat.xmax
    ymin, ymax = core_flat.ymin, core_flat.ymax

    core_w = xmax - xmin
    core_h = ymax - ymin

    cx = snap((xmin + xmax) / 2)
    cy = snap((ymin + ymax) / 2)

    # Adding tapring
    if with_tie:
        well, sdglayer = "pwell", "p+s/d"
        tap_separation = max(
            maxmet_sep, pdk.get_grule("active_diff", "active_tap")["min_separation"]
        )
        tap_separation += pdk.get_grule(sdglayer, "active_tap")["min_enclosure"]
        tap_encloses = (snap(4 * tap_separation + core_w), snap(4 * tap_separation + core_h))
        tie_ref = top_level << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer=sdglayer,
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        tie_ref.move((cx, cy))
        top_level.add_ports(tie_ref.get_ports_list(), prefix="welltie_")

    # add well padding + perimeter ports
    top_level.add_padding(
        default=pdk.get_grule(well, "active_tap")["min_enclosure"],
        layers=[pdk.get_glayer(well)],
    )
    top_level = add_ports_perimeter(top_level, layer=pdk.get_glayer(well), prefix="well_")

    # add the substrate tap if specified
    if with_substrate_tap:
        substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")["min_separation"]
        substrate_tap_enclosure = (
            snap(4 * substrate_tap_separation + core_w),
            snap(4 * substrate_tap_separation + core_h),
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
        top_level.add_ports(substrate_tap_ring_ref.get_ports_list(), prefix="substrate_tap_")

    # Connect well ties to well
    try:
        pass
        top_level << straight_route(
            pdk, top_level.ports["currm_A_0_dummy_L_gsdcon_top_met_W"], top_level.ports["welltie_W_top_met_W"], glayer2="met1"
        )
        top_level << straight_route(
            pdk, top_level.ports["currm_B_0_dummy_R_gsdcon_top_met_E"], top_level.ports["welltie_E_top_met_E"], glayer2="met1"
        )
    except KeyError:
        pass

    # -------------------------------------------------------------------------
    # CONNECT BOTTOM DRAINS TO OTHER STAGES
    # -------------------------------------------------------------------------
    dist_ring = abs(
        top_level.ports["welltie_W_top_met_W"].center[0]
        - top_level.ports["welltie_W_top_met_E"].center[0]
    ) / 2

    bottomA_drain_via = top_level << viam1m2
    bottomA_drain_via.move(
        (top_level.ports["welltie_W_top_met_W"].center[0], top_level.ports["currm_A_0_drain_W"].center[1])
    ).movex(-dist_ring - 2 * dist_DS)
    top_level.add_ports(bottomA_drain_via.get_ports_list(), prefix="IN_")

    top_level << straight_route(
        pdk, top_level.ports["currm_A_0_drain_W"], bottomA_drain_via.ports["top_met_W"], glayer2="met2"
    )

    bottomB_drain_via = top_level << viam1m2
    bottomB_drain_via.move(
        (top_level.ports["welltie_E_top_met_E"].center[0], top_level.ports["currm_B_0_drain_E"].center[1])
    ).movex(-dist_ring + 2 * dist_DS)
    top_level.add_ports(bottomB_drain_via.get_ports_list(), prefix="OUT_")

    top_level << straight_route(
        pdk, top_level.ports["currm_B_0_drain_E"], bottomB_drain_via.ports["top_met_E"], glayer2="met2"
    )

    # -------------------------------------------------------------------------
    # CONNECT SOURCES TO GND
    # -------------------------------------------------------------------------
    bottomA_source_via = top_level << viam1m2
    bottomA_source_via.move(
        (top_level.ports["welltie_W_top_met_E"].center[0], top_level.ports["currm_A_0_source_W"].center[1])
    ).movex(-dist_ring)

    top_level << straight_route(
        pdk, top_level.ports["currm_A_0_source_W"], bottomA_source_via.ports["top_met_W"], glayer2="met2"
    )

    bottomB_source_via = top_level << viam1m2
    bottomB_source_via.move(
        (top_level.ports["welltie_E_top_met_E"].center[0], top_level.ports["currm_B_0_source_W"].center[1])
    ).movex(-dist_ring)

    top_level << straight_route(
        pdk, top_level.ports["currm_B_0_source_W"], bottomB_source_via.ports["top_met_W"], glayer2="met2"
    )

    top_level = component_snap_to_grid(rename_ports_by_orientation(top_level))

    top_level.info["netlist"] = generate_current_mirror_netlist(
        pdk=pdk,
        prefix="VCM",
        instance_name=top_level.name,
        CM_size=(Width, Length, num_cols, fingers),  # (width, length, multipliers, fingers)
        transistor_type=type,
        drain_net_in="VIN",   # Input drain connected to IREF
        drain_net_out="VOUT", # Output drain connected to ICOPY
        gate_net="VIN",       # Gate connected to VREF
        source_net_in="VSS" if type.lower() == "nfet" else "VDD",  # Source
        source_net_out="VSS" if type.lower() == "nfet" else "VDD", # Source
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
    move_info.append((vinlabel, cm_in.ports["IN_top_met_N"], None))

    # VOUT
    voutlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutlabel.add_label(text="VOUT", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutlabel, cm_in.ports["OUT_top_met_N"], None))

    # VSS (well tie)
    vsslabel = rectangle(layer=pdk.get_glayer("met1_pin"), size=psize, centered=True).copy()
    vsslabel.add_label(text="VSS", layer=pdk.get_glayer("met1_label"))
    move_info.append((vsslabel, cm_in.ports["welltie_N_top_met_N"], None))

    for comp, prt, alignment in move_info:
        alignment = ("c", "b") if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        cm_in.add(compref)

    return cm_in.flatten()


if __name__ == "__main__":
    selected_pdk = gf180
    comp = current_mirror_base(selected_pdk, num_cols=1, Length=1, Width=4, device="nfet", show_netlist=False)
    # comp = add_cm_labels(comp, pdk=selected_pdk)
    comp.name = "CM"
    comp.show()

    # Print the generated netlist
    print(comp.info["netlist"].generate_netlist())

    # Run DRC
    drc_result = selected_pdk.drc_magic(comp, comp.name, output_file=Path("DRC/"))

    # Run LVS
    netgen_lvs_result = selected_pdk.lvs_netgen(
        comp, comp.name, output_file_path=Path("LVS/"), copy_intermediate_files=True
    )