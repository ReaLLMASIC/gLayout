from pathlib import Path
from typing import Optional, Union
import os
import re
import subprocess


from glayout import MappedPDK, sky130, gf180


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

selected_pdk = gf180

# DRC
drc_result = selected_pdk.drc_magic("gds/top_new.gds", "TOP", output_file=Path("DRC/"))

# LVS
netgen_lvs_result = selected_pdk.lvs_netgen(
    "gds/top_new.gds", "TOP", netlist="gds/top_new.spice", output_file_path=Path("LVS/"), copy_intermediate_files=True
)