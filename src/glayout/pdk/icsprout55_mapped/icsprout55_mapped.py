"""
usage: from glayout.pdk.icsprout55_mapped import icsprout55_mapped_pdk
"""

from pathlib import Path
import os

from ..mappedpdk import MappedPDK
from .icsprout55_grules import grulesobj

# Layer definitions from ICsprout 55nm Open Source PDK:
# icsprout55-pdk/techfile/icsprout55.layermap
LAYER = {
    "metaltop": (103, 1),
    "via5": (113, 1),
    "metal5": (85, 1),
    "via4": (94, 1),
    "metal4": (84, 1),
    "via3": (93, 1),
    "metal3": (83, 1),
    "via2": (92, 1),
    "metal2": (82, 1),
    "via1": (91, 1),
    "metal1": (81, 1),
    "contact": (72, 1),
    "poly2": (41, 1),
    "comp": (2, 1),
    "nplus": (52, 1),
    "pplus": (53, 1),
    "nwell": (9, 1),
    "lvpwell": (388, 12),
    "dnwell": (7, 1),
    "dualgate": (27, 1),
    "sab": (71, 1),
    "esd": (24, 0),
    "res_mk": (262, 12),
    "CAP_MK": (140, 1),
    "drc_bjt": (195, 1),
    "lvs_bjt": (195, 12),
    "MIM_L_MK": (271, 12),
    "fusetop": (141, 1),
    "lvtn": (50, 1),
    "lvtp": (51, 1),
    "hvtn": (54, 1),
    "hvtp": (55, 1),
    "nat": (44, 1),
    "v5_xtor": (112, 1),
    # _Label Layer Definitions (datatype 6 in icsprout55.layermap)
    "metaltop_label": (103, 6),
    "metal5_label": (85, 6),
    "metal4_label": (84, 6),
    "metal3_label": (83, 6),
    "metal2_label": (82, 6),
    "metal1_label": (81, 6),
    "poly2_label": (41, 6),
    "comp_label": (2, 6),
}

icsprout55_glayer_mapping = {
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

icsprout55_valid_bjt_sizes = {
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
icsprout55_lydrc_file_path = _HERE / "icsprout55.drc"
lvs_schematic_ref_file = _HERE / "icsprout55_stdcells.spice"
lvs_deck_dir = _HERE / "lvs"
pdk_root = Path(os.getenv("PDK_ROOT", str(lvs_deck_dir)))

pdk_files = {
    "pdk_root": pdk_root,
    "klayout_drc_file": icsprout55_lydrc_file_path,
    "lvs_schematic_ref_file": lvs_schematic_ref_file,
    "lvs_setup_tcl_file": None,
    "magic_drc_file": None,
    "temp_dir": None,
}

icsprout55_mapped_pdk = MappedPDK(
    name="icsprout55",
    glayers=icsprout55_glayer_mapping,
    models={
        "nfet": "nm1p2_svt_lp",
        "pfet": "pm1p2_svt_lp",
        "mimcap": "cap_mim_2f0fF",
    },
    layers=LAYER,
    pdk_files=pdk_files,
    grules=grulesobj,
    valid_bjt_sizes=icsprout55_valid_bjt_sizes,
)

# Configure the grid size and GDS write precision (1nm grid matching ICsprout55 dbu=0.001)
icsprout55_mapped_pdk.gds_write_settings.precision = 1 * 10**-9
icsprout55_mapped_pdk.cell_decorator_settings.cache = False
if "grid_size" in type(icsprout55_mapped_pdk).model_fields:
    icsprout55_mapped_pdk.grid_size = 0.001
