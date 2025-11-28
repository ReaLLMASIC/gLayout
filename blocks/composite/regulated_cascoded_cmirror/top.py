from pathlib import Path
from typing import Optional, Union
import os
import re
import subprocess

from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory.components import rectangle, text_freetype

from glayout import MappedPDK, sky130, gf180, nmos, pmos, tapring, via_stack
from glayout.placement.two_transistor_interdigitized import (
    two_nfet_interdigitized,
    two_pfet_interdigitized,
)
from glayout.routing import L_route, c_route, straight_route
from glayout.spice.netlist import Netlist
from glayout.util.comp_utils import (
    align_comp_to_port,
    evaluate_bbox,
    prec_center,
    prec_ref_center,
)
from glayout.util.port_utils import add_ports_perimeter, rename_ports_by_orientation
from glayout.util.snap_to_grid import component_snap_to_grid

from cm_v import current_mirror_base
from cm_sb import self_biased_cascode_current_mirror
from cm_rc import regulated_cascode_current_mirror
from input import input_stage
from bias import bias_stage

###### Only Required for IIC-OSIC Docker
# Run a shell, source .bashrc, then printenv
cmd = 'bash -c "source ~/.bashrc && printenv"'
result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
env_vars = {}
for line in result.stdout.splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        env_vars[key] = value
os.environ.update(env_vars)

# ---- helpers ----
_HEADER_RE = re.compile(
    r"^\s*\.subckt\s+(\S+)\s+(.*)\s*$", re.IGNORECASE | re.MULTILINE
)


def _parse_subckt_header(source: str):
    m = _HEADER_RE.search(source)
    if not m:
        raise ValueError("Could not find .subckt header in child netlist")
    name = m.group(1)
    pins = [t for t in m.group(2).split() if t.strip()]
    return name, pins


def _instance_line(
    inst_name: str,
    subckt_name: str,
    ordered_child_pins: list[str],
    pinmap: dict[str, str],
):
    try:
        nodes_in_order = [pinmap[p] for p in ordered_child_pins]
    except KeyError as e:
        missing = str(e).strip("'")
        raise ValueError(
            f"Missing mapping for child pin '{missing}' when instantiating {subckt_name}"
        )
    return f"X{inst_name} " + " ".join(nodes_in_order) + f" {subckt_name}\n"


