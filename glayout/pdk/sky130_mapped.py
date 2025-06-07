"""
Sky130 PDK implementation for Glayout.
"""

from pathlib import Path
from .mappedpdk import MappedPDK, SetupPDKFiles

# Layer definitions for Sky130
LAYER = {
    "met5": (68, 20),
    "via4": (67, 44),
    "met4": (66, 20),
    "via3": (65, 44),
    "met3": (64, 20),
    "via2": (63, 44),
    "met2": (62, 20),
    "via1": (61, 44),
    "met1": (60, 20),
    "mcon": (66, 44),
    "poly": (66, 20),
    "active": (65, 20),
    "n+s/d": (64, 20),
    "p+s/d": (64, 44),
    "nwell": (64, 20),
    "dnwell": (64, 44),
    "capmet": (89, 44),
    # Label layers
    "met5_label": (68, 10),
    "met4_label": (66, 10),
    "met3_label": (64, 10),
    "met2_label": (62, 10),
    "met1_label": (60, 10),
    "poly_label": (66, 10),
    "active_label": (65, 10),
}

# Generic layer mapping for Sky130
sky130_glayer_mapping = {
    "met5": "met5",
    "via4": "via4",
    "met4": "met4",
    "via3": "via3",
    "met3": "met3",
    "via2": "via2",
    "met2": "met2",
    "via1": "via1",
    "met1": "met1",
    "mcon": "mcon",
    "poly": "poly",
    "active_diff": "active",
    "active_tap": "active",
    "n+s/d": "n+s/d",
    "p+s/d": "p+s/d",
    "nwell": "nwell",
    "dnwell": "dnwell",
    "capmet": "capmet",
    # Pin layers
    "met5_pin": "met5_label",
    "met4_pin": "met4_label",
    "met3_pin": "met3_label",
    "met2_pin": "met2_label",
    "met1_pin": "met1_label",
    "poly_pin": "poly_label",
    "active_diff_pin": "active_label",
    # Label layers
    "met5_label": "met5_label",
    "met4_label": "met4_label",
    "met3_label": "met3_label",
    "met2_label": "met2_label",
    "met1_label": "met1_label",
    "poly_label": "poly_label",
    "active_diff_label": "active_label",
}

# PDK file paths
pdk_root = Path('/usr/bin/miniconda3/share/pdk/')
klayout_drc_file = Path(__file__).parent / "sky130_drc.lydrc"
lvs_schematic_ref_file = pdk_root / "sky130A" / "libs.ref" / "sky130_fd_sc_hd" / "spice" / "sky130_fd_sc_hd.spice"
lvs_setup_tcl_file = pdk_root / "sky130A" / "libs.tech" / "netgen" / "sky130_setup.tcl"
magic_drc_file = pdk_root / "sky130A" / "libs.tech" / "magic" / "sky130A.magicrc"
temp_dir = None

# Setup PDK files
pdk_files = SetupPDKFiles(
    pdk_root=pdk_root,
    klayout_drc_file=klayout_drc_file,
    lvs_schematic_ref_file=lvs_schematic_ref_file,
    lvs_setup_tcl_file=lvs_setup_tcl_file,
    magic_drc_file=magic_drc_file,
    temp_dir=temp_dir,
    pdk='sky130'
).return_dict_of_files()

# Create the Sky130 PDK instance
sky130_mapped_pdk = MappedPDK(
    name="sky130",
    glayers=sky130_glayer_mapping,
    models={
        'nfet': 'sky130_fd_pr__nfet_01v8',
        'pfet': 'sky130_fd_pr__pfet_01v8',
        'mimcap': 'sky130_fd_pr__cap_mim_m3_1'
    },
    layers=LAYER,
    pdk_files=pdk_files,
)

# Configure PDK settings
sky130_mapped_pdk.gds_write_settings.precision = 5e-9
sky130_mapped_pdk.cell_decorator_settings.cache = False
sky130_mapped_pdk.gds_write_settings.flatten_invalid_refs = False 