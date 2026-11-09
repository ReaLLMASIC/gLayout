"""Standalone original-generator LVS pins; conductor geometry is unchanged."""

import math

PINS = {
    "current_mirror_nfet": {
        "VREF": "fet_A_drain_N",
        "VOUT": "fet_B_drain_N",
        "VSS": "fet_A_source_E",
        "B": "welltie_S_top_met_S",
    },
    "current_mirror_pfet": {
        "VREF": "fet_A_drain_N",
        "VOUT": "fet_B_drain_N",
        "VSS": "fet_A_source_E",
        "B": "welltie_S_top_met_S",
    },
    "diff_pair": {
        "VP": "br_multiplier_0_gate_S",
        "VN": "bl_multiplier_0_gate_S",
        "VDD1": "tl_multiplier_0_drain_N",
        "VDD2": "tr_multiplier_0_drain_N",
        "VTAIL": "bl_multiplier_0_source_S",
        "B": "tap_N_top_met_S",
    },
    "flipped_voltage_follower": {
        "VIN": "A_multiplier_0_gate_N",
        "Ib": "A_drain_bottom_met_N",
        "VOUT": "A_source_bottom_met_N",
        "VBULK": "B_tie_N_top_met_N",
    },
    "transmission_gate": {
        "VIN": "N_multiplier_0_source_E",
        "VOUT": "P_multiplier_0_drain_W",
        "VSS": "N_tie_S_top_met_N",
        "VCC": "P_tie_S_top_met_S",
        "VGP": "P_multiplier_0_gate_E",
        "VGN": "N_multiplier_0_gate_E",
    },
    "diff_pair_ibias": {
        "VP": "br_multiplier_0_gate_S",
        "VN": "bl_multiplier_0_gate_S",
        "VDD1": "tl_multiplier_0_drain_N",
        "VDD2": "tr_multiplier_0_drain_N",
        "IBIAS": "ibias_A_drain_E",
        "VSS": "ibias_purposegndport",
        "B": "tap_N_top_met_S",
    },
    "low_voltage_cmirror": {
        "IBIAS1": "M_1_A_drain_bottom_met_N",
        "IBIAS2": "M_2_A_drain_bottom_met_N",
        "IOUT1": "M_3_A_multiplier_0_drain_N",
        "IOUT2": "M_4_A_multiplier_0_drain_N",
        "GND": "M_3_B_tie_N_top_met_N",
    },
    "differential_to_single_ended_converter": {
        "VIN": "ptopAB_L_gate_W",
        "VOUT": "ptopAB_L_drain_W",
        "VSS": "2L2Rsrcvia_top_met_N",
        "VSS2": "ptopAB_R_source_W",
    },
    "nmos_narrow": {
        "D": "drain_N",
        "G": "gate_S",
        "S": "source_W",
        "B": "tie_N_top_met_S",
    },
    "pmos_narrow": {
        "D": "drain_N",
        "G": "gate_S",
        "S": "source_W",
        "B": "tie_N_top_met_S",
    },
}
BULKS = {
    "current_mirror_nfet": "B",
    "current_mirror_pfet": "B",
    "diff_pair": "B",
    "diff_pair_ibias": "B",
    "flipped_voltage_follower": "VBULK",
    "transmission_gate": "VSS",
    "low_voltage_cmirror": "GND",
    "nmos_narrow": "B",
    "pmos_narrow": "B",
}


def add_pins(comp, name, pdk):
    comp = comp.flatten()
    if name == "opamp":
        allowed = {"VDD", "GND", "DIFFPAIR_BIAS", "VP", "VN", "CS_BIAS", "VOUT"}
        for label in list(comp._cell.labels):
            if label.text.upper() not in allowed:
                comp._cell.remove(label)
        comp.add_label("GND", position=(0, 0), layer=(3, 251))
        return comp
    for label in list(comp._cell.labels):
        comp._cell.remove(label)
    for net, portname in PINS[name].items():
        port = comp.ports[portname]
        x, y = port.center
        angle = math.radians(port.orientation)
        x -= 0.001 * math.cos(angle)
        y -= 0.001 * math.sin(angle)
        metal = pdk.layer_to_glayer(port.layer)
        comp.add_label(net, position=(x, y), layer=pdk.get_glayer(metal + "_label"))
    if name == "differential_to_single_ended_converter":
        from glayout.pdk.finfet import polygons_by_layer

        for points in polygons_by_layer(comp).get((1, 0), []):
            import numpy as np

            comp.add_label(
                "VSS", position=np.asarray(points).mean(axis=0), layer=(1, 251)
            )
    if name in BULKS:
        comp.add_label(BULKS[name], position=(0, 0), layer=(3, 251))
    return comp