def generate_top_netlist(
    prefix: str,
    in_net: str,
    aux_net: str,
    en_net: str,
    out_vcm_net: str,
    out_sbcm_net: str,
    out_rccm_net: str,
    out_vin_net: str,
    nl_input: Netlist,
    nl_bias: Netlist,
    nl_vcm: Netlist,
    nl_sbcm: Netlist,
    nl_rccm: Netlist,
    show_netlist: bool = False,
) -> Netlist:
    """
    Build top-level .subckt that instantiates child subckts and wires them to top nets.
    TOP pin order must match layout header:
    .subckt TOP VIN VSS VDD VOUT_RCCM VOUT_SBCM VOUT_VCM VAUX EN
    """
    top_pins = [
        in_net,
        "VSS",
        "VDD",
        out_vin_net,
        out_rccm_net,
        out_sbcm_net,
        out_vcm_net,
        aux_net,
        en_net,
    ]

    # Render children and parse headers
    child_texts = {
        "INPUT": nl_input.generate_netlist(),
        "BIAS":  nl_bias.generate_netlist(),
        "VCM": nl_vcm.generate_netlist(),
        "SBCM": nl_sbcm.generate_netlist(),
        "RCCM": nl_rccm.generate_netlist(),
    }
    parsed = {}
    for key, text in child_texts.items():
        subckt_name, pins = _parse_subckt_header(text)
        parsed[key] = {"name": subckt_name, "pins": pins, "text": text}

    # Internal nets
    in_vcm_int = "IN_VCM"
    in_sbcm_int = "IN_SBCM"
    in_rccm_int = "IN_RCCM"

    bias_rccm_int = "BIAS_RCCM"

    # Pin maps matching the child headers
    # INPUT: .subckt INPUT VIN EN VOUT_VCM VOUT_BCM VOUT_CCM VDD
    pinmap_input = {
        "VIN": in_net,
        "EN": en_net,
        "VOUT_VCM": in_vcm_int,
        "VOUT_BCM": in_sbcm_int,
        "VOUT_CCM": in_rccm_int,
        "VOUT_VIN": out_vin_net,
        "VDD": "VDD",
    }
    # BIAS: .subckt BIAS IN_RCCM VAUX EN VDD
    pinmap_bias = {
        "VOUT": bias_rccm_int,
        "VIN": aux_net,
        "EN": en_net,
        "VDD": "VDD",
        "VSS": "VSS",
    }
    # VCM: .subckt VCM VIN VOUT VSS
    pinmap_vcm = {"VIN": in_vcm_int, "VOUT": out_vcm_net, "VSS": "VSS"}
    # SBCM: .subckt SBCM VIN VOUT VSS
    pinmap_sbcm = {"VIN": in_sbcm_int, "VOUT": out_sbcm_net, "VSS": "VSS"}
    # RCCM: .subckt RCCM VIN VAUX VOUT VSS
    pinmap_rccm = {
        "VIN": in_rccm_int,
        "VAUX": bias_rccm_int,
        "VOUT": out_rccm_net,
        "VSS": "VSS",
    }

    # Build instance lines using parsed child pin order
    x_lines = [
        _instance_line(
            f"{prefix}IN",
            parsed["INPUT"]["name"],
            parsed["INPUT"]["pins"],
            pinmap_input,
        ),
        _instance_line(
            f"{prefix}BIAS",
            parsed["BIAS"]["name"],
            parsed["BIAS"]["pins"],
            pinmap_bias,
        ),
        _instance_line(
            f"{prefix}VCM",
            parsed["VCM"]["name"],
            parsed["VCM"]["pins"],
            pinmap_vcm,
        ),
        _instance_line(
            f"{prefix}SBCM",
            parsed["SBCM"]["name"],
            parsed["SBCM"]["pins"],
            pinmap_sbcm,
        ),
        _instance_line(
            f"{prefix}RCCM",
            parsed["RCCM"]["name"],
            parsed["RCCM"]["pins"],
            pinmap_rccm,
        ),
    ]

    # Write children FIRST, then TOP
    src = []
    for key in ("INPUT", "BIAS", "VCM", "SBCM", "RCCM"):
        src.append(parsed[key]["text"].rstrip())
        src.append("")

    src.append(f".subckt {prefix} " + " ".join(top_pins))
    src.extend(x_lines)
    src.append(".ends " + prefix)
    src.append("")

    source_netlist = "\n".join(src)

    topnet = Netlist(
        circuit_name=prefix,
        nodes=top_pins,
        source_netlist=source_netlist,
        instance_format="X{name} {nodes} {circuit_name}",
        parameters={},
    )

    if show_netlist:
        print("Generated top-level netlist:\n")
        print(topnet.generate_netlist())

    return topnet

# def generate_top_netlist(
#     prefix: str,
#     in_net: str,
#     aux_net: str,
#     en_net: str,
#     out_vcm_net: str,
#     out_sbcm_net: str,
#     out_rccm_net: str,
#     nl_input: Netlist,
#     nl_vcm: Netlist,
#     nl_sbcm: Netlist,
#     nl_rccm: Netlist,
#     show_netlist: bool = False,
# ) -> Netlist:
#     """
#     Build top-level .subckt that instantiates child subckts and wires them to top nets.
#     TOP pin order must match layout header:
#     .subckt TOP VIN VSS VDD VOUT_RCCM VOUT_SBCM VOUT_VCM VAUX EN
#     """
#     top_pins = [
#         in_net,
#         "VSS",
#         "VDD",
#         out_rccm_net,
#         out_sbcm_net,
#         out_vcm_net,
#         aux_net,
#         en_net,
#     ]

