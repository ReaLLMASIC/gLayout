"""
usage: from glayout.pdk.openrpdk28_mapped import openrpdk28_mapped_pdk
"""

from pathlib import Path
import os

from ..mappedpdk import MappedPDK
from .openrpdk28_grules import grulesobj

# Layer definitions from OpenRPDK28 mask/KLayout tables:
# OpenRPDK28/docs/masks.md and OpenRPDK28/libraries/tech/klayout/openrpdk28.lyp
LAYER = {
    "metaltop": (53, 0),
    "via5": (82, 0),
    "metal5": (81, 0),
    "via4": (41, 0),
    "metal4": (46, 0),
    "via3": (40, 0),
    "metal3": (42, 0),
    "via2": (38, 0),
    "metal2": (36, 0),
    "via1": (35, 0),
    "metal1": (34, 0),
    "contact": (33, 0),
    "poly2": (30, 0),
    "comp": (22, 0),
    "nplus": (32, 0),
    "pplus": (31, 0),
    "nwell": (21, 0),
    "lvpwell": (204, 0),
    "dnwell": (12, 0),
    "dualgate": (55, 0),
    "sab": (49, 0),
    "esd": (24, 0),
    "res_mk": (110, 5),
    "CAP_MK": (117, 5),
    "drc_bjt": (127, 5),
    "lvs_bjt": (118, 5),
    "MIM_L_MK": (117, 10),
    "fusetop": (75, 0),
    "lvtn": (125, 0),
    "mvtn": (189, 4),
    "mvtp": (195, 4),
    "nat": (5, 0),
    "v5_xtor": (112, 1),
    # _Label Layer Definitions
    "metaltop_label": (53, 10),
    "metal5_label": (81, 10),
    "metal4_label": (46, 10),
    "metal3_label": (42, 10),
    "metal2_label": (36, 10),
    "metal1_label": (34, 10),
    "poly2_label": (30, 10),
    "comp_label": (22, 10),
}

openrpdk28_glayer_mapping = {
    "met5": "metal5",
    "via4": "via4",
    "met4": "metal4",
    "via3": "via3",
    "met3": "metal3",
    "via2": "via2",
    "met2": "metal2",
    "via1": "via1",
    "met1": "metal1",
    "mcon": "contact",
    "poly": "poly2",
    "active_diff": "comp",
    "active_tap": "comp",
    "n+s/d": "nplus",
    "p+s/d": "pplus",
    "nwell": "nwell",
    "pwell": "lvpwell",
    "dnwell": "dnwell",
    "capmet": "CAP_MK",
    # BJT layers
    "drc_bjt": "drc_bjt",
    "lvs_bjt": "lvs_bjt",
    # _pin layer mapping
    "met5_pin": "metal5_label",
    "met4_pin": "metal4_label",
    "met3_pin": "metal3_label",
    "met2_pin": "metal2_label",
    "met1_pin": "metal1_label",
    "poly_pin": "poly2_label",
    "active_diff_pin": "comp_label",
    # _label layer mapping
    "met5_label": "metal5_label",
    "met4_label": "metal4_label",
    "met3_label": "metal3_label",
    "met2_label": "metal2_label",
    "met1_label": "metal1_label",
    "poly_label": "poly2_label",
    "active_diff_label": "comp_label",
}

openrpdk28_valid_bjt_sizes = {
    "npn": [
        (0.54, 2.0),
        (0.54, 4.0),
        (0.54, 8.0),
        (0.54, 16.0),
        (5.0, 5.0),
        (10.0, 10.0),
    ],
    "pnp": [
        (0.42, 5.0),
        (0.42, 10.0),
        (5.0, 0.42),
        (5.0, 5.0),
        (10.0, 0.42),
        (10.0, 10.0),
    ],
}

_HERE = Path(__file__).resolve().parent
openrpdk28_lydrc_file_path = _HERE / "openrpdk28.drc"
lvs_schematic_ref_file = _HERE / "openrpdk28_osu_sc_9T.spice"
lvs_deck_dir = _HERE / "lvs"
pdk_root = Path(os.getenv("PDK_ROOT", str(lvs_deck_dir)))

pdk_files = {
    "pdk_root": pdk_root,
    "klayout_drc_file": openrpdk28_lydrc_file_path,
    "lvs_schematic_ref_file": lvs_schematic_ref_file,
    "lvs_setup_tcl_file": None,
    "magic_drc_file": None,
    "temp_dir": None,
}

openrpdk28_mapped_pdk = MappedPDK(
    name="openrpdk28",
    glayers=openrpdk28_glayer_mapping,
    models={
        "nfet": "nfet_03v3",
        "pfet": "pfet_03v3",
        "mimcap": "cap_mim_2f0fF",
    },
    layers=LAYER,
    pdk_files=pdk_files,
    grules=grulesobj,
    valid_bjt_sizes=openrpdk28_valid_bjt_sizes,
)

# Configure the grid size and GDS write precision (1nm grid matching OpenRPDK28 dbu=0.001)
openrpdk28_mapped_pdk.gds_write_settings.precision = 1 * 10**-9
openrpdk28_mapped_pdk.cell_decorator_settings.cache = False
if "grid_size" in type(openrpdk28_mapped_pdk).model_fields:
    openrpdk28_mapped_pdk.grid_size = 0.001
