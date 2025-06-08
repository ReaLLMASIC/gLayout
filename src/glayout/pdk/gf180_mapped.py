"""
GF180 PDK implementation for Glayout.
"""

from pathlib import Path
from .mappedpdk import MappedPDK, SetupPDKFiles

# Layer definitions for GF180
LAYER = {
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
    "CAP_MK": (117, 5),
    # Label layers
    "metal5_label": (81, 10),
    "metal4_label": (46, 10),
    "metal3_label": (42, 10),
    "metal2_label": (36, 10),
    "metal1_label": (34, 10),
    "poly2_label": (30, 10),
    "comp_label": (22, 10),
}

# Generic layer mapping for GF180
gf180_glayer_mapping = {
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
    # Pin layers
    "met5_pin": "metal5_label",
    "met4_pin": "metal4_label",
    "met3_pin": "metal3_label",
    "met2_pin": "metal2_label",
    "met1_pin": "metal1_label",
    "poly_pin": "poly2_label",
    "active_diff_pin": "comp_label",
    # Label layers
    "met5_label": "metal5_label",
    "met4_label": "metal4_label",
    "met3_label": "metal3_label",
    "met2_label": "metal2_label",
    "met1_label": "metal1_label",
    "poly_label": "poly2_label",
    "active_diff_label": "comp_label",
}

# PDK file paths
pdk_root = Path('/usr/bin/miniconda3/share/pdk/')
klayout_drc_file = Path(__file__).parent / "gf180mcu_drc.lydrc"
lvs_schematic_ref_file = pdk_root / "gf180mcuC" / "libs.ref" / "gf180mcu_osu_sc_9T" / "spice" / "gf180mcu_osu_sc_9T.spice"
lvs_setup_tcl_file = pdk_root / "gf180mcuC" / "libs.tech" / "netgen" / "gf180mcuC_setup.tcl"
magic_drc_file = pdk_root / "gf180mcuC" / "libs.tech" / "magic" / "gf180mcuC.magicrc"
temp_dir = None

# Setup PDK files
pdk_files = SetupPDKFiles(
    pdk_root=pdk_root,
    klayout_drc_file=klayout_drc_file,
    lvs_schematic_ref_file=lvs_schematic_ref_file,
    lvs_setup_tcl_file=lvs_setup_tcl_file,
    magic_drc_file=magic_drc_file,
    temp_dir=temp_dir,
    pdk='gf180'
).return_dict_of_files()

# Create the GF180 PDK instance
gf180_mapped_pdk = MappedPDK(
    name="gf180",
    glayers=gf180_glayer_mapping,
    models={
        'nfet': 'nfet_03v3',
        'pfet': 'pfet_03v3',
        'mimcap': 'mimcap_1p0fF'
    },
    layers=LAYER,
    pdk_files=pdk_files,
)

# Configure PDK settings
gf180_mapped_pdk.gds_write_settings.precision = 5e-9
gf180_mapped_pdk.cell_decorator_settings.cache = False 