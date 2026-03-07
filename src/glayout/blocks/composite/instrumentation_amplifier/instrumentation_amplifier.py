# PDK import, components
from glayout import MappedPDK, sky130 , gf180
from gdsfactory.cell import cell
from gdsfactory import Component
from gdsfactory.components import text_freetype, rectangle
from typing import Dict, Any, Tuple

import os
import gdstk
import svgutils.transform as sg
import IPython.display
import ipywidgets as widgets
from gdsfactory import Component
from gdsfactory.port import Port
from gdsfactory.components import rectangle
from glayout import gf180
from glayout import nmos, pmos, tapring
from glayout.util.comp_utils import evaluate_bbox, prec_center, align_comp_to_port
from glayout import rename_ports_by_orientation
from glayout.util.port_utils import add_ports_perimeter,print_ports
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.spice.netlist import Netlist

# ROUTING
from glayout.routing.straight_route import straight_route
from glayout.routing.c_route import c_route

# VIAS import
from glayout import via_stack, via_array

import os
import subprocess

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

def bbox_wh(obj, padding=0.0):
    b = evaluate_bbox(obj, padding=padding)
    if b is None: raise ValueError("evaluate_bbox returned None")
    if len(b) == 2: return float(b[0]), float(b[1])
    if len(b) == 4: return float(b[2] - b[0]), float(b[3] - b[1])
    raise ValueError(f"unexpected bbox format: {b}")

# make tapring (automatic) for every pairs
def safe_tapring(pdk, obj, padding=0.6, sdlayer=None, **kwargs):
    w, h = bbox_wh(obj, padding=padding)
    min_gap_tap = pdk.get_grule("active_tap")["min_separation"]
    w = max(w, min_gap_tap + 0.05)
    h = max(h, min_gap_tap + 0.05)
    if sdlayer is not None:
        return tapring(pdk, enclosed_rectangle=(w, h), sdlayer=sdlayer, **kwargs)
    return tapring(pdk, enclosed_rectangle=(w, h), **kwargs)

# point reference to object for automatic routing (can be used)
def center_ref_to_obj(ref, obj):
    cx, cy = prec_center(obj)
    ref.movex(destination=-cx).movey(destination=-cy)
    return ref
# add ports for layouting
def export_ports_by_suffix(comp, ref, prefix):
    def add(newname, suffix):
        for k, p in ref.ports.items():
            if k.endswith(suffix):
                name = f"{prefix}_{newname}"
                if name not in comp.ports: comp.add_port(name, port=p)
                return
    add("gate_E", "gate_E"); add("gate_W", "gate_W")
    add("source_E", "source_E"); add("source_W", "source_W"); add("source_N", "source_N")
    add("drain_E", "drain_E"); add("drain_W", "drain_W"); add("drain_N", "drain_N"); add("drain_S", "drain_S")

# function to automatic route only if the two point that want to be connected is parallel. If not, this won't work,
def route_if_ports_exist(pdk, comp, refA, keyA, refB, keyB):
    if (keyA in refA.ports) and (keyB in refB.ports):
        comp << straight_route(pdk, refA.ports[keyA], refB.ports[keyB])