#     netlist = Netlist(
#         circuit_name=prefix,
#         nodes=top_pins,
#     )


#     in_comp = netlist.connect_netlist(nl_input, [('VIN',in_net),('EN',en_net), ('VDD','VDD')])
#     vcm_comp = netlist.connect_netlist(nl_vcm, [('VOUT',out_vcm_net),('VSS','VSS')])
#     sbcm_comp = netlist.connect_netlist(nl_sbcm, [('VOUT',out_sbcm_net),('VSS','VSS')])
#     rccm_comp = netlist.connect_netlist(nl_rccm, [('VAUX',aux_net),('VOUT',out_rccm_net),('VSS','VSS')])

#     netlist.connect_subnets(in_comp, vcm_comp, [('VOUT_VCM','VIN')])
#     netlist.connect_subnets(in_comp, sbcm_comp, [('VOUT_BCM','VIN')])
#     netlist.connect_subnets(in_comp, rccm_comp, [('VOUT_CCM','VIN')])

#     if show_netlist:
#         print("Generated top-level netlist:\n")
#         print(netlist.generate_netlist())

#     return netlist


# @validate_arguments
def top(
    pdk: MappedPDK,
    with_tie: Optional[bool] = True,
    with_dummy: Optional[bool] = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    show_netlist: Optional[bool] = False,
    add_labels: bool = True,
    **kwargs,
) -> Component:
    """An instantiable self biased cascoded current mirror that returns a Component."""
    pdk.activate()

    # Create the current mirror component
    top_level = Component(name="top_design")
    top_ref = prec_ref_center(top_level)

    viam1m2 = via_stack(pdk, "met1", "met2", centered=True)
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    viam1m3 = via_stack(pdk, "met1", "met3", centered=True)

    # -------------------------------------------------------------------------
    # CREATING THE INPUT STAGE
    # -------------------------------------------------------------------------
    print("Creating Input Stage ...")

    input_stage_comp = input_stage(
        pdk,
        num_cols=1,
        Length=2,
        Width=10,
        device="pfet",
        with_substrate_tap=False,
        with_tie=with_tie,
        with_dummy=with_dummy,
        tie_layers=tie_layers,
        add_labels=False,
    )
    input_stage_ref = prec_ref_center(input_stage_comp)
    input_stage_ref.move(top_ref.center)
    top_level.add(input_stage_ref)
    top_level.add_ports(input_stage_ref.get_ports_list(), prefix="input_")

    center = top_level.center

    # -------------------------------------------------------------------------
    # CREATING THE VANILLA CURRENT MIRROR STAGE
    # -------------------------------------------------------------------------
    print("Creating Vanilla Current Mirror ...")

    VCM = current_mirror_base(
        pdk,
        num_cols=1,
        Length=1,
        Width=4,
        device="nfet",
        with_substrate_tap=False,
        add_labels=False,
    )
    vcm_ref = prec_ref_center(VCM)
    vcm_ref.move(center).movex(
        evaluate_bbox(input_stage_ref)[0] + 4 * pdk.util_max_metal_seperation()
    ).movey(-evaluate_bbox(input_stage_ref)[1] / 2)

    top_level.add(vcm_ref)
    top_level.add_ports(vcm_ref.get_ports_list(), prefix="vcm_")

    top_level << L_route(
        pdk, vcm_ref.ports["IN_top_met_N"], input_stage_ref.ports["OUT_B_top_met_E"]
    )

    # -------------------------------------------------------------------------
    # CREATING THE SELF-BIASED CURRENT MIRROR STAGE
    # -------------------------------------------------------------------------
    print("Creating Self-Biased Current Mirror ...")

    SBCM = self_biased_cascode_current_mirror(
        pdk, num_cols=1, Length=1, Width=4, device="nfet", add_labels=False
    )
    sbcm_ref = prec_ref_center(SBCM)
    sbcm_ref.move(center).movex(
        evaluate_bbox(input_stage_ref)[0] + 4 * pdk.util_max_metal_seperation()
    )

    top_level.add(sbcm_ref)
    top_level.add_ports(sbcm_ref.get_ports_list(), prefix="sbcm_")

    top_level << L_route(
        pdk, sbcm_ref.ports["IN_top_met_N"], input_stage_ref.ports["OUT_C_top_met_E"]
    )

    # -------------------------------------------------------------------------
    # CREATING THE REGULATED CASCODE CURRENT MIRROR STAGE
    # -------------------------------------------------------------------------
    print("Creating Regulated Cascoded Current Mirror ...")

    RCCM = regulated_cascode_current_mirror(
        pdk, num_cols=2, Length=1, Width=4, device="nfet", show_netlist=False, add_labels=False
    )
    rccm_ref = prec_ref_center(RCCM)
    rccm_ref.move(center).movex(
        evaluate_bbox(input_stage_ref)[0] + 4 * pdk.util_max_metal_seperation()
    ).movey(+evaluate_bbox(input_stage_ref)[1] / 2)

    top_level.add(rccm_ref)
    top_level.add_ports(rccm_ref.get_ports_list(), prefix="rccm_")

    dist_via = abs(
        rccm_ref.ports["IN_top_met_W"].center[0]
        - rccm_ref.ports["IN_top_met_E"].center[0]
    ) / 2

    in_rccm_via = top_level << viam2m3
    in_rccm_via.move((input_stage_ref.ports["OUT_D_top_met_W"].center)).movex(dist_via)

    rccm_in_via = top_level << viam2m3
    rccm_in_via.move((rccm_ref.ports["IN_top_met_W"].center)).movex(dist_via)


    top_level << L_route(
        pdk, in_rccm_via.ports["top_met_N"], rccm_in_via.ports["top_met_W"], hglayer="met3", vglayer="met3",
    )

    # -------------------------------------------------------------------------
    # CREATING THE BIAS STAGE
    # -------------------------------------------------------------------------
    print("Creating Bias Stage ...")

    bias_stage_comp = bias_stage(
        pdk,
        add_labels=False,
    )
    bias_stage_ref = prec_ref_center(bias_stage_comp)

    bias_stage_ref.move(center).movex(
        -3 * evaluate_bbox(input_stage_ref)[0] - 6 * pdk.util_max_metal_seperation()
    ).movey(+evaluate_bbox(input_stage_ref)[1] / 2 + evaluate_bbox(sbcm_ref)[1] / 2 + 6 * pdk.util_max_metal_seperation())
    bias_stage_ref.move(center)
    top_level.add(bias_stage_ref)
    top_level.add_ports(bias_stage_ref.get_ports_list(), prefix="bias_")


    # -------------------------------------------------------------------------
    # CONNECTING AUX
    # -------------------------------------------------------------------------


    top_level << L_route(
        pdk, bias_stage_ref.ports["base_right_OUT_top_met_N"], rccm_ref.ports["AUX_A_top_met_W"], hglayer="met1", vglayer="met1",
    )

    en_via = top_level << viam1m2
    en_via.move(bias_stage_ref.ports["fet_right_multiplier_0_gate_E"].center).movex(evaluate_bbox(bias_stage_ref)[0])
    top_level.add_ports(en_via.get_ports_list(), prefix=f"EN_")

    top_level << straight_route(
        pdk,
        bias_stage_ref.ports["fet_right_multiplier_0_gate_E"],
        en_via.ports["top_met_W"],
        glayer1="met2",
        glayer2="met2",
    )

    en_input_via = top_level << viam2m3
    en_input_via.move((input_stage_ref.ports["EN_A_top_met_N"].center[0], en_via.center[1]))

    en_input_conn_via = top_level << viam2m3
    en_input_conn_via.move(input_stage_ref.ports["EN_A_top_met_N"].center)

    top_level << straight_route(
        pdk,
        en_input_via.ports["top_met_S"],
        en_input_conn_via.ports["top_met_S"],
        glayer1="met3",
        glayer2="met3",
    )

    aux_via = top_level << viam2m3
    aux_via.move(en_via.center).movey(evaluate_bbox(rccm_ref)[1])
    top_level.add_ports(aux_via.get_ports_list(), prefix=f"VAUX_")

    ##### This one Met 3
    top_level << L_route(
        pdk,
        bias_stage_ref.ports["base_left_IN_top_met_N"],
        aux_via.ports["top_met_W"],
        hglayer="met3", vglayer="met2"
    )

    # Outputs

    vcm_via = top_level << viam1m2
    vcm_via.move((en_via.center[0], vcm_ref.ports["OUT_top_met_W"].center[1]))
    top_level.add_ports(vcm_via.get_ports_list(), prefix=f"VOUT_VCM_")

    top_level << straight_route(
        pdk,
        vcm_via.ports["top_met_W"],
        vcm_ref.ports["OUT_top_met_E"],
        glayer1="met2",
        glayer2="met2",
    )

    sbcm_via = top_level << viam1m2
    sbcm_via.move((en_via.center[0], sbcm_ref.ports["OUT_top_met_W"].center[1]))
    top_level.add_ports(sbcm_via.get_ports_list(), prefix=f"VOUT_SBCM_")

    top_level << straight_route(
        pdk,
        sbcm_via.ports["top_met_W"],
        sbcm_ref.ports["OUT_top_met_E"],
        glayer1="met2",
        glayer2="met2",
    )

    rccm_via = top_level << viam1m2
    rccm_via.move((en_via.center[0], rccm_ref.ports["OUT_top_met_W"].center[1]))
    top_level.add_ports(rccm_via.get_ports_list(), prefix=f"VOUT_RCCM_")

    top_level << straight_route(
        pdk,
        rccm_via.ports["top_met_W"],
        rccm_ref.ports["OUT_top_met_E"],
        glayer1="met2",
        glayer2="met2",
    )

    outvin_via = top_level << viam1m2
    outvin_via.move(en_via.center).movey(-evaluate_bbox(vcm_ref)[1] + 6 * pdk.util_max_metal_seperation())
    top_level.add_ports(outvin_via.get_ports_list(), prefix=f"VOUT_VIN_")

    top_level << L_route(
        pdk, input_stage_ref.ports["OUT_E_top_met_N"], outvin_via.ports["top_met_W"], hglayer="met2", vglayer="met2",
    )

    # Input

    vin1_via = top_level << viam1m2
    vin1_via.move(input_stage_ref.ports["IN_A_top_met_N"].center).movey(-evaluate_bbox(sbcm_ref)[1])

    vin2_via = top_level << viam1m2
    vin2_via.move(vin1_via.center).movex(2*evaluate_bbox(input_stage_ref)[0])

    vin3_via = top_level << viam1m2
    vin3_via.move(aux_via.center).movey(evaluate_bbox(rccm_ref)[1])
    top_level.add_ports(vin3_via.get_ports_list(), prefix=f"VIN_")

    top_level << straight_route(
        pdk,
        input_stage_ref.ports["IN_A_top_met_S"],
        vin1_via.ports["top_met_N"],
        glayer1="met1",
        glayer2="met1",
    )

    top_level << straight_route(
        pdk,
        vin1_via.ports["top_met_E"],
        vin2_via.ports["top_met_W"],
        glayer1="met1",
        glayer2="met1",
    )

    top_level << L_route(
        pdk,
        vin2_via.ports["top_met_N"],
        vin3_via.ports["top_met_W"],
        hglayer="met1", vglayer="met1",
    )

    # VSS

    vss_via = top_level << viam1m3
    vss_via.move(vin3_via.center).movey(evaluate_bbox(rccm_ref)[1])
    top_level.add_ports(vss_via.get_ports_list(), prefix=f"VSS_")

    top_level << L_route(
        pdk,
        vss_via.ports["top_met_W"],
        rccm_ref.ports["welltie_N_top_met_N"],
        hglayer="met1", vglayer="met1",
        vwidth=5, hwidth=5
    )

    ###### DRC_Error
    # handles = place_welltie_via_row(
    # top_level, pdk, "bias_base_bottom",
    # top_layer="met3",
    # use_edges=False, offset=5.0,
    # fill_mode="auto",
    # )

    # top_level << L_route(
    #     pdk,
    #     bias_stage_ref.ports["base_bottom_welltie_N_top_met_N"],
    #     vss_via.ports["top_met_W"],
    #     hglayer="met3", vglayer="met3",
    #     vwidth=12, hwidth=12,
    # )
    #######################################################
    
    # VDD
    vdd_via = top_level << viam1m2
    vdd_via.move(vss_via.center).movey(evaluate_bbox(rccm_ref)[1])
    top_level.add_ports(vdd_via.get_ports_list(), prefix=f"VDD_")

    top_level << L_route(
        pdk,
        vdd_via.ports["top_met_W"],
        bias_stage_ref.ports["fet_left_tie_N_top_met_N"],
        hglayer="met1", vglayer="met1",
        vwidth=5, hwidth=5
    )


    # -------------------------------------------------------------------------
    # CONNECTING VDD TOGETHER
    # -------------------------------------------------------------------------

    top_level << straight_route(
        pdk,
        bias_stage_ref.ports["VDD_port"],
        top_level.ports["input_welltie_W_top_met_W"],
        glayer1="met1",
        glayer2="met1",
        width=10,
    )

    # -------------------------------------------------------------------------
    # CONNECTING VSS TOGETHER
    # -------------------------------------------------------------------------
    top_level << straight_route(
        pdk,
        top_level.ports["vcm_welltie_N_top_met_N"],
        top_level.ports["sbcm_welltie_S_top_met_S"],
        glayer1="met1",
        glayer2="met1",
        width=10,
    )
    top_level << straight_route(
        pdk,
        top_level.ports["sbcm_welltie_N_top_met_N"],
        top_level.ports["rccm_welltie_S_top_met_S"],
        glayer1="met1",
        glayer2="met1",
        width=10,
    )

    top_level << L_route(
        pdk,
        bias_stage_ref.ports["base_bottom_welltie_N_top_met_N"],
        vss_via.ports["top_met_W"],
        hglayer="met2", vglayer="met2",
        vwidth=12, hwidth=12,
    )

    top_level = component_snap_to_grid(rename_ports_by_orientation(top_level))

    top_level.info["netlist"] = generate_top_netlist(
        prefix="TOP",
        in_net="VIN",
        aux_net="VAUX",
        en_net="EN",
        out_vcm_net="VOUT_VCM",
        out_sbcm_net="VOUT_SBCM",
        out_rccm_net="VOUT_RCCM",
        out_vin_net="VOUT_VIN",
        nl_input=input_stage_comp.info["netlist"],
        nl_bias=bias_stage_comp.info["netlist"],
        nl_vcm=VCM.info["netlist"],
        nl_sbcm=SBCM.info["netlist"],
        nl_rccm=RCCM.info["netlist"],
        show_netlist=show_netlist,
    )

    if add_labels:
        return add_cm_labels(top_level, pdk)
    return top_level

