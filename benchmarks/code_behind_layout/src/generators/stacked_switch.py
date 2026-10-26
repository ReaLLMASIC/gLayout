"""Vertical complementary switch with two shared signal columns.

Placement and six explicit net paths differ from the vendor's horizontal TG.
Only MOS/via/PDK and disclosed basic terminal drawing are shared dependencies.
"""
import json
from pathlib import Path
from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos, pmos
from src.generators.terminal_access import expose, wire, via, pin, finish
from src.generators.stacked_switch_reference import DEFAULT


def build(output, sizing=None, separation=24., signal_width=.8):
    size = {**DEFAULT, **(sizing or {})}
    sky130.activate()
    top = Component("stacked_switch")
    remove = [v for k,v in sky130.glayers.items() if k.endswith(("_label","_pin"))]+[(64,44)]
    ncell = nmos(sky130,width=size["n_width"],length=size["length"],fingers=size["fingers"],
                 with_dummy=False,with_tie=True,with_dnwell=False).copy().remove_layers(remove,include_labels=True)
    pcell = pmos(sky130,width=size["p_width"],length=size["length"],fingers=size["fingers"],
                 with_dummy=False,with_tie=True).copy().remove_layers(remove,include_labels=True)
    lower, upper = top << ncell, top << pcell
    lower.movex(-lower.xmin)
    upper.movex(-upper.xmin)
    upper.movey(lower.ymax+separation-upper.ymin)
    n, p = expose(top,lower), expose(top,upper)
    # Aligning the left extents creates separate, continuous source and drain
    # columns without a crossbar or a general netlist-to-row compiler.
    for terminal in ("D","S"):
        wire(top,"met3",n[terminal],p[terminal],signal_width)
    mid = round((lower.ymax+upper.ymin)/2/.005)*.005
    endpoint = max(lower.xmax,upper.xmax)+4
    signals = {"OUT":(n["D"][0],mid+2),"IN":(n["S"][0],mid-2)}
    for net, location in signals.items():
        via(top,"met3","met4",location)
        wire(top,"met4",location,(endpoint,location[1]),signal_width)
        pin(top,net,(endpoint-1,location[1]))
    # Gates and bodies terminate on opposite ends of the vertical stack; equal
    # access-column x coordinates therefore never connect EN to ENB or VSS to VDD.
    ends = [("EN",n["G"],lower.ymin-4),("VSS",n["B"],lower.ymin-8),
            ("ENB",p["G"],upper.ymax+4),("VDD",p["B"],upper.ymax+8)]
    for net, start, height in ends:
        end = (start[0],round(float(height)/.005)*.005)
        wire(top,"met3",start,end,.6)
        via(top,"met3","met4",end)
        wire(top,"met4",end,(endpoint,end[1]),.8)
        pin(top,net,(endpoint-1,end[1]))
    output = Path(output)
    output.mkdir(parents=True,exist_ok=True)
    (output/"sizing.json").write_text(json.dumps(size,indent=2)+"\n")
    (output/"layout_intent.json").write_text(json.dumps({"placement":"vertical_complementary_pair",
        "vertical_separation_um":separation,"signal_columns":["source_IN","drain_OUT"],
        "terminal_access_dependency":"src/generators/terminal_access.py",
        "forbidden_dependencies_used":False},indent=2)+"\n")
    return finish(top,output)
