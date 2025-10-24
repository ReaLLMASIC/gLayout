from glayout import MappedPDK, sky130, gf180
from glayout import nmos, pmos, tapring, via_stack

from gdsfactory.port import Port

# from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from bias_base import biased_base
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
def generate_bias_netlist(
    pdk,
    prefix: str,
    in_net: str,
    en_net: str,
    out_net: str,
    show_netlist: bool = False,
    *,
    # NMOS (bottom block) sizing
    n_w: float = 8.0,
    n_l: float = 1.0,
    n_m_ab: int = 10,    # m for A and B devices
    n_m_cd: int = 1,    # m for C and D devices
    n_dummy_m: int = 4,
    include_n_dummy: bool = True,
    # PMOS (left/right blocks) sizing
    p_w: float = 10.0,
    p_l: float = 2.0,
    p_m_ab: int = 10,    # m for A and B devices
    p_m_cd: int = 1,    # m for C and D devices
    p_dummy_m: int = 4,
    include_p_dummy: bool = True,
    # Extra PFETs that tap internal nodes of the left/right blocks
    tap_left:  str = "VTBL",   # "VTBL" or "VTBR"
    tap_right: str = "VTBR",   # "VTBL" or "VTBR"
    tap_p_w: float = 10.0,
    tap_p_l: float = 2.0,
    tap_p_m: int = 1,
) -> Netlist:
    """
    Flat netlist of the bias stage:
      Pins: <in_net>  VSS  VDD  <out_net>  <en_net>

      Topology:
        LEFT  (PFET block):   in_net  -> N1
        BOTTOM(NFET block):   N1      -> N2
        RIGHT (PFET block):   N2      -> out_net

      Each block uses the same 4-device (A,B,C,D) structure you provided, with bulks:
        - PFET blocks: bulk = VDD
        - NFET block:  bulk = VSS

      Extra PFETs:
        - XMPL: D = chosen internal node of LEFT block (VTBL_L or VTBR_L)
        - XMPR: D = chosen internal node of RIGHT block (VTBL_R or VTBR_R)
        - Gates = EN, Source/Bulk = VDD
    """
    nmos_name = pdk.models["nfet"]
    pmos_name = pdk.models["pfet"]
    VSS, VDD = "VSS", "VDD"

    # Internal stitch nets between blocks
    N1 = f"{prefix}_N1"
    N2 = f"{prefix}_N2"

    # Helper to emit one block with A/B/C/D using your pattern, choosing model & bulk by type
    # Assumes device node order = D G S B (change if your PDK differs).
    def emit_block(
        block_id: str,  # "L", "B", "R"
        in_node: str,
        out_node: str,
        kind: str,      # "pfet" or "nfet"
    ) -> tuple[str, str, str]:
        VTBL = f"VTBL_{block_id}"
        VTBR = f"VTBR_{block_id}"
        if kind == "pfet":
            model = pmos_name
            w, l = p_w, p_l
            m_ab, m_cd = p_m_ab, p_m_cd
            bulk = VDD
            include_dummy = include_p_dummy
            dummy_m = p_dummy_m
        else:
            model = nmos_name
            w, l = n_w, n_l
            m_ab, m_cd = n_m_ab, n_m_cd
            bulk = VSS
            include_dummy = include_n_dummy
            dummy_m = n_dummy_m

        lines = []
        # A: D=in, G=in, S=VTBL, B=bulk
        lines.append(f"X{block_id}_A {in_node} {in_node} {VTBL} {bulk} {model} l={l} w={w} m={m_ab}")
        # B: D=VTBL, G=VTBL, S=bulk, B=bulk
        lines.append(f"X{block_id}_B {VTBL} {VTBL} {bulk} {bulk} {model} l={l} w={w} m={m_ab}")
        # C: D=out, G=in, S=VTBR, B=bulk
        lines.append(f"X{block_id}_C {out_node} {in_node} {VTBR} {bulk} {model} l={l} w={w} m={m_cd}")
        # D: D=VTBR, G=VTBL, S=bulk, B=bulk
        lines.append(f"X{block_id}_D {VTBR} {VTBL} {bulk} {bulk} {model} l={l} w={w} m={m_cd}")
        if include_dummy:
            lines.append(f"X{block_id}_DUMMY {bulk} {bulk} {bulk} {bulk} {model} l={l} w={w} m={dummy_m}")

        return ("\n".join(lines), VTBL, VTBR)

    # Build flat subckt text
    top_pins = [in_net, VSS, VDD, out_net, en_net]
    txt = [f".subckt {prefix} " + " ".join(top_pins)]

    # LEFT = PFET block
    left_text, VTBL_L, VTBR_L = emit_block("L", in_node=in_net, out_node=N1, kind="pfet")
    txt.append(left_text)

    # BOTTOM = NFET block
    bottom_text, VTBL_B, VTBR_B = emit_block("B", in_node=N1, out_node=N2, kind="nfet")
    txt.append(bottom_text)

    # RIGHT = PFET block
    right_text, VTBL_R, VTBR_R = emit_block("R", in_node=N2, out_node=out_net, kind="pfet")
    txt.append(right_text)

    # Choose which internal nodes to tap with the extra PFET drains
    def pick_tap(which: str, VTBL_name: str, VTBR_name: str) -> str:
        which = which.upper()
        if which not in ("VTBL", "VTBR"):
            raise ValueError("tap selection must be 'VTBL' or 'VTBR'")
        return VTBL_name if which == "VTBL" else VTBR_name

    tap_left_node  = pick_tap(tap_left,  VTBL_L, VTBR_L)
    tap_right_node = pick_tap(tap_left, VTBL_R, VTBR_R)

    # Extra PFETs (D G S B) → drains to taps, gate EN, source/bulk VDD
    txt.append(f"XMPL {tap_left_node}  {en_net} {VDD} {VDD} {pmos_name} l={tap_p_l} w={tap_p_w} m={tap_p_m}")
    txt.append(f"XMPR {tap_right_node} {en_net} {VDD} {VDD} {pmos_name} l={tap_p_l} w={tap_p_w} m={tap_p_m}")
    txt.append(f"Xextra_DUMMY {VDD} {VDD} {VDD} {VDD} {pmos_name} l={tap_p_l} w={tap_p_w} m={4}")

    txt.append(f".ends {prefix}")
    source_netlist = "\n".join(txt)

    net = Netlist(
        circuit_name=prefix,
        nodes=top_pins,
        source_netlist=source_netlist,
        instance_format="X{name} {nodes} {circuit_name}",  # kept for API symmetry
        parameters={
            "nmos_model": nmos_name, "pmos_model": pmos_name,
            "n_w": n_w, "n_l": n_l, "n_m_ab": n_m_ab, "n_m_cd": n_m_cd,
            "p_w": p_w, "p_l": p_l, "p_m_ab": p_m_ab, "p_m_cd": p_m_cd,
            "tap_p_w": tap_p_w, "tap_p_l": tap_p_l, "tap_p_m": tap_p_m,
        },
    )

    if show_netlist:
        print(source_netlist)

    return net


