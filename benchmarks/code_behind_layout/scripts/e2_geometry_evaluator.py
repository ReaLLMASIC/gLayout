"""Trusted E2 geometry-only stage. No reference, EDA tool or SPICE is read."""
import argparse
import json
from pathlib import Path
import gdstk
from e2_mask_geometry import read_masks

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--gds", required=True)
p.add_argument("--output", required=True)
p.add_argument("--fidelity", choices=["geometry"], required=True)
a = p.parse_args()
out = Path(a.output)
meta = json.loads(Path("/trusted/meta.json").read_text())
library = gdstk.read_gds(a.gds)
top, = library.top_level()
if top.name != meta["top_cell"]:
    raise ValueError("Actual generated top differs from the frozen E2 target")
mask = read_masks(a.gds, meta["excluded_layer_datatypes"])
boxes = [row["bbox_in_grid_units"] for row in mask.summary["layers"].values()]
width = (max(v[2] for v in boxes)-min(v[0] for v in boxes))*mask.precision_um
height = (max(v[3] for v in boxes)-min(v[1] for v in boxes))*mask.precision_um
wirelength, area = 0., 0.
for (layer, datatype), polygons in mask.masks.items():
    if datatype != 20 or layer not in [67, 68, 69, 70, 71]:
        continue
    for polygon in polygons:
        lower, upper = polygon.bounding_box()
        dx, dy = upper[0]-lower[0], upper[1]-lower[1]
        wirelength += float(abs(dx-dy))
        area += float(polygon.area())
record = {"scope": "E2_geometry_only_no_gold_no_EDA_no_SPICE", "requested_fidelity": "geometry",
    "requested_fidelity_complete": True, "top_cell": top.name, "GDS_bytes": Path(a.gds).stat().st_size,
    "geometry": {"physical_mask_bbox_area_um2": width*height, "conductor_union_area_um2": area,
        "union_rectilinear_proxy_um": wirelength,
        "wirelength_definition": "Sum abs(bbox_width-bbox_height) over per-layer union conductor polygons; descriptive proxy, not net-aware routed length or a UGB prediction",
        "canonical_masks": mask.summary},
    "S1_or_S2_established": False, "reference_netlist_mounted": False,
    "physical_tool_calls": {"DRC": 0, "LVS": 0, "PEX": 0, "SPICE": 0}}
(out / "validation.json").write_text(json.dumps(record, indent=2, allow_nan=False)+"\n")
print(json.dumps(record), flush=True)
