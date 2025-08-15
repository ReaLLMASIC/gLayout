"""
usage: from ihp130_mapped import ihp130_mapped_pdk
"""

from ..ihp130_mapped.ihp130_grules import grulesobj
from ..mappedpdk import MappedPDK, SetupPDKFiles
from pathlib import Path
import os

# Layer definitions for IHP 130nm BiCMOS Open Source PDK
# See: IHP Layer Table (GDS number and datatype) https://ihp-open-pdk-docs.readthedocs.io/en/latest/layout_rules/02_layer_table.html

LAYER = {
    # Active (diffusion)
    "activ":            (1,   0),
    # Poly gates
    "gatpoly":          (5,   0),
    # Source/drain implants
    "nsd":              (7,   0),
    "nsd_block":        (7,  21),
    "nsd_pin":          (7,   2),
    "psd":              (14,  0),
    "psd_pin":          (14,  2),
    # Well implants
    "nwell":            (31,  0),
    "nwell_pin":        (31,  2),
    "pwell":            (46,  0),
    "pwell_pin":        (46,  2),
    # Contacts
    "cont":             (6,   0),
    "cont_pin":         (6,   2),
    # Metal layers and vias
    "via1":             (19,  0),
    "metal1":           (8,   0),
    "via2":             (29,  0),
    "metal2":           (10,  0),
    "via3":             (49,  0),
    "metal3":           (30,  0),
    "via4":             (66,  0),
    "metal4":           (50,  0),
    "metal5":           (67,  0),
    # MIM capacitor
    "mim":              (36,  0),
    # LVS reference
    "gatpoly_pin":      (5,   2),
    "activ_pin":        (1,   2),
    "metal1_pin":       (8,   2),
    "metal1_label":     (8,   25),
    "metal2_pin":       (10,  2),
    "metal2_label":     (10,  25),
    "metal3_pin":       (30,  2),
    "metal3_label":     (30,  25),
    "metal4_pin":       (50,  2),
    "metal4_label":     (50,  25),
    "metal5_pin":       (67,  2),
    "metal5_label":     (67,  25),
}

# Generic-to-IHP layer name mapping
ihp130_glayer_mapping = {
    # Metals and vias
    "met5":       "metal5",
    "via4":       "via4",
    "met4":       "metal4",
    "via3":       "via3",
    "met3":       "metal3",
    "via2":       "via2",
    "met2":       "metal2",
    "via1":       "via1",
    "met1":       "metal1",
    # Contacts & active
    "mcon":       "cont",
    "active_diff":   "activ",
    "active_tap":    "activ",
    # Poly
    "poly":       "gatpoly",
    # Implant
    "n+s/d":      "nsd",
    "p+s/d":      "psd",
    "nwell":      "nwell",
    "pwell":      "pwell",
    # Capacitor
    "capmet":     "mim",
    # _pin layer ampping
    "met5_pin": "metal5_pin",
    "met4_pin": "metal4_pin",
    "met3_pin": "metal3_pin",
    "met2_pin": "metal2_pin",
    "met1_pin": "metal1_pin",
    "poly_pin": "gatpoly_pin",
    "active_diff_pin": "activ_pin",
    # _label layer mapping
    "met5_label": "metal5_label",
    "met4_label": "metal4_label",
    "met3_label": "metal3_label",
    "met2_label": "metal2_label",
    "met1_label": "metal1_label",
    "poly_label": "gatpoly_pin",
    "active_diff_label": "activ_pin",
}

ip130_lydrc_file_path = Path(__file__).resolve().parent / "ihp130_drc.lydrc"

if os.getenv('PDK_ROOT') is None:
    raise EnvironmentError("PDK_ROOT environment variable is not set.")
else:
    pdk_root = Path(os.getenv('PDK_ROOT'))

#ip130_lydrc_file_path = pdk_root / "libs.tech" / "klayout" / "tech" / "drc" / "sg13g2_minimal.lydrc"

# lvs_schematic_ref_file = Path(__file__).resolve().parent / "ihp130_lvs.spice"
# magic_drc_file = pdk_root / "libs.tech" / "magic" / "ihp130.magicrc"
# lvs_setup_tcl_file = pdk_root / "libs.tech" / "netgen" / "ihp130_setup.tcl"

lvs_schematic_ref_file = None
magic_drc_file = None ## Checkout the magic DRC file path in IIC-OSIC Dockers PDK folder
lvs_setup_tcl_file = None
temp_dir = None

pdk_files = SetupPDKFiles(
    pdk_root=pdk_root,
    klayout_drc_file=ip130_lydrc_file_path,
    lvs_schematic_ref_file=lvs_schematic_ref_file,
    lvs_setup_tcl_file=lvs_setup_tcl_file,
    magic_drc_file=magic_drc_file,
    temp_dir=temp_dir,
    pdk='ihp130'
).return_dict_of_files()

# Create the mapped PDK object
ihp130_mapped_pdk = MappedPDK(
    name="ihp130",
    glayers=ihp130_glayer_mapping,
    models={ ## Checkout these models in IIC-OSIC Dockers Xschem Netlist
        'nfet': 'sg13_lv_nmos',
        'pfet': 'sg13_lv_pmos',
        'mimcap': 'cap_cmim',
    },
    layers=LAYER,
    pdk_files=pdk_files,
    grules=grulesobj,
)

# Configure GDS write precision and cell decorator cache
ihp130_mapped_pdk.gds_write_settings.precision = 1e-9 # 1nm precision , Check this setting with PDk documentration later
ihp130_mapped_pdk.cell_decorator_settings.cache = False