# @validate_arguments
def bias_stage(
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
    top_level = Component(name="bias_stage")
    top_level.name = "bias_stage"
    Length = Length if Length is not None else pdk.get_grule("poly")["min_width"]
    top_ref = prec_ref_center(top_level)

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # BOTTOM BASE
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    print("Creating base bottom of BIAS stage...")
    base_bottom = biased_base(
        pdk,
        device="nfet",
        width=(8, 8),
        length=1,
        fingers=(10,1),
        with_substrate_tap=False,
        with_tie=True,
    )


    base_bottom_ref = prec_ref_center(base_bottom)
    base_bottom_ref.move(top_ref.center)
    top_level.add(base_bottom_ref)

    top_level.add_ports(base_bottom_ref.get_ports_list(), prefix="base_bottom_")

    core1 = base_bottom.copy().flatten()   # so we don't mutate while measuring

    xmin1, xmax1 = core1.xmin, core1.xmax
    ymin1, ymax1 = core1.ymin, core1.ymax

    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    viam1m2 = via_stack(pdk, "met1", "met2", centered=True)


    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # TOP LEFT BASE
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    print("Creating base top of BIAS stage...")
    base_top = biased_base(
        pdk,
        device="pfet",
        width=(10, 10),
        length=2,
        fingers=(10,1),
        with_substrate_tap=False,
        with_tie=True,
    )

    core2 = base_top.copy().flatten()   # so we don't mutate while measuring

    xmin2, xmax2 = core2.xmin, core2.xmax
    ymin2, ymax2 = core2.ymin, core2.ymax

    base_left_ref = prec_ref_center(base_top)
    # base_left_ref.move(base_bottom_ref.center).movey(
    #     (ymax1-ymin1)  + 4 * n_well_sep + 4*maxmet_sep
    # ).movex(-(xmax1 - xmin1)/2 -  (xmax2 - xmin2)/2 - 2*n_well_sep - 2*maxmet_sep)
    base_left_ref.move(base_bottom_ref.center).movex(-(xmax1 - xmin1)/2 -  (xmax2 - xmin2)/2 - 2*n_well_sep - 2*maxmet_sep)
    top_level.add(base_left_ref)

    top_level.add_ports(base_left_ref.get_ports_list(), prefix="base_left_")

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # TOP RIGHT BASE
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------


    base_right_ref = prec_ref_center(base_top)
    # base_right_ref.move(base_bottom_ref.center).movey(
    #     (ymax1-ymin1)  + 4 * n_well_sep + 4*maxmet_sep
    # ).movex((xmax1 - xmin1)/2 + (xmax2 - xmin2)/2 + 2*n_well_sep + 2*maxmet_sep)
    base_right_ref.move(base_bottom_ref.center).movex((xmax1 - xmin1)/2 + (xmax2 - xmin2)/2 + 2*n_well_sep + 2*maxmet_sep)
    top_level.add(base_right_ref)

    top_level.add_ports(base_right_ref.get_ports_list(), prefix="base_right_")


    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # INTERCONNECTIONS
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    top_level << L_route(
        pdk, base_left_ref.ports["OUT_top_met_S"], base_bottom_ref.ports["IN_top_met_W"]
    )

    top_level << L_route(
        pdk, base_right_ref.ports["IN_top_met_S"], base_bottom_ref.ports["OUT_top_met_E"]
    )

    ## Adding Enable FETs
    fet = pmos(pdk, width=10, length=2, fingers=1, with_tie=True, with_substrate_tap=False)

    fet_ref_left = prec_ref_center(fet)

    # fet_ref_right = prec_ref_center(fet)

    fet_ref_left.move(base_left_ref.ports["GATE_CONN_top_met_N"].center).movey(4*maxmet_sep + 1.5*evaluate_bbox(fet_ref_left)[1] + 2*n_well_sep)
    top_level.add(fet_ref_left)

    top_level.add_ports(fet_ref_left.get_ports_list(), prefix="fet_left_")


    dist_DS = (
        abs(
            top_level.ports[f"fet_left_multiplier_0_drain_E"].center[0]
            - top_level.ports[f"fet_left_multiplier_0_drain_W"].center[0]
        )
        / 2
    )

    drain_gate_via = top_level << viam2m3
    drain_gate_via.move(top_level.ports[f"fet_left_multiplier_0_drain_W"].center).movex(dist_DS)

    top_level << straight_route(pdk, drain_gate_via.ports["top_met_S"], base_left_ref.ports["GATE_CONN_top_met_N"], glayer1="met3", glayer2="met3")

    fet_ref_right = prec_ref_center(fet)
    fet_ref_right.move(base_right_ref.ports["GATE_CONN_top_met_N"].center).movey(4*maxmet_sep + 1.5*evaluate_bbox(fet_ref_right)[1] + 2*n_well_sep)
    top_level.add(fet_ref_right)

    top_level.add_ports(fet_ref_right.get_ports_list(), prefix="fet_right_")

    drain_gate_via = top_level << viam2m3
    drain_gate_via.move(top_level.ports[f"fet_right_multiplier_0_drain_W"].center).movex(dist_DS)

    top_level << straight_route(pdk, drain_gate_via.ports["top_met_S"], base_right_ref.ports["GATE_CONN_top_met_N"], glayer1="met3", glayer2="met3")

    ## DRC Problem
    top_level << straight_route(pdk, fet_ref_left.ports["tie_S_top_met_S"], base_left_ref.ports["welltie_N_top_met_N"], width=6)
    top_level << straight_route(pdk, fet_ref_right.ports["tie_S_top_met_S"], base_right_ref.ports["welltie_N_top_met_N"], width=6)
    ######

    # Create two m1m2 vias to connect the gates of the pfets

    gate_left_via = top_level << viam1m2
    gate_left_via.move((base_bottom_ref.ports["welltie_W_top_met_W"].center[0], fet_ref_left.ports["multiplier_0_gate_E"].center[1]))

    gate_right_via = top_level << viam1m2
    gate_right_via.move((base_bottom_ref.ports["welltie_E_top_met_E"].center[0], fet_ref_right.ports["multiplier_0_gate_W"].center[1]))

    top_level << straight_route(pdk, fet_ref_left.ports["multiplier_0_gate_E"], gate_left_via.ports["top_met_W"], glayer1="met2", glayer2="met2")

    top_level << straight_route(pdk, gate_left_via.ports["top_met_E"], gate_right_via.ports["top_met_W"], glayer1="met1", glayer2="met1")

    top_level << straight_route(pdk, gate_right_via.ports["top_met_E"], fet_ref_right.ports["multiplier_0_gate_W"], glayer1="met2", glayer2="met2")

    # Connect pfets sources to tie

    dist_ring = (
        abs(
            fet_ref_left.ports["tie_W_top_met_W"].center[0]
            - fet_ref_left.ports["tie_W_top_met_E"].center[0]
        )
        / 2
    )

    left_tie_source_via = top_level << viam1m2
    left_tie_source_via.move(
            (fet_ref_left.ports["tie_W_top_met_E"].center[0], fet_ref_left.ports["multiplier_0_source_W"].center[1])
        ).movex(-dist_ring)
    

    top_level << straight_route(pdk, fet_ref_left.ports["multiplier_0_source_W"], left_tie_source_via.ports["top_met_E"], glayer1="met2", glayer2="met2")

    right_tie_source_via = top_level << viam1m2
    right_tie_source_via.move(
            (fet_ref_right.ports["tie_W_top_met_E"].center[0], fet_ref_right.ports["multiplier_0_source_W"].center[1])
        ).movex(-dist_ring)

    top_level << straight_route(pdk, fet_ref_right.ports["multiplier_0_source_W"], right_tie_source_via.ports["top_met_E"], glayer1="met2", glayer2="met2")

    # Connect fets ties to tie for VDD
    top_level << straight_route(pdk, fet_ref_left.ports["tie_E_top_met_E"], fet_ref_right.ports["tie_W_top_met_W"], glayer1="met1", glayer2="met1", width=6)

    # Connect base left and right well ties for VDD

    top_level, rc_h = c_route_welltie_south(top_level, pdk, left_key="base_left", right_key="base_right", width = 10, drop=10.0, layer_name="met1")


    top_level = component_snap_to_grid(rename_ports_by_orientation(top_level))

    top_level.info["netlist"] = generate_bias_netlist(
        pdk=pdk,
        prefix="BIAS",
        in_net="VIN",  # Input drain connected to IREF
        en_net="EN",  # Auxiliary node
        out_net="VOUT",
        show_netlist=show_netlist,
    )

    if add_labels:
        return add_cm_labels(top_level, pdk)
    else:
        if "VDD_port" not in top_level.ports:
            top_level.add_port(
                name="VDD_port",
                port=Port(
                    name="VDD_port",
                    center=rc_h.center,
                    width=rc_h.width,
                    orientation=rc_h.orientation,
                    layer=rc_h.layer,  # tuple
                ),
            )
        return top_level
    

def c_route_welltie_south(
    top_level,
    pdk,
    left_key: str,                  # e.g. "base_left"
    right_key: str,                 # e.g. "base_right"
    width: float = 4.0,
    drop: float = 6.0,
    layer_name: str = "met1",       # STRING for straight_route glayers
):
    # Resolve real S-facing well-tie ports
    pL_real = top_level.ports[f"{left_key}_welltie_S_top_met_S"]
    pR_real = top_level.ports[f"{right_key}_welltie_S_top_met_S"]

    gl_tuple = pdk.get_glayer(layer_name)  # tuple for Port.layer
    gl_name  = layer_name                  # string for straight_route arg

    # Snap coords
    xL = pdk.snap_to_2xgrid(pL_real.center[0])
    xR = pdk.snap_to_2xgrid(pR_real.center[0])
    yL = pdk.snap_to_2xgrid(pL_real.center[1])
    yR = pdk.snap_to_2xgrid(pR_real.center[1])
    y_jog = pdk.snap_to_2xgrid(min(yL, yR) - abs(drop))

    # Shadow endpoints (tuple-layer)
    pL = Port("shadow_pL", center=(xL, yL), width=width, orientation=pL_real.orientation, layer=gl_tuple)
    pR = Port("shadow_pR", center=(xR, yR), width=width, orientation=pR_real.orientation, layer=gl_tuple)

    # Vertical–corner ports at the jog (centered on verticals)
    lc_v = Port("lc_v", center=(xL, y_jog), width=width, orientation=90,  layer=gl_tuple)   # faces north
    rc_v = Port("rc_v", center=(xR, y_jog), width=width, orientation=270, layer=gl_tuple)   # faces south

    # >>> Edge-aligned horizontal corners <<<
    # horizontal start at *left edge* of left vertical: x_left_edge = xL - width/2
    lc_h = Port("lc_h", center=(pdk.snap_to_2xgrid(xL - width/2), y_jog),
                width=width, orientation=0, layer=gl_tuple)   # faces east
    # horizontal end at *right edge* of right vertical: x_right_edge = xR + width/2
    rc_h = Port("rc_h", center=(pdk.snap_to_2xgrid(xR + width/2), y_jog),
                width=width, orientation=180, layer=gl_tuple) # faces west
    
    top_level.add_port(name="VDD_port", port=rc_h)
    
    # Routes (all on layer_name)
    top_level << straight_route(pdk, pL,   lc_v, glayer2=gl_name, width=width)   # left vertical
    top_level << straight_route(pdk, lc_h, rc_h, glayer2=gl_name, width=width)   # horizontal, edge-aligned
    top_level << straight_route(pdk, rc_v, pR,   glayer2=gl_name, width=width)   # right vertical

    return top_level, rc_h


def add_cm_labels(cm_in: Component, pdk: MappedPDK) -> Component:
    cm_in.unlock()

    psize = (0.35, 0.35)
    move_info = []

    # VIN
    vinlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    vinlabel.add_label(text="VIN", layer=pdk.get_glayer("met2_label"))
    move_info.append((vinlabel, cm_in.ports["base_left_IN_top_met_N"], None))

    # EN
    venlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    venlabel.add_label(text="EN", layer=pdk.get_glayer("met2_label"))
    move_info.append((venlabel, cm_in.ports["fet_left_multiplier_0_gate_N"], None))

    # VOUT 
    voutlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    voutlabel.add_label(text="VOUT", layer=pdk.get_glayer("met2_label"))
    move_info.append((voutlabel, cm_in.ports["base_right_OUT_top_met_N"], None))

    # VDD (well tie)
    vddlabel = rectangle(layer=pdk.get_glayer("met1_pin"), size=psize, centered=True).copy()
    vddlabel.add_label(text="VDD", layer=pdk.get_glayer("met1_label"))
    move_info.append((vddlabel, cm_in.ports["fet_left_tie_N_top_met_N"], None))

    # VSS (well tie)
    vsslabel = rectangle(layer=pdk.get_glayer("met1_pin"), size=psize, centered=True).copy()
    vsslabel.add_label(text="VSS", layer=pdk.get_glayer("met1_label"))
    move_info.append((vsslabel, cm_in.ports["base_bottom_welltie_S_top_met_S"], None))

    for comp, prt, alignment in move_info:
        alignment = ("c", "b") if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        cm_in.add(compref)

    return cm_in.flatten()


if __name__ == "__main__":
    selected_pdk = gf180
    comp = bias_stage(
        selected_pdk, num_cols=1, Width=10, Length=2, with_substrate_tap=False, show_netlist=False, add_labels=True
    )
    
    comp.name = "BIAS_STAGE"
    comp.show()
    # Write the current mirror layout to a GDS file
    comp.write_gds("GDS/bias_stage.gds")

    # Generate the netlist for the current mirror
    # print(comp.info["netlist"].generate_netlist())

    # DRC Checks
    drc_result = selected_pdk.drc_magic(comp, comp.name, output_file=Path("DRC/"))

    # LVS Checks
    netgen_lvs_result = selected_pdk.lvs_netgen(
        comp, comp.name, output_file_path=Path("LVS/"), copy_intermediate_files=True
    )
    