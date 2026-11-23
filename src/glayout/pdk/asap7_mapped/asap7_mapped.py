"""ASAP7 r1p7 mapping. Native physical units (um), not the 4x/10x APR GDS.

Dimensions: local ASAP7 design rule manual, sections 2 and 3. The open-source
verification module is a POC subset; the licensed Calibre decks remain the
signoff authority. Importing this module requires no proprietary tools/PDK.
"""

from glayout.pdk.mappedpdk import MappedPDK
from glayout.pdk.finfet import FinFETTechnology, FinFETFlavor

layers = {
    "nwell": (1, 0),
    "pwell": (3, 0),
    "fin": (2, 0),
    "slvt": (97, 0),
    "lvt": (98, 0),
    "sramvt": (110, 0),
    "poly": (16, 0),
    "active_tap": (100, 20),
    "dnwell": (100, 21),
    "capmet": (100, 10),
    "gcut": (10, 0),
    "active_diff": (11, 0),
    "n+s/d": (12, 0),
    "p+s/d": (13, 0),
    "lig": (16, 0),
    "lisd": (17, 0),
    "mcon": (18, 0),
    "sdt": (88, 0),
}
for i, number in enumerate((19, 20, 30, 40, 50), 1):
    layers[f"met{i}"] = (number, 0)
    layers[f"met{i}_pin"] = (number, 251)
    layers[f"met{i}_label"] = (number, 2)
for i, number in enumerate((21, 25, 35, 45), 1):
    layers[f"via{i}"] = (number, 0)

rules = {}


def rule(a, b, **values):
    rules.setdefault(a, {})[b] = values


rule("poly", "poly", min_width=0.020, min_separation=0.030, pitch=0.054)
rule("fin", "fin", width=0.007, min_width=0.007, pitch=0.027)
rule("active_diff", "active_diff", min_width=0.027, min_separation=0.054)
for i in range(1, 6):
    width, sep = (0.024, 0.024) if i <= 3 else (0.036, 0.024)
    rule(f"met{i}", f"met{i}", min_width=width, min_separation=sep)
for i in range(1, 5):
    width = 0.018 if i <= 3 else 0.024
    rule(f"via{i}", f"via{i}", width=width, min_separation=0.024)
    for metal in (i, i + 1):
        enc = 0.005 if metal < 4 else (0.009 if i <= 3 else 0.006)
        rule(f"via{i}", f"met{metal}", min_enclosure=enc)
rule("mcon", "mcon", width=0.018, min_separation=0.024)
rule("mcon", "met1", min_enclosure=0.003)

# Generic primitive contracts: poly denotes gate local interconnect (LIG).
# Actual gate stripes use FinFETTechnology.gate_layer=(7,0).
rule("poly", "active_diff", overhang=0.054)
rule("poly", "mcon", min_enclosure=0.002, min_separation=0.005)
rule("active_diff", "mcon", min_enclosure=0.003)
rule("active_tap", "active_tap", min_width=0.024, min_separation=0.054)
rule("active_tap", "active_diff", min_separation=0.054)
rule("active_tap", "mcon", min_enclosure=0.003)
for select in ("n+s/d", "p+s/d"):
    rule(select, select, min_width=0.054, min_separation=0.054)
    rule(select, "active_diff", min_enclosure=0.054)
    rule(select, "active_tap", min_enclosure=0.027)
for well in ("pwell", "nwell", "dnwell"):
    rule(well, well, min_width=0.108, min_separation=0.108)
    rule(well, "active_tap", min_enclosure=0.054, min_separation=0.054)
    rule(well, "active_diff", min_enclosure=0.027, min_separation=0.027)
rule("pwell", "dnwell", min_enclosure=0.054)
rule("capmet", "capmet", min_separation=0.108, capmettop=(50, 0), capmetbottom=(40, 0))
for metal in ("met4", "met5"):
    rule(metal, "capmet", min_enclosure=0.0)

# Reverse mapping should prefer the generic routable alias for LIG.
layers["poly"] = layers.pop("poly")

asap7_mapped_pdk = MappedPDK(
    name="asap7",
    layers=layers,
    glayers={key: key for key in layers},
    models={"nfet": "nmos_rvt", "pfet": "pmos_rvt"},
    finfet_flavors={
        "rvt": FinFETFlavor("nmos_rvt", "pmos_rvt"),
        "lvt": FinFETFlavor("nmos_lvt", "pmos_lvt", "lvt"),
        "slvt": FinFETFlavor("nmos_slvt", "pmos_slvt", "slvt"),
        "sram": FinFETFlavor("nmos_sram", "pmos_sram", "sramvt"),
    },
    grules=rules,
    pdk_files={},
    valid_bjt_sizes={},
    finfet=FinFETTechnology(
        fin_pitch=0.027,
        fin_width=0.007,
        gate_pitch=0.054,
        gate_length=0.020,
        gate_extension=0.054,
        active_gate_extension=0.027,
        well_enclosure=0.054,
    ),
)
asap7_mapped_pdk.gds_write_settings.precision = 0.5e-9
asap7_mapped_pdk.cell_decorator_settings.cache = False

if "grid_size" in type(asap7_mapped_pdk).model_fields:
    asap7_mapped_pdk.grid_size = 0.0005
