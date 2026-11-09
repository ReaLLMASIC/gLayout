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
icsprout55_lylvs_file_path = _HERE / "icsprout55.lvs"
lvs_schematic_ref_file = _HERE / "icsprout55_stdcells.spice"
lvs_deck_dir = _HERE / "lvs"
pdk_root = Path(os.getenv("PDK_ROOT", str(lvs_deck_dir)))

# Official ICsprout 55nm LLULP1225/1233 ngspice simulation model library and device catalog
ICSPROUT55_NGSPICE_DIR = _HERE / "ngspice"
ICSPROUT55_SPICE_LIB = ICSPROUT55_NGSPICE_DIR / "ICsprout_55LLULP1225_V1p1_hsp.lib"
ICSPROUT55_SPICE_MODELS = {
    "mos": {
        "nfet_svt": "nm1p2_svt_lp",
        "pfet_svt": "pm1p2_svt_lp",
        "nfet_lvt": "nm1p2_lvt_lp",
        "pfet_lvt": "pm1p2_lvt_lp",
        "nfet_hvt": "nm1p2_hvt_lp",
        "pfet_hvt": "pm1p2_hvt_lp",
        "nfet_nat_1p2": "nnat1p2_lp",
        "nfet_2p5": "nm2p5_lp",
        "pfet_2p5": "pm2p5_lp",
        "nfet_nat_2p5": "nnat2p5_lp",
        "nfet_3p3": "nmod3p3_lp",
        "pfet_3p3": "pmod3p3_lp",
        "nfet_nat_3p3": "nnatod3p3_lp",
    },
    "bjt": {
        "pnp_1p2_2x": "vpnp1p2_2x_lp",
        "pnp_1p2_5x": "vpnp1p2_5x_lp",
        "pnp_1p2_10x": "vpnp1p2_10x_lp",
        "npn_1p2_2x": "vnpn1p2_2x_lp",
        "npn_1p2_5x": "vnpn1p2_5x_lp",
        "npn_1p2_10x": "vnpn1p2_10x_lp",
        "pnp_2p5_2x": "vpnp2p5_2x_lp",
        "pnp_2p5_5x": "vpnp2p5_5x_lp",
        "pnp_2p5_10x": "vpnp2p5_10x_lp",
        "npn_2p5_2x": "vnpn2p5_2x_lp",
        "npn_2p5_5x": "vnpn2p5_5x_lp",
        "npn_2p5_10x": "vnpn2p5_10x_lp",
    },
    "dio": {
        "ndio_svt": "dio_1p2_np_pw_lp",
        "pdio_svt": "dio_1p2_pp_nw_lp",
        "ndio_lvt": "dio_1p2_np_pw_lvt_lp",
        "pdio_lvt": "dio_1p2_pp_nw_lvt_lp",
        "ndio_hvt": "dio_1p2_np_pw_hvt_lp",
        "pdio_hvt": "dio_1p2_pp_nw_hvt_lp",
        "ndio_2p5": "dio_2p5_np_pw_lp",
        "pdio_2p5": "dio_2p5_pp_nw_lp",
    },
    "res": {
        "ppo_2t": "re_ppo_2t",
        "ppo_3t": "re_ppo_3t",
        "ppo_sab_2t": "re_ppo_sab_2t",
        "ppo_sab_3t": "re_ppo_sab_3t",
        "npo_2t": "re_npo_2t",
        "npo_3t": "re_npo_3t",
        "npo_sab_2t": "re_npo_sab_2t",
        "npo_sab_3t": "re_npo_sab_3t",
    },
    "cap": {
        "mimcap": "cap_mim_2f0fF",
        "mom_2t": "mom_2t",
        "mom_3t": "mom_3t",
        "var_1p2": "var1p2_npd_nw_lp",
        "var_2p5": "var2p5_npd_nw_lp",
    },
    "corners": {
        "mos": ("tt_mos", "ff_mos", "ss_mos", "fnsp_mos", "snfp_mos", "mc_mos"),
        "bjt": ("tt_bjt", "ff_bjt", "ss_bjt", "mc_bjt"),
        "dio": ("tt_dio", "ff_dio", "ss_dio", "mc_dio"),
        "res": ("tt_res", "ff_res", "ss_res", "mc_res"),
        "var": ("tt_var", "ff_var", "ss_var", "mc_var"),
        "mom": ("tt_mom", "ff_mom", "ss_mom", "mc_mom"),
    },
}

pdk_files = {
    "pdk_root": pdk_root,
    "klayout_drc_file": icsprout55_lydrc_file_path,
    "lvs_schematic_ref_file": lvs_schematic_ref_file,
    "lvs_setup_tcl_file": _HERE / "netgen" / "ics55.tcl",
    "magic_drc_file": _HERE / "magic" / "ics55.magicrc",
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
