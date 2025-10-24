from glayout import MappedPDK, sky130,gf180
from glayout import nmos, pmos, tapring,via_stack

from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory.components import text_freetype, rectangle

from glayout.routing import c_route,L_route,straight_route
from glayout.spice.netlist import Netlist

from glayout.util.port_utils import add_ports_perimeter,rename_ports_by_orientation
from glayout.util.comp_utils import evaluate_bbox, prec_center, prec_ref_center, align_comp_to_port
from glayout.util.snap_to_grid import component_snap_to_grid
from typing import Optional, Union 

###### Only Required for IIC-OSIC Docker
import os
import subprocess
from typing import ClassVar, Optional, Any, Union, Literal, Iterable, TypedDict
from pathlib import Path
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

import sys
sys.path.append('../../elementary/current_mirror/')

from current_mirror import current_mirror,add_cm_labels

comp = current_mirror(gf180)
# comp.pprint_ports()
comp = add_cm_labels(comp,gf180)
comp.name = "CM"
comp.show()
#print(comp.info['netlist'].generate_netlist())
print("...Running DRC...")
drc_result = gf180.drc_magic(comp, "CM")
## Klayout DRC
#drc_result = sky130.drc(comp)\n


    
print("...Running LVS...")
lvs_res=gf180.lvs_netgen(comp, "CM")