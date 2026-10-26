"""Triangular common-source assembly with a short right output spine.

The PMOS reference/load sit above an offset NMOS signal branch. Each circuit
net path is explicit; no existing amplifier or graph-to-layout compiler is used.
"""
import json
from pathlib import Path
from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos,pmos
from src.generators.terminal_access import expose,wire,via,pin,finish
from src.generators.common_source_reference import DEFAULT


def build(output,sizing=None,pair_gap=36.,stage_gap=24.,output_width=.8):
    size={**DEFAULT,**(sizing or {})}
    sky130.activate();top=Component("common_source_stage")
    remove=[v for k,v in sky130.glayers.items() if k.endswith(("_label","_pin"))]+[(64,44)]
    ncell=nmos(sky130,width=size["n_width"],length=size["length"],fingers=size["fingers"],
               with_dummy=False,with_tie=True,with_dnwell=False).copy().remove_layers(remove,include_labels=True)
    pcell=pmos(sky130,width=size["p_width"],length=size["length"],fingers=size["fingers"],
               with_dummy=False,with_tie=True).copy().remove_layers(remove,include_labels=True)
    reference,load,signal=top<<pcell,top<<pcell,top<<ncell
    reference.move(origin=(reference.xmin,reference.ymin),destination=(0,0))
    load.move(origin=(load.xmin,load.ymin),destination=(reference.xmax+pair_gap,0))
    signal.move(origin=signal.center,destination=((reference.xmax+load.xmin)/2,-stage_gap-ncell.ysize/2))
    r,l,n=expose(top,reference),expose(top,load),expose(top,signal)
    # The bias track is above the output track in the inter-stage channel.
    bias_y=round((signal.ymax+reference.ymin)/2/.005)*.005+4
    output_y=bias_y-8
    for start in (r["D"],r["G"],l["G"]):
        stop=(start[0],bias_y);wire(top,"met3",start,stop,.6);via(top,"met3","met4",stop)
    left=-12.;right=float(load.xmax)+4
    wire(top,"met4",(left,bias_y),(l["G"][0],bias_y),.8);pin(top,"PBIAS",(left+1,bias_y))
    for start in (n["D"],l["D"]):
        stop=(start[0],output_y);wire(top,"met3",start,stop,output_width);via(top,"met3","met4",stop)
    wire(top,"met4",(n["D"][0],output_y),(right,output_y),output_width);pin(top,"OUT",(right-1,output_y))
    top_y=round((max(reference.ymax,load.ymax)+8)/.005)*.005
    for start in (r["S"],r["B"],l["S"],l["B"]):
        stop=(start[0],top_y);wire(top,"met3",start,stop,.6);via(top,"met3","met4",stop)
    wire(top,"met4",(left,top_y),(right,top_y),.8);pin(top,"VDD",(left+1,top_y))
    floor=round((signal.ymin-6)/.005)*.005
    for start in (n["S"],n["B"]):
        stop=(start[0],floor);wire(top,"met3",start,stop,.6);via(top,"met3","met4",stop)
    wire(top,"met4",(left,floor),(n["S"][0]+2,floor),.8);pin(top,"VSS",(left+1,floor))
    gate=(n["G"][0],floor-6)
    wire(top,"met3",n["G"],gate,.6);via(top,"met3","met4",gate)
    wire(top,"met4",(left,gate[1]),gate,.8);pin(top,"VIN",(left+1,gate[1]))
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/"sizing.json").write_text(json.dumps(size,indent=2)+"\n")
    return finish(top,output)
