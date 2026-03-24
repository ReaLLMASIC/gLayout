from glayout import MappedPDK, sky130, gf180
from glayout import nmos, pmos, tapring, via_stack

# from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory.components import text_freetype, rectangle
from pathlib import Path

from glayout.routing import c_route, L_route, straight_route
from glayout.spice.netlist import Netlist

from glayout.util.port_utils import add_ports_perimeter, rename_ports_by_orientation
from glayout.util.comp_utils import (
    evaluate_bbox,
    prec_center,
    prec_ref_center,
    align_comp_to_port,
)
from glayout.util.snap_to_grid import component_snap_to_grid
from typing import Optional, Union


from cm_v import current_mirror_base
from cm_sb import self_biased_cascode_current_mirror
from cm_rc import regulated_cascode_current_mirror
from input import input_stage
from bias import bias_stage

###### Only Required for IIC-OSIC Docker
import os
import subprocess

# Run a shell, source .bashrc, then printenv
cmd = 'bash -c "source ~/.bashrc && printenv"'
result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
env_vars = {}
for line in result.stdout.splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        env_vars[key] = value

# Now, update os.environ with these
os.environ.update(env_vars)



# @validate_arguments
def rec_dnwell(
    pdk: MappedPDK,
    Width: float = 1,
    Length: Optional[float] = 1,
    with_tie: Optional[bool] = True,
    with_dummy: Optional[bool] = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    show_netlist: Optional[bool] = False,
    add_labels: bool = True,
    **kwargs,
) -> Component:
    """An instantiable self biased casoded current mirror that returns a Component object."""

    pdk.activate()
    maxmet_sep = pdk.util_max_metal_seperation()

    # Create the component
    top_level = Component(name="rec_nwell")
    top_level.name = "rec_nwell"
    Length = Length if Length is not None else pdk.get_grule("poly")["min_width"]
    top_ref = prec_ref_center(top_level)

    snap = pdk.snap_to_2xgrid
    center = top_level.center

    rec=rectangle(layer=pdk.get_glayer("dnwell"), size=(30,115), centered=True)
    rec_ref = prec_ref_center(rec)
    #rec_ref.move(center).movex(36.56 + 8 * pdk.util_max_metal_seperation())
    top_level.add(rec_ref)
    # # -------------------------------------------------------------------------
    # # CREATING THE VANILLA CURRENT MIRROR STAGE
    # # -------------------------------------------------------------------------
    # print("Creating Vanilla Current Mirror ...")

    # VCM = current_mirror_base(
    #     pdk,
    #     num_cols=1,
    #     Length=1,
    #     Width=4,
    #     device="nfet",
    #     with_substrate_tap=False,
    #     add_labels=False,
    # )
    # vcm_ref = prec_ref_center(VCM)
    # vcm_ref.move(center).movex(36.56 + 4 * pdk.util_max_metal_seperation()
    # ).movey(-81.12 / 2)

    # top_level.add(vcm_ref)
    # top_level.add_ports(vcm_ref.get_ports_list(), prefix="vcm_")

    # # -------------------------------------------------------------------------
    # # CREATING THE SELF-BIASED CURRENT MIRROR STAGE
    # # -------------------------------------------------------------------------
    # print("Creating Self-Biased Current Mirror ...")

    # SBCM = self_biased_cascode_current_mirror(
    #     pdk, num_cols=1, Length=1, Width=4, device="nfet", add_labels=False
    # )
    # sbcm_ref = prec_ref_center(SBCM)
    # sbcm_ref.move(center).movex(36.56 + 4 * pdk.util_max_metal_seperation()
    # )

    # top_level.add(sbcm_ref)
    # top_level.add_ports(sbcm_ref.get_ports_list(), prefix="sbcm_")

    # # -------------------------------------------------------------------------
    # # CREATING THE REGULATED CASCODE CURRENT MIRROR STAGE
    # # -------------------------------------------------------------------------
    # print("Creating Regulated Cascoded Current Mirror ...")

    # RCCM = regulated_cascode_current_mirror(
    #     pdk, num_cols=2, Length=1, Width=4, device="nfet", show_netlist=False, add_labels=False
    # )
    # rccm_ref = prec_ref_center(RCCM)
    # rccm_ref.move(center).movex(36.56 + 4 * pdk.util_max_metal_seperation()
    # ).movey(+81.12 / 2)

    # top_level.add(rccm_ref)
    # top_level.add_ports(rccm_ref.get_ports_list(), prefix="rccm_")
 
    # top_level.add_padding(
    #     layers=(pdk.get_glayer("dnwell"),),
    #     default=pdk.get_grule("pwell", "dnwell")["min_enclosure"],
    #     )
  
    core = top_level.copy()  # so we don't mutate while measuring
    core_flat = core.flatten()  # include all placed children

    xmin, xmax = core_flat.xmin, core_flat.xmax
    ymin, ymax = core_flat.ymin, core_flat.ymax

    core_w = xmax - xmin
    core_h = ymax - ymin

    cx = snap((xmin + xmax) / 2)
    cy = snap((ymin + ymax) / 2)

    tap_separation = pdk.get_grule("dnwell", "active_tap")["min_separation"]
    tap_encloses = (
        (snap(4 * tap_separation + core_w)),
        (snap(4 * tap_separation + core_h)),
    )
    # subtap_enclosure = (
    #         2.5 * (subtap_sep + interdigitized_fets.xmax),
    #         2.5 * (subtap_sep + interdigitized_fets.ymax),
    #     )

    ringtoadd = top_level << tapring(
        pdk,
        enclosed_rectangle=tap_encloses,
        sdlayer="p+s/d",
        horizontal_glayer= "met1",
        vertical_glayer = "met1",
    )
    ringtoadd.move((cx, cy))

    top_level = component_snap_to_grid(rename_ports_by_orientation(top_level))
    return top_level



if __name__ == "__main__":
    selected_pdk = gf180
    comp = rec_dnwell(selected_pdk)
    
    comp.name = "DNWell Rect"
    comp.show()
    # Write the current mirror layout to a GDS file
    comp.write_gds("GDS/deep_nwell_rect.gds")

    # DRC Checks
    drc_result = selected_pdk.drc_magic(comp, comp.name, output_file=Path("DRC/"))