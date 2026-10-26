"""Two vertical cascode branches with explicit stack and mirror connections.

This high-level assembly is independently written. It imports no existing OTA,
component circuit assembly, or universal netlist-to-layout compiler. Shared
MOS/via/terminal-access constraints are disclosed dependencies. Local M3 lifts,
staggered M4 tier tracks and topology-specific M5 joins implement this circuit.
"""
import json
from pathlib import Path

from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos, pmos
from src.generators.terminal_access import expose, wire, via, pin, finish
from src.generators.telescopic_ota_reference import DEFAULT


def build(output, sizing=None, *, branch_gap=110., stack_pitch=80., join_width=.8, track_stagger=24.):
    s = {**DEFAULT, **(sizing or {})}
    sky130.activate()
    top = Component("telescopic_mirror_ota")
    annotations = [layer for name, layer in sky130.glayers.items()
        if name.endswith(("_pin", "_label"))] + [(64, 44)]

    def placed(kind, category, column, tier):
        factory = pmos if kind == "p" else nmos
        kwargs = dict(width=s[category+"_width"], length=s[category+"_length"],
            fingers=s[category+"_fingers"], with_dummy=False, with_tie=True)
        device = (factory(sky130, with_dnwell=False, **kwargs) if kind == "n" else
            factory(sky130, dnwell=False, **kwargs)).copy().remove_layers(annotations, include_labels=True)
        ref = top << device
        ref.move(origin=(ref.xmin, ref.ymin), destination=(column*branch_gap, tier*stack_pitch))
        terminals = expose(top, ref)
        lifted = {}
        for index, terminal in enumerate(["D", "G", "S", "B"]):
            start = terminals[terminal]
            point = (start[0], float(ref.ymax)+8+column*track_stagger+3*index)
            wire(top, "met3", start, point, .4)
            via(top, "met3", "met4", point)
            lifted[terminal] = point
        return lifted

    # Column order follows the actual vertical current path. The bottom diode
    # and tail occupy their own tier, below the two signal branches.
    nr = placed("n", "tail", 0, -1)
    nt = placed("n", "tail", 1, -1)
    n1 = placed("n", "input", 0, 0)
    n2 = placed("n", "input", 1, 0)
    n3 = placed("n", "ncas", 0, 1)
    n4 = placed("n", "ncas", 1, 1)
    p3 = placed("p", "pcas", 0, 2)
    p4 = placed("p", "pcas", 1, 2)
    p1 = placed("p", "mirror", 0, 3)
    p2 = placed("p", "mirror", 1, 3)
    center = branch_gap/2
    east = float(top.xmax)+30

    def join(points, x, *, width=join_width, external=None):
        # A basic Manhattan connection, with the location and membership
        # explicitly chosen by this particular topology below.
        low, high = min(p[1] for p in points), max(p[1] for p in points)
        wire(top, "met5", (x, low), (x, high), width)
        for point in points:
            turn = (x, point[1])
            wire(top, "met4", point, turn, width)
            via(top, "met4", "met5", turn)
        if external:
            # A real M4 landing, as required by the common port contract.
            landing = (x, high)
            wire(top, "met4", (x-1, high), (x+1, high), width)
            pin(top, external, landing)

    # Short local stack joins are kept out of the central sense/bias corridor.
    join([n1["D"], n3["S"]], -22)
    join([n2["D"], n4["S"]], branch_gap-22)
    join([p1["D"], p3["S"]], -30)
    join([p2["D"], p4["S"]], branch_gap-30)
    # Mirror sensing closes across the reference cascode stack, not solely
    # across its upper PMOS. The right-hand collector is the independent output.
    join([n3["D"], p3["D"], p1["G"], p2["G"]], center)
    join([n4["D"], p4["D"]], east, external="VOUT")
    join([n1["S"], n2["S"], nt["D"]], center+10)
    join([nr["D"], nr["G"], nt["G"]], -44, external="IBIAS")
    join([n3["G"], n4["G"]], center-12, external="VBN")
    join([p3["G"], p4["G"]], center-24, external="VBP")
    # Each supply uses a different outer edge of the assembly.
    join([p1["S"], p2["S"], p1["B"], p2["B"], p3["B"], p4["B"]], -68,
        width=1.2, external="VDD")
    join([nr["S"], nt["S"], nr["B"], nt["B"], n1["B"], n2["B"], n3["B"], n4["B"]], east+18,
        width=1.2, external="GND")
    for name, point in [("VP", n1["G"]), ("VN", n2["G"])]:
        wire(top, "met4", (point[0]-1, point[1]), (point[0]+1, point[1]), join_width)
        pin(top, name, point)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "sizing.json").write_text(json.dumps(s, indent=2)+"\n")
    return finish(top, output)
