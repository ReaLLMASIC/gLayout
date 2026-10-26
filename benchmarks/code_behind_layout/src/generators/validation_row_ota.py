"""A validation-only row of five devices with explicit global metal-4 buses.

Authored separately from the evaluated OTA assemblies and training compiler.
MOS and terminal-access primitives are shared. A row with global buses is also
a high-level strategy used by an evaluated assembly; this is disclosed ancestry,
not evidence that the validation source has no conceptual overlap.
"""
from collections import defaultdict
from pathlib import Path
from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos,pmos
from src.generators.terminal_access import expose,wire,via,pin,finish
from src.generators.validation_row_ota_reference import DEFAULT,PORTS


def build(output,sizing=None,device_gap=24.,bus_pitch=3.,bus_width=.8):
    z = {**DEFAULT, **(sizing or {})}; sky130.activate()
    top = Component('validation_row_ota')
    remove = [v for k,v in sky130.glayers.items() if k.endswith(('_label','_pin'))]+[(64,44)]
    devices = {}; cursor = 0.
    for name,kind,group in [('sink','n','tail'),('plus','n','input'),('diode','p','load'),('minus','n','input'),('load','p','load')]:
        maker = nmos if kind=='n' else pmos
        well = {'with_dnwell':False} if kind=='n' else {'dnwell':False}
        cell = maker(sky130,width=z[group+'_width'],length=z[group+'_length'],fingers=z[group+'_fingers'],
                     with_dummy=False,with_tie=True,**well).copy().remove_layers(remove,include_labels=True)
        ref = top << cell
        ref.move(origin=(ref.xmin,ref.ymin),destination=(cursor,0.))
        devices[name] = expose(top,ref); cursor = float(ref.xmax)+device_gap
    nets = defaultdict(list)
    # Fixed circuit connections; placement and routing never derive this graph
    # from an extracted netlist or a full target implementation.
    connections = {
        'sink':('tail','VBIAS','GND','GND'),
        'plus':('mirror','VP','tail','GND'),
        'diode':('mirror','mirror','VDD','VDD'),
        'minus':('VOUT','VN','tail','GND'),
        'load':('VOUT','mirror','VDD','VDD')}
    for name,bindings in connections.items():
        for terminal,net in zip('DGSB',bindings):nets[net].append(devices[name][terminal])
    ceiling = round((float(top.ymax)+10)/.005)*.005
    left = min(point[0] for points in nets.values() for point in points)-4
    right = cursor-device_gap+4
    tracks = {}
    for index,net in enumerate(['GND','VBIAS','tail','VP','mirror','VN','VOUT','VDD']):
        y = ceiling+index*bus_pitch; tracks[net] = y
        wire(top,'met4',(left,y),(right,y),bus_width)
        for point in nets[net]:
            landing = (point[0],y)
            wire(top,'met3',point,landing,.6); via(top,'met3','met4',landing)
        if net in PORTS:pin(top,net,(left+1,y))
    output = Path(output); output.mkdir(parents=True,exist_ok=True)
    return finish(top,output)