# BUILD PAIR BLOCK
def build_pair_block(name, pdk, fet_fun, cfg, kwargs, x_distance=5, tap=True, tap_padding=0.6, dnwell=False, export_ports=True, individual_tap=False):
    w, l, f, m = cfg["width"], cfg["length"], cfg["fingers"], cfg["multipliers"]
    dummy, tie, sd_rmult = cfg["dummy_1"], cfg["tie_layers1"], cfg["sd_rmult"]
    local_kwargs = dict(kwargs)
    if fet_fun == nmos: local_kwargs["with_dnwell"] = False
    manual_assembly = dnwell and individual_tap

    # Nested fet : helped if dnwell is needed and automatically centered to the NMOS for each pair
    def create_nested_fet_block(block_name, fet_width, fet_length, fet_fingers, fet_mult):
        sub_comp = Component(block_name)
        fet_ref = sub_comp << fet_fun(pdk, width=fet_width, length=fet_length, fingers=fet_fingers, multipliers=fet_mult, with_dummy=dummy, with_substrate_tap=False if manual_assembly else individual_tap, tie_layers=tie, sd_rmult=sd_rmult, **local_kwargs)
        sub_comp.add_ports(fet_ref.ports)
        if manual_assembly:
            inner_ring = safe_tapring(pdk, fet_ref, padding=0.6, sdlayer="n+s/d")
            inner_ref = sub_comp << inner_ring
            center_ref_to_obj(inner_ref, fet_ref)
            wb, hb = bbox_wh(inner_ring, padding=1.0)
            poly_dnwell = sub_comp.add_polygon([(-wb/2, -hb/2), (wb/2, -hb/2), (wb/2, hb/2), (-wb/2, hb/2)], layer=pdk.get_glayer("dnwell"))
            cx, cy = prec_center(fet_ref); poly_dnwell.move((cx, cy))
        return sub_comp
    
    comp = Component(name)
    block1 = create_nested_fet_block(f"{name}_blk1", w[0], l[0], f[0], m[0])
    r1 = comp << block1; r1.name = f"{name}_1"
    block2 = create_nested_fet_block(f"{name}_blk2", w[1], l[1], f[1], m[1])
    r2 = comp << block2; r2.name = f"{name}_2"
    compSep = gf180.util_max_metal_seperation()
    if cfg["placement"] == "horizontal": w1, _ = bbox_wh(block1, padding=0.0); r2.movex(compSep + w1 + x_distance)
    else: raise ValueError("placement must be horizontal")

    # make the tapring based on the safe_tapring function
    if tap:
        flat = comp.flatten(); ring = safe_tapring(pdk, flat, padding=tap_padding)
        ring_ref = comp << ring; center_ref_to_obj(ring_ref, flat)
        if not manual_assembly and not individual_tap:
            if "source_N" in r1.ports and "top_met_S" in ring_ref.ports: comp << straight_route(pdk, r1.ports["source_N"], ring_ref.ports["top_met_S"])
            if "source_N" in r2.ports and "top_met_S" in ring_ref.ports: comp << straight_route(pdk, r2.ports["source_N"], ring_ref.ports["top_met_S"])

    flat2 = comp.flatten(); cx, cy = prec_center(flat2)
    tie_pairs = []
    if name in ["NMOS_PAIR_INNER"]:
        tie_pairs = [("tie_S_array_row0_col0_top_met_E", "tie_S_array_row0_col0_top_met_W"), ("tie_N_array_row0_col0_top_met_E", "tie_N_array_row0_col0_top_met_W")]
    for k1, k2 in tie_pairs: route_if_ports_exist(pdk, comp, r1, k1, r2, k2)

    if ("multiplier_0_drain_N" in r1.ports) and ("tie_N_top_met_N" in r1.ports): comp << straight_route(pdk, r1.ports["multiplier_0_drain_N"], r1.ports["tie_N_top_met_N"])
    if ("multiplier_0_drain_N" in r2.ports) and ("tie_N_top_met_N" in r2.ports): comp << straight_route(pdk, r2.ports["multiplier_0_drain_N"], r2.ports["tie_N_top_met_N"])

    for rr in comp.references: rr.movex(-cx).movey(-cy)
    for poly in comp.polygons: poly.move((-cx, -cy))
    if export_ports: export_ports_by_suffix(comp, r1, "M1"); export_ports_by_suffix(comp, r2, "M2")
    return comp