def add_cm_labels(cm_in: Component, pdk: MappedPDK) -> Component:
    cm_in.unlock()

    psize = (0.35, 0.35)
    move_info = []

    # VIN
    vinlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    vinlabel.add_label(text="VIN", layer=pdk.get_glayer("met2_label"))
    move_info.append((vinlabel, cm_in.ports["VIN_top_met_E"], None))

    # EN
    vEnlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    vEnlabel.add_label(text="EN", layer=pdk.get_glayer("met2_label"))
    move_info.append((vEnlabel, cm_in.ports["EN_top_met_E"], None))

    # VAUX
    vauxlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    vauxlabel.add_label(text="VAUX", layer=pdk.get_glayer("met2_label"))
    move_info.append((vauxlabel, cm_in.ports["VAUX_top_met_E"], None))

    # VOUT VCM
    voutvcmlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutvcmlabel.add_label(text="VOUT_VCM", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutvcmlabel, cm_in.ports["VOUT_VCM_top_met_E"], None))

    # VOUT SBCM
    voutsbcmlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutsbcmlabel.add_label(text="VOUT_SBCM", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutsbcmlabel, cm_in.ports["VOUT_SBCM_top_met_E"], None))

    # VOUT RCCM
    voutrccmlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutrccmlabel.add_label(text="VOUT_RCCM", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutrccmlabel, cm_in.ports["VOUT_RCCM_top_met_E"], None))

    # VOUT VIN
    voutvinlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutvinlabel.add_label(text="VOUT_VIN", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutvinlabel, cm_in.ports["VOUT_VIN_top_met_E"], None))

    # VDD (well tie)
    vddlabel = rectangle(layer=pdk.get_glayer("met1_pin"), size=psize, centered=True).copy()
    vddlabel.add_label(text="VDD", layer=pdk.get_glayer("met1_label"))
    move_info.append((vddlabel, cm_in.ports["VDD_top_met_E"], None))

    # VSS (well tie)
    vsslabel = rectangle(layer=pdk.get_glayer("met1_pin"), size=psize, centered=True).copy()
    vsslabel.add_label(text="VSS", layer=pdk.get_glayer("met1_label"))
    move_info.append((vsslabel, cm_in.ports["VSS_top_met_E"], None))

    #

    for comp, prt, alignment in move_info:
        alignment = ("c", "b") if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        cm_in.add(compref)

    return cm_in.flatten()


def place_welltie_via_row(
    top_level,
    pdk,
    block_key: str=None,                 # expects f"{block_key}_welltie_S_top_met_S"
    *,
    top_layer: str = "met3",        # top layer to reach (string, e.g. "met3")
    # Where to put the two edge via stacks:
    use_edges: bool = True,         # True: at ± welltie.width/2; False: at ±offset
    offset: float = 5.0,            # used when use_edges=False (distance from center)
    jog_dy: float = 0.0,            # vertical offset for the whole via row center

    # How to fill middle stacks: mode ∈ {"auto","pitch","count"}
    fill_mode: str = "auto",
    pitch: float | None = None,     # used when fill_mode="pitch"
    count: int | None = None,       # used when fill_mode="count"
    edge_margin: float = 0.0,       # keep gap from edges for "pitch" mode
):
    """
    Returns dict with keys:
      left_ref, right_ref: ComponentReference of edge stacks
      left_top, right_top: Port on top_layer for each edge stack
      mid_refs: list[ComponentReference] for middle stacks
      mid_top_ports: list[Port] top ports for middle stacks
    """
    # --- 1) resolve the welltie S-facing top-metal port ---

    wt = top_level.ports[f"{block_key}_welltie_N_top_met_N"]  # Port (likely on met1 or met2)

    delta_y = abs(top_level.ports[f"{block_key}_welltie_N_top_met_N"].center[1] - top_level.ports[f"{block_key}_welltie_N_top_met_S"].center[1])/2
    x0, y0 = wt.center

    w_wt = wt.width

    # --- 2) utilities: mapping layer tuple<->name and grid snapping ---
    def _name_of(gl_tuple):
        for nm in ("met1","met2","met3","met4","met5"):
            try:
                if pdk.get_glayer(nm) == gl_tuple:
                    return nm
            except Exception:
                pass
        raise ValueError(f"Unknown layer tuple {gl_tuple}")

    snap = pdk.snap_to_2xgrid
    bottom_layer = _name_of(wt.layer)            # e.g. "met1" or "met2"
    bot_gl = pdk.get_glayer(bottom_layer)
    top_gl = pdk.get_glayer(top_layer)

    # --- 3) edge stack X positions ---
    if use_edges:
        xL = snap(x0 - w_wt/2)
        xR = snap(x0 + w_wt/2)
    else:
        xL = snap(x0 - abs(offset))
        xR = snap(x0 + abs(offset))
    yC = snap(y0 - delta_y+ jog_dy)

    # --- 4) create via stack template and place the two edge stacks (as refs) ---
    vs_proto = via_stack(pdk, bottom_layer, top_layer)  # Component
    left_ref  = top_level << vs_proto                   # ComponentReference
    right_ref = top_level << vs_proto
    left_ref.move((xL, yC))
    right_ref.move((xR, yC))

    # helper to pick bottom/top ports of a via ref
    def _bottom_port(vref):
        return next(p for p in vref.ports.values() if p.layer == bot_gl)
    def _top_port(vref):
        return next(p for p in vref.ports.values() if p.layer == top_gl)

    left_bot  = _bottom_port(left_ref)
    right_bot = _bottom_port(right_ref)
    left_top  = _top_port(left_ref)
    right_top = _top_port(right_ref)


    # --- 6) compute middle positions depending on fill_mode ---
    mid_refs = []
    mid_top_ports = []

    xL_center, _ = left_ref.center
    xR_center, _ = right_ref.center

    if fill_mode not in {"auto","pitch","count"}:
        raise ValueError("fill_mode must be one of {'auto','pitch','count'}")

    if fill_mode == "count":
        n = int(count or 0)
        if n > 0:
            step = (xR_center - xL_center) / (n + 1)
            for k in range(1, n+1):
                xk = snap(xL_center + k*step)
                r = top_level << vs_proto
                r.move((xk, yC))
                mid_refs.append(r)
                mid_top_ports.append(_top_port(r))

    else:
        # need a pitch value: either provided, or auto-computed
        if fill_mode == "pitch":
            if pitch is None or pitch <= 0:
                raise ValueError("fill_mode='pitch' requires a positive 'pitch' parameter.")
            eff_pitch = float(pitch)
        else:
            # "auto": via width on top layer + min spacing of that layer
            # get via *component* width on x from template bbox
            vx, _vy = evaluate_bbox(vs_proto)        # (w, h) in layout units
            min_sp = pdk.get_grule(top_layer)["min_separation"]
            eff_pitch = snap(vx + min_sp)

        x_start = snap(xL_center + edge_margin)
        x_stop  = snap(xR_center - edge_margin)

        x = x_start + eff_pitch
        # leave small epsilon to avoid placing on/over the right ref
        while x < x_stop - 1e-6:
            r = top_level << vs_proto
            r.move((snap(x), yC))
            mid_refs.append(r)
            mid_top_ports.append(_top_port(r))
            x += eff_pitch

    return {
        "left_ref": left_ref, "right_ref": right_ref,
        "left_top": left_top, "right_top": right_top,
        "mid_refs": mid_refs, "mid_top_ports": mid_top_ports,
    }


if __name__ == "__main__":
    selected_pdk = gf180

    comp = top(selected_pdk, show_netlist=False, add_labels=True)
    # comp.pprint_ports()
    comp.name = "M"
    comp.show()

    # Write the layout to GDS
    comp.write_gds("GDS/topv6.gds")

    # DRC
    drc_result = selected_pdk.drc_magic(comp, comp.name, output_file=Path("DRC/"))

    # LVS
    netgen_lvs_result = selected_pdk.lvs_netgen(
        comp, comp.name, output_file_path=Path("LVS/"), copy_intermediate_files=True
    )
