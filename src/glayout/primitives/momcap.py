"""Custom interdigitated M3 MOM capacitor with M2 terminal bars.

Capacitance is a nominal edge-length model, NOT a characterized ASAP7 model.
The 100/10 recognition marker is gLayout metadata, not a fabrication mask.
"""

import math
from glayout.backend import Component
from glayout.spice import Netlist
from glayout.primitives.finfet import _rect, _ports

MOM_MARKER = (100, 10)
MOM_PITCH = 0.072
MOM_WIDTH = 0.028
MOM_END_GAP = 0.054
MOM_FF_PER_UM = 0.1


def momcap(pdk, size=(1.0, 1.0), fingers=None):
    if pdk.finfet is None:
        raise ValueError("MOM demo requires a FinFET PDK")
    if any(not math.isfinite(v) or v <= 0 for v in size):
        raise ValueError("MOM dimensions must be finite and positive")
    count = (
        max(2, math.floor((size[0] - MOM_WIDTH) / MOM_PITCH) + 1)
        if fingers is None
        else fingers
    )
    if isinstance(count, bool) or not isinstance(count, int) or count < 2:
        raise ValueError("MOM capacitor requires at least two fingers")
    length = max(0.216, pdk.snap_to_2xgrid(size[1]))
    pdk.activate()
    comp = Component()
    xmax = (count - 1) * MOM_PITCH
    for i in range(count):
        x = i * MOM_PITCH
        y0 = -0.014 if i % 2 == 0 else MOM_END_GAP
        y1 = length - MOM_END_GAP if i % 2 == 0 else length + 0.014
        _rect(comp, pdk.get_glayer("met3"), x - 0.014, y0, x + 0.014, y1)
        y = 0 if i % 2 == 0 else length
        _rect(comp, pdk.get_glayer("via2"), x - 0.009, y - 0.009, x + 0.009, y + 0.009)
    for name, y in [("V1", 0), ("V2", length)]:
        bounds = (-0.024, y - 0.014, xmax + 0.024, y + 0.014)
        _rect(comp, pdk.get_glayer("met2"), *bounds)
        _ports(comp, name + "_", bounds, pdk.get_glayer("met2"))
        comp.add_label(name, position=(0, y), layer=pdk.get_glayer("met2_label"))
    _rect(comp, MOM_MARKER, -0.024, -0.014, xmax + 0.024, length + 0.014)
    value = (count - 1) * (length - 2 * MOM_END_GAP) * MOM_FF_PER_UM * 1e-15
    comp.info["momcap"] = {"fingers": count, "length": length, "capacitance": value}
    comp.info["netlist"] = Netlist(
        circuit_name="MOMCAP",
        nodes=["V1", "V2"],
        source_netlist=".subckt {circuit_name} {nodes}\nC0 V1 V2 "
        + f"{value:.12g}"
        + "\n.ends {circuit_name}",
    )
    from dataclasses import asdict

    comp.info["finfet_technology"] = asdict(pdk.finfet)
    pdk.finfet.validate(comp)
    return comp


def legacy_momcap(pdk, size=(1.0, 1.0)):
    """MOM implementation of the existing top_met/bottom_met cap interface."""
    from glayout.primitives.via_gen import via_stack

    c = momcap(pdk, size=size)
    for label in list(c._cell.labels):
        c._cell.remove(label)
    length = c.info["momcap"]["length"]
    xmax = (c.info["momcap"]["fingers"] - 1) * MOM_PITCH
    for name, net, y, metal in [
        ("bottom_met", "V2", 0, "met4"),
        ("top_met", "V1", length, "met5"),
    ]:
        v = via_stack(pdk, "met2", metal)
        margin = max(0.108, (v.xmax - v.xmin) / 2 + 0.054)
        x = -margin if net == "V2" else xmax + margin
        r = c << v
        r.move((x, y))
        _rect(
            c,
            pdk.get_glayer("met2"),
            min(x, 0) - 0.014,
            y - 0.014,
            max(x, xmax) + 0.014,
            y + 0.014,
        )
        c.add_ports(
            r.get_ports_list(prefix="top_met_"),
            prefix=name.replace("_met", "") + "_landing_",
        )
        bounds = (
            r.ports["top_met_W"].x,
            r.ports["top_met_S"].y,
            r.ports["top_met_E"].x,
            r.ports["top_met_N"].y,
        )
        _ports(c, name + "_", bounds, pdk.get_glayer(metal))
    return c


def legacy_momcap_array(pdk, rows, columns, size, rmult=1, **kwargs):
    from glayout.util.comp_utils import prec_array
    from glayout.routing.straight_route import straight_route

    unit = legacy_momcap(pdk, size)
    c = Component()
    array = c << prec_array(unit, rows, columns, spacing=(0.216, 0.216))
    c.add_ports(array.get_ports_list())
    for row in range(rows):
        for col in range(columns - 1):
            for prefix, metal in [("top_met", "met5"), ("bottom_met", "met4")]:
                a = c.ports[f"row{row}_col{col}_{prefix}_E"]
                b = c.ports[f"row{row}_col{col+1}_{prefix}_W"]
                c << straight_route(
                    pdk, a, b, glayer1=metal, glayer2=metal, width=0.048
                )
    for row in range(rows - 1):
        for col, prefix, metal in [
            (0, "bottom_met", "met4"),
            (columns - 1, "top_met", "met5"),
        ]:
            a = c.ports[f"row{row}_col{col}_{prefix}_N"]
            b = c.ports[f"row{row+1}_col{col}_{prefix}_S"]
            c << straight_route(pdk, a, b, glayer1=metal, glayer2=metal, width=0.048)
    # Expose the bottom-plate (V2, met4) landing on row0_col0_top_met_E so
    # opamp_twostage's L_route(hglayer='met4') connects to plate V2 while its
    # c_route(e2glayer='met5') to row{rows-1}_col0_top_met_N connects to plate V1.
    if "row0_col0_bottom_met_E" in c.ports:
        p = c.ports["row0_col0_bottom_met_E"].copy()
        p.name = "row0_col0_top_met_E"
        c.ports["row0_col0_top_met_E"] = p
    nl = Netlist(circuit_name="MOM_ARRAY", nodes=["V1", "V2"])
    for _ in range(rows * columns):
        nl.connect_netlist(unit.info["netlist"], [])
    c.info["netlist"] = nl
    return c.flatten()