def add_amplifier_labels(
    ina: Component,
    pdk: MappedPDK,
    ) -> Component:

    ina.unlock()

    psize = (0.5, 0.5)
    move_info = list()

    # VSS
    vsslabel = rectangle(layer=pdk.get_glayer("met3_pin"), size=psize, centered=True).copy()
    vsslabel.add_label(text="VSS", layer=pdk.get_glayer("met3_label"))
    move_info.append((vsslabel, ina.ports["VSS_TOPL_top_met_N"], None))
    move_info.append((vsslabel, ina.ports["VSS_BOTTOML_top_met_N"], None))
    move_info.append((vsslabel, ina.ports["VSS_TOPR_top_met_N"], None))
    move_info.append((vsslabel, ina.ports["VSS_BOTTOMR_top_met_N"], None))

    # VDD
    vddlabel = rectangle(layer=pdk.get_glayer("met3_pin"), size=psize, centered=True).copy()
    vddlabel.add_label(text="VDD", layer=pdk.get_glayer("met3_pin"))
    move_info.append((vddlabel, ina.ports["VDD_TOPL_top_met_N"], None))
    move_info.append((vddlabel, ina.ports["VDD_TOPR_top_met_N"], None))
    move_info.append((vddlabel, ina.ports["VDD_BOTTOML_top_met_S"], None))
    move_info.append((vddlabel, ina.ports["VDD_BOTTOMR_top_met_S"], None))

    # Output
    outputplabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    outputplabel.add_label(text="VOUTP", layer=pdk.get_glayer("met2_pin"))
    move_info.append((outputplabel, ina.ports["OUTP_top_met_E"], None))
    
    outputnlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    outputnlabel.add_label(text="VOUTN", layer=pdk.get_glayer("met2_pin"))
    move_info.append((outputnlabel, ina.ports["OUTN_top_met_E"], None))

    # Input
    inputplabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    inputplabel.add_label(text="VINP", layer=pdk.get_glayer("met2_pin"))
    move_info.append((inputplabel, ina.ports["INP_top_met_W"], None))
    
    inputnlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=psize, centered=True).copy()
    inputnlabel.add_label(text="VINN", layer=pdk.get_glayer("met2_pin"))
    move_info.append((inputnlabel, ina.ports["INN_top_met_W"], None))

    # Apply Labels (Standard Move)
    for comp, prt, alignment in move_info:
        alignment = ('c', 'b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        ina.add(compref)

    return ina.flatten()

def deep_update(default, user_input):
    if user_input is None:
        return default
    
    # Salin default agar tidak merubah data asli
    res = default.copy()
    
    for k, v in user_input.items():
        # Jika nilai adalah dictionary dan k ada di res, lakukan update dalam
        if isinstance(v, dict) and k in res and isinstance(res[k], dict):
            res[k] = deep_update(res[k], v)
        else:
            res[k] = v
    return res

@cell
def generate_ina(
    pdk: MappedPDK,
    CFG: Dict[str,Any] = None,
    x_distance: int = 5,
    row_gap: float = 6.0,
    bias_gap: float = 4.0,
    trunk_pitch_in: float =3.4,
    trunk_pitch_out: float =1.0,
    outpad_margin: float = 35.0,
    outer_keepout: float = 6.0,
    nmos_pair_outer_ring_padding: float = 2.2,
    bias_gate_route_dx: float = 25.0,
    c_route_extension: float = 6.0,
    vcm_dx: float = -20.0,
    vin_dx: float = 40.0,
    vout_dx: float = 40.0,
    pwr_params: Dict[str,Any] = None,
    nmos_kwargs: Dict[str,Any] = None,
    pmos_kwargs: Dict[str,Any] = None,
    **kwargs
    ) -> Component:

    pdk.activate()

    DEFAULT_CFG = {
        "pmos_pair": {"pdk": gf180, "placement": "horizontal", "width": (6, 6), "length": (3, 3), "fingers": (6, 6), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1},
        "pmos_bias": {"pdk": gf180, "placement": "horizontal", "width": (0.5, 0.5), "length": (6.9, 6.9), "fingers": (1, 1), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1},
        "nmos_pair": {"pdk": gf180, "placement": "horizontal", "width": (3, 3), "length": (3, 3), "fingers": (1, 1), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1},
        "nmos_mirror": {"pdk": gf180, "placement": "horizontal", "width": (0.5, 0.5), "length": (6.9, 6.9), "fingers": (1, 1), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1},
        "pmos_diode": {"pdk": gf180, "placement": "horizontal", "width": (0.5, 0.5), "length": (6.9, 6.9), "fingers": (1, 1), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1}
    }

    DEFAULT_PWR = {
        "trace_width": 2, "via_size": (2, 1), 
        "vdd": {"bridge_x": 12, "left_y_offsets": [-13, -23.2], "right_y_offsets": [2.5, -6.5, -9.5, -19.7]},
        "vss": {"left_x": -9, "right_x": 9, "y_coords": [6.0, -4.0, -14.0, -30.2, -31.5, -41.8, -70]}
    }

    DEFAULT_NMOS = {
        "with_tie": True, "with_dnwell": False, "sd_route_topmet": "met2", "gate_route_topmet": "met2", 
        "sd_route_left": True, "rmult": None, "gate_rmult": 1, "interfinger_rmult": 1, 
        "substrate_tap_layers": ("met2", "met1"), "dummy_routes": True
    }

    DEFAULT_PMOS = {
        "with_tie": True, "dnwell": False, "sd_route_topmet": "met2", "gate_route_topmet": "met2", 
        "sd_route_left": True, "rmult": None, "gate_rmult": 1, "interfinger_rmult": 1, 
        "substrate_tap_layers": ("met2", "met1"), "dummy_routes": True
    }

    # 2. Proses Merging (Update otomatis)
    cfg = deep_update(DEFAULT_CFG, CFG or {})
    pwr = deep_update(DEFAULT_PWR, pwr_params or {})
    nmos_kwargs = deep_update(DEFAULT_NMOS, nmos_kwargs or {})
    pmos_kwargs = deep_update(DEFAULT_PMOS, pmos_kwargs or {})

    PMOS_PAIR = build_pair_block("PMOS_PAIR", pdk, pmos, cfg["pmos_pair"], pmos_kwargs, x_distance=x_distance, tap=True, tap_padding=0.6, export_ports=True)
    NMOS_PAIR_INNER = build_pair_block("NMOS_PAIR_INNER", pdk, nmos, cfg["nmos_pair"], nmos_kwargs, x_distance=x_distance, tap=True, individual_tap=True, dnwell=True, tap_padding=nmos_pair_outer_ring_padding, export_ports=True)
    NMOS_PAIR = Component("NMOS_PAIR"); nmos_pair_inner_ref = NMOS_PAIR << NMOS_PAIR_INNER; nmos_pair_inner_ref.move((0, 0))
    for pname, p in nmos_pair_inner_ref.ports.items():
        if pname not in NMOS_PAIR.ports: NMOS_PAIR.add_port(pname, port=p)
    NMOS_MIRROR = build_pair_block("NMOS_MIRROR", pdk, nmos, cfg["nmos_mirror"], nmos_kwargs, x_distance=x_distance, tap=True, individual_tap=False, dnwell=False, tap_padding=0.6, export_ports=True)
    PMOS_DIODE = build_pair_block("PMOS_DIODE", pdk, pmos, cfg["pmos_diode"], {}, x_distance=x_distance, tap=True, tap_padding=0.6, export_ports=True)

    ALL_TOP = Component(name ="ALL_TOP")
    TOP = ALL_TOP 
    X_TRUNK = 0.0

    bias = pmos(pdk, width=cfg["pmos_bias"]["width"][0], length=cfg["pmos_bias"]["length"][0], fingers=cfg["pmos_bias"]["fingers"][0], multipliers=cfg["pmos_bias"]["multipliers"][0], with_dummy=cfg["pmos_bias"]["dummy_1"], with_substrate_tap=False, tie_layers=cfg["pmos_bias"]["tie_layers1"], sd_rmult=cfg["pmos_bias"]["sd_rmult"], **pmos_kwargs)
    bias_ref = TOP << bias; bias_ref.name = "PFET_BIAS"; bias_ref.movex(X_TRUNK - bias_ref.center[0]).movey(0)
    
    pmos_pair_ref = TOP << PMOS_PAIR; pmos_pair_ref.movex(X_TRUNK - pmos_pair_ref.center[0]).movey(bias_ref.ymin - bias_gap - (pmos_pair_ref.ymax - pmos_pair_ref.center[1]))
    nmos_pair_ref = TOP << NMOS_PAIR; nmos_pair_ref.movex(X_TRUNK - nmos_pair_ref.center[0]).movey(pmos_pair_ref.ymin - row_gap - (nmos_pair_ref.ymax - nmos_pair_ref.center[1]))
    mirror_ref = TOP << NMOS_MIRROR; mirror_ref.movex(X_TRUNK - mirror_ref.center[0]).movey(nmos_pair_ref.ymin - row_gap - (mirror_ref.ymax - mirror_ref.center[1]))
    diode_ref = TOP << PMOS_DIODE; diode_ref.movex(X_TRUNK - diode_ref.center[0]).movey(mirror_ref.ymin - row_gap - (diode_ref.ymax - diode_ref.center[1]))

    flat_top = TOP.flatten(); pad = pdk.get_grule("nwell", "active_diff")["min_enclosure"]
    outer = safe_tapring(pdk, flat_top, padding=pad + outer_keepout); outer_ref = TOP << outer; center_ref_to_obj(outer_ref, flat_top)

    # ===================================================================================
    # MAIN VIA PLACEMENT AND ROUTING
    # ===================================================================================
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    X_IN_P, X_IN_N = X_TRUNK - trunk_pitch_in / 2, X_TRUNK + trunk_pitch_in / 2
    X_OUT_P, X_OUT_N = X_TRUNK - trunk_pitch_out / 2, X_TRUNK + trunk_pitch_out / 2

    pfet1_src = pmos_pair_ref.ports["M1_source_E"]; pfet2_src = pmos_pair_ref.ports["M2_source_W"]; pfet1_drn = pmos_pair_ref.ports["M1_drain_E"]; pfet2_drn = pmos_pair_ref.ports["M2_drain_W"]
    dfet1_drn = diode_ref.ports["M1_drain_E"]; dfet2_drn = diode_ref.ports["M2_drain_W"]

    # PMOS bias
    TOP << straight_route(pdk, pfet1_drn, pfet2_drn)
    via_common_drn = TOP << viam2m3; via_common_drn.move((X_TRUNK, pfet1_drn.center[1]))
    y_bias_src = bias_ref.ports["source_E"].center[1]; via_bias_src = TOP << viam2m3; via_bias_src.move((X_TRUNK, y_bias_src))
    TOP << straight_route(pdk, via_common_drn.ports["top_met_N"], via_bias_src.ports["bottom_met_S"])

    bias_gate = bias_ref.ports["gate_W"]; via_bias_gate_array = TOP << via_array(pdk, "met2", "met3", size=(3, 1))
    via_bias_gate_array.move((bias_gate.center[0] - bias_gate_route_dx, bias_gate.center[1]))
    TOP << straight_route(pdk, bias_gate, via_bias_gate_array.ports["array_row0_col2_bottom_met_E"])

    # PMOS PAIR
    via_pmos_src_L = TOP << viam2m3; via_pmos_src_L.move((X_OUT_P, pfet1_src.center[1]))
    TOP << straight_route(pdk, pfet1_src, via_pmos_src_L.ports["bottom_met_W"])
    via_pmos_src_R = TOP << viam2m3; via_pmos_src_R.move((X_OUT_N, pfet2_src.center[1]))
    TOP << straight_route(pdk, pfet2_src, via_pmos_src_R.ports["bottom_met_W"])

    # NMOS MIRROR
    y_mirr_gate_L = mirror_ref.ports["M1_gate_W"].center[1]; y_mirr_gate_R = mirror_ref.ports["M2_gate_W"].center[1]
    via_mirr_gate_L = TOP << viam2m3; via_mirr_gate_L.move((X_OUT_P, y_mirr_gate_L))
    via_mirr_gate_R = TOP << viam2m3; via_mirr_gate_R.move((X_OUT_N, y_mirr_gate_R))
    TOP << straight_route(pdk, via_pmos_src_L.ports["top_met_N"], via_mirr_gate_L.ports["top_met_S"])
    TOP << straight_route(pdk, via_pmos_src_R.ports["top_met_N"], via_mirr_gate_R.ports["top_met_S"])
    TOP << straight_route(pdk, mirror_ref.ports["M1_gate_W"], via_mirr_gate_L.ports["bottom_met_W"])
    TOP << straight_route(pdk, mirror_ref.ports["M2_gate_W"], via_mirr_gate_R.ports["bottom_met_W"])

    # PMOS DIODE
    via_diode_drn_L = TOP << viam2m3; via_diode_drn_L.move((X_IN_P, dfet1_drn.center[1]))
    TOP << straight_route(pdk, dfet1_drn, via_diode_drn_L.ports["bottom_met_W"])
    via_diode_drn_R = TOP << viam2m3; via_diode_drn_R.move((X_IN_N, dfet2_drn.center[1]))
    TOP << straight_route(pdk, dfet2_drn, via_diode_drn_R.ports["bottom_met_W"])

    # PMOS PAIR GATE
    y_pmos_gate_ref = pmos_pair_ref.ports["M2_gate_W"].center[1]
    via_pmos_gate_L = TOP << viam2m3; via_pmos_gate_L.move((X_IN_P, y_pmos_gate_ref))
    via_pmos_gate_R = TOP << viam2m3; via_pmos_gate_R.move((X_IN_N, y_pmos_gate_ref))
    TOP << straight_route(pdk, via_pmos_gate_L.ports["top_met_N"], via_diode_drn_L.ports["top_met_S"])
    TOP << straight_route(pdk, via_pmos_gate_R.ports["top_met_N"], via_diode_drn_R.ports["top_met_S"])
    TOP << straight_route(pdk, pmos_pair_ref.ports["M2_gate_W"], via_pmos_gate_R.ports["bottom_met_W"])
    
    via_to_gate_PMOS_PAIR_L = TOP << viam2m3; via_to_gate_PMOS_PAIR_L.move((X_IN_P, pmos_pair_ref.ports["M1_gate_W"].center[1]))
    TOP << straight_route(pdk, pmos_pair_ref.ports["M1_gate_W"], via_to_gate_PMOS_PAIR_L.ports["bottom_met_E"])

    # NMOS PAIR
    nmos1_src = nmos_pair_ref.ports["M1_source_E"]; nmos2_src = nmos_pair_ref.ports["M2_source_W"]
    x_via_src_L = via_pmos_src_L.center[0]; x_via_src_R = via_pmos_src_R.center[0]
    via_nmos_src_L = TOP << viam2m3; via_nmos_src_L.move((x_via_src_L, nmos1_src.center[1]))
    via_nmos_src_R = TOP << viam2m3; via_nmos_src_R.move((x_via_src_R, nmos2_src.center[1]))
    TOP << straight_route(pdk, nmos1_src, via_nmos_src_L.ports["bottom_met_W"])
    TOP << straight_route(pdk, nmos2_src, via_nmos_src_R.ports["bottom_met_W"])

    nmos1_gate = nmos_pair_ref.ports["M1_gate_W"]; nmos2_gate = nmos_pair_ref.ports["M2_gate_W"]
    x_via_gate_L = via_pmos_gate_L.center[0]; x_via_gate_R = via_pmos_gate_R.center[0]
    via_nmos_gate_L = TOP << viam2m3; via_nmos_gate_L.move((x_via_gate_L, nmos1_gate.center[1]))
    via_nmos_gate_R = TOP << viam2m3; via_nmos_gate_R.move((x_via_gate_R, nmos2_gate.center[1]))
    TOP << straight_route(pdk, nmos1_gate, via_nmos_gate_L.ports["bottom_met_W"])
    TOP << straight_route(pdk, nmos2_gate, via_nmos_gate_R.ports["bottom_met_W"])

    # still NMOS pair, but also the via to input
    y_gap_center = (nmos_pair_ref.ymin + mirror_ref.ymax) / 2; track_sep = 2.0
    y_in_plus = y_gap_center + track_sep/2; y_in_minus = y_gap_center - track_sep/2
    x_in_L = via_nmos_gate_L.center[0]; x_in_R = via_nmos_gate_R.center[0]
    via_in_plus_start = TOP << viam2m3; via_in_plus_start.move((x_in_L, y_in_plus))
    via_in_minus_start = TOP << viam2m3; via_in_minus_start.move((x_in_R, y_in_minus))
    via_in_plus_end = TOP << viam2m3; via_in_plus_end.move((x_in_L - vin_dx, y_in_plus))
    via_in_minus_end = TOP << viam2m3; via_in_minus_end.move((x_in_R - vin_dx, y_in_minus))
    TOP << straight_route(pdk, via_in_plus_start.ports["bottom_met_W"], via_in_plus_end.ports["bottom_met_E"])
    TOP << straight_route(pdk, via_in_minus_start.ports["bottom_met_W"], via_in_minus_end.ports["bottom_met_E"])

    # still PMOS PAIR, but also the via to output
    y_gap_out = (pmos_pair_ref.ymin + nmos_pair_ref.ymax) / 2; y_out_plus = y_gap_out + track_sep/2; y_out_minus = y_gap_out - track_sep/2
    x_out_L = via_pmos_src_L.center[0]; x_out_R = via_pmos_src_R.center[0]
    via_out_plus = TOP << viam2m3; via_out_plus.move((x_out_L, y_out_plus))
    via_out_minus = TOP << viam2m3; via_out_minus.move((x_out_R, y_out_minus))
    via_out_plus_end = TOP << viam2m3; via_out_plus_end.move((x_out_L + vout_dx, y_out_plus))
    via_out_minus_end = TOP << viam2m3; via_out_minus_end.move((x_out_R + vout_dx, y_out_minus))
    TOP << straight_route(pdk, via_out_plus.ports["bottom_met_E"], via_out_plus_end.ports["bottom_met_W"])
    TOP << straight_route(pdk, via_out_minus.ports["bottom_met_E"], via_out_minus_end.ports["bottom_met_W"])

    # NMOS PAIR C routed to NMOS MIRROR
    TOP << c_route(pdk, nmos_pair_ref.ports["M1_drain_W"], mirror_ref.ports["M1_source_W"], extension=c_route_extension)
    TOP << c_route(pdk, nmos_pair_ref.ports["M2_drain_E"], mirror_ref.ports["M2_source_E"], extension=c_route_extension)

    # PMOS DIODE SOURCE AND THE VCM ROUTING
    d_src_L = diode_ref.ports["M1_source_E"]; d_src_R = diode_ref.ports["M2_source_W"]; d_gate_L = diode_ref.ports["M1_gate_E"]; d_gate_R = diode_ref.ports["M2_gate_W"]
    TOP << straight_route(pdk, d_src_L, d_src_R); TOP << straight_route(pdk, d_gate_L, d_gate_R)
    via_x_center = (d_src_L.center[0] + d_src_R.center[0]) / 2; y_src_level = d_src_L.center[1]; y_gate_level = d_gate_L.center[1]; y_mid_level = (mirror_ref.ymin + diode_ref.ymax) / 2
    via_1_src = TOP << viam2m3; via_1_src.move((via_x_center, y_src_level)); via_2_gate = TOP << viam2m3; via_2_gate.move((via_x_center, y_gate_level))
    via_3_mid = TOP << viam2m3; via_3_mid.move((via_x_center, y_mid_level))
    TOP << straight_route(pdk, via_3_mid.ports["top_met_S"], via_2_gate.ports["top_met_N"]); TOP << straight_route(pdk, via_2_gate.ports["top_met_S"], via_1_src.ports["top_met_N"])
    vcm_via = TOP << via_array(pdk, "met2", "met3", size=(2, 1)); vcm_via.move((via_x_center + vcm_dx, y_mid_level))
    if vcm_dx > 0: TOP << straight_route(pdk, via_3_mid.ports["bottom_met_E"], vcm_via.ports["array_row0_col0_bottom_met_W"])
    else: TOP << straight_route(pdk, via_3_mid.ports["bottom_met_W"], vcm_via.ports["array_row0_col1_bottom_met_E"])

    # ===================================================================================
    # POWER ROUTING (VERTICAL ONLY)
    # ===================================================================================
    viaarray = via_array(pdk, "met2", "met3", size=pwr["via_size"])
    trace_w = pwr["trace_width"]
    
    VDD1_a_via = TOP << viaarray; VDD1_a_via.move(bias_ref.ports["tie_N_array_row0_col0_top_met_E"].center)
    VDD2_via = TOP << viaarray; VDD2_via.move(bias_ref.ports["tie_S_array_row0_col0_top_met_E"].center)
    
    left_vdd_refs = []
    for y_off in pwr["vdd"]["left_y_offsets"]:
        v = TOP << viaarray; v.movex(VDD1_a_via.center[0]).movey(y_off); left_vdd_refs.append(v)
    VDD4_via = left_vdd_refs[-1]

    bias_src_port_1 = bias_ref.ports["multiplier_0_drain_W"]
    VDD1_b_via = TOP << viaarray; VDD1_b_via.move((VDD1_a_via.center[0], bias_src_port_1.center[1]))
    VDD1_c_via = TOP << viaarray; VDD1_c_via.move((pwr["vdd"]["bridge_x"], bias_src_port_1.center[1]))
    TOP << straight_route(pdk, VDD1_b_via.ports["array_row0_col0_bottom_met_W"], VDD1_c_via.ports["array_row0_col0_bottom_met_E"])

    y_anchor = VDD1_a_via.center[1]; x_right = VDD1_c_via.center[0]
    right_vdd_refs = []
    for y_off in pwr["vdd"]["right_y_offsets"]:
        v = TOP << viaarray; v.move((x_right, y_anchor + y_off)); right_vdd_refs.append(v)

    TOP << straight_route(pdk, VDD1_a_via.ports["top_met_N"], VDD4_via.ports["top_met_S"], width=trace_w)
    right_vdd_refs_sorted = sorted(right_vdd_refs, key=lambda v: v.center[1], reverse=True)
    TOP << straight_route(pdk, right_vdd_refs_sorted[0].ports["top_met_N"], right_vdd_refs_sorted[-1].ports["top_met_S"], width=trace_w)

    vss_l_vias = []; x_pos_l = pwr["vss"]["left_x"]
    for y_pos in pwr["vss"]["y_coords"]: v = TOP << viaarray; v.movex(x_pos_l).movey(y_pos); vss_l_vias.append(v)
    vss_l_vias.sort(key=lambda v: v.center[1], reverse=True)
    TOP << straight_route(pdk, vss_l_vias[0].ports["top_met_N"], vss_l_vias[-1].ports["top_met_S"], width=trace_w)

    vss_r_vias = []; x_pos_r = pwr["vss"]["right_x"]
    for y_pos in pwr["vss"]["y_coords"]: v = TOP << viaarray; v.movex(x_pos_r).movey(y_pos); vss_r_vias.append(v)
    vss_r_vias.sort(key=lambda v: v.center[1], reverse=True)
    TOP << straight_route(pdk, vss_r_vias[0].ports["top_met_N"], vss_r_vias[-1].ports["top_met_S"], width=trace_w)

    # ===================================================================================
    # AUTOMATIC PORTS & LABELS ADDITION
    # ===================================================================================
    
    # 1. VARIABLE MAPPING (User manual vars -> Auto vars)
    via_input_P = via_in_plus_end
    via_input_N = via_in_minus_end
    via_output_P = via_out_plus_end
    via_output_N = via_out_minus_end
    
    # VDD/VSS Mapping (Via)
    VDD5_via = right_vdd_refs_sorted[0]  # Top Right
    VDD8_via = right_vdd_refs_sorted[-1] # Bottom Right
    VSS1_via = vss_l_vias[0]   # Top Left
    VSS7_via = vss_l_vias[-1]  # Bottom Left
    VSS8_via = vss_r_vias[0]   # Top Right
    VSS14_via = vss_r_vias[-1] # Bottom Right
    
    VCM_via = vcm_via
    Vbias_via = via_bias_gate_array

    # 2. ADD PORTS
    ALL_TOP.add_ports(via_input_P.get_ports_list(), prefix="INP_")
    ALL_TOP.add_ports(via_input_N.get_ports_list(), prefix="INN_")
    ALL_TOP.add_ports(via_output_P.get_ports_list(), prefix="OUTP_")
    ALL_TOP.add_ports(via_output_N.get_ports_list(), prefix="OUTN_")

    ALL_TOP.add_ports(VDD1_a_via.get_ports_list(), prefix="VDD_TOPL_")
    ALL_TOP.add_ports(VDD5_via.get_ports_list(), prefix="VDD_TOPR_")
    ALL_TOP.add_ports(VDD4_via.get_ports_list(), prefix="VDD_BOTTOML_")
    ALL_TOP.add_ports(VDD8_via.get_ports_list(), prefix="VDD_BOTTOMR_")

    ALL_TOP.add_ports(VSS1_via.get_ports_list(), prefix="VSS_TOPL_")
    ALL_TOP.add_ports(VSS7_via.get_ports_list(), prefix="VSS_BOTTOML_")
    ALL_TOP.add_ports(VSS8_via.get_ports_list(), prefix="VSS_TOPR_")
    ALL_TOP.add_ports(VSS14_via.get_ports_list(), prefix="VSS_BOTTOMR_")

    ALL_TOP.add_ports(VCM_via.get_ports_list(), prefix="VCM_")
    ALL_TOP.add_ports(Vbias_via.get_ports_list(), prefix="VBIAS_")


    return component_snap_to_grid(rename_ports_by_orientation(ALL_TOP))

if __name__ == "__main__":
	comp = generate_ina(gf180)

	# comp.pprint_ports()

	comp = add_amplifier_labels(comp, gf180)

	comp.name = "instrumentation_amplifier"

	comp.write_gds('out_INA.gds')

	comp.show()

	print("...Running DRC...")

	drc_result = gf180.drc_magic(comp, "instrumentation_amplifier")

	drc_result = gf180.drc(comp)

