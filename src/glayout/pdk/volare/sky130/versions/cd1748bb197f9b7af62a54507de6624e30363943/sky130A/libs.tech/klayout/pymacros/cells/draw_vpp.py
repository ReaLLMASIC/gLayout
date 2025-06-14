# Copyright 2022 Mabrains LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

########################################################################################################################
## VPP CAP Pcells Generators for Klayout of skywater130
########################################################################################################################


import os
from .globals import *
import gdsfactory as gf


gds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),"fixed_devices/VPP" )


def draw_vpp(layout, device_name):
    '''
    drawing VPP Capacitors devices 
    '''
 
    if device_name in VPP_CAP_DEV :       
        layout.read(f"{gds_path}/{device_name}.gds")
        cell_name = device_name
    else:
        cell_name = device_name
    return layout.cell(cell_name)
    

