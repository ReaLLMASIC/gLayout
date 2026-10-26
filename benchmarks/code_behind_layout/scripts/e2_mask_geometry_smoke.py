"""Software fixtures for exact E2 geometry dedup; no physical measurements."""
import json
from pathlib import Path
import sys

import gdstk

sys.path.insert(0, "/work")
from src.e2_mask_geometry import first_duplicate, read_masks, same_masks

out = Path.cwd()
exclude = [(68, 16), (64, 44)]


def save(name, polygons, origin=(0, 0), extra_layer=False):
    library = gdstk.Library(unit=1e-6, precision=1e-9)
    top = library.new_cell(name)
    for polygon in polygons:
        p = polygon.copy().translate(*origin)
        p.layer, p.datatype = 68, 20
        top.add(p)
    top.add(gdstk.Label(name, origin, layer=68, texttype=5))
    top.add(gdstk.rectangle((origin[0]+10, origin[1]+10), (origin[0]+11, origin[1]+11), layer=68, datatype=16))
    if extra_layer:
        top.add(gdstk.rectangle(origin, (origin[0]+1, origin[1]+1), layer=69, datatype=20))
    path = out / (name+".gds")
    library.write_gds(str(path))
    return read_masks(path, exclude)


ring = gdstk.boolean(gdstk.rectangle((0, 0), (4, 4)), gdstk.rectangle((1, 1), (3, 3)), "not", precision=.001)
partition = [gdstk.rectangle((0, 0), (4, 1)), gdstk.rectangle((0, 3), (4, 4)),
             gdstk.rectangle((0, 1), (1, 3)), gdstk.rectangle((3, 1), (4, 3))]
baseline = save("ring", ring)
equivalent = save("translated_partition", partition, (7.123, -2.456))
reversed_ring = save("reversed", [gdstk.Polygon(p.points[::-1]) for p in ring])
widened = save("widened", partition+[gdstk.rectangle((4, 0), (4.01, 1))])
new_layer = save("new_layer", ring, extra_layer=True)
checks = {
    "partition_hole_translation_names_text_and_annotation_ignored": same_masks(baseline, equivalent),
    "polygon_winding_ignored": same_masks(baseline, reversed_ring),
    "10nm_physical_route_change_distinct": not same_masks(baseline, widened),
    "new_physical_layer_distinct": not same_masks(baseline, new_layer),
    "duplicate_index_is_first_actual_equal_mask": first_duplicate(equivalent, [widened, baseline]) == 1,
}
record = {"scope": "software_geometry_unit_fixtures_not_physical_measurements", "checks": checks,
          "all_pass": all(checks.values()), "GDS_precision_um": baseline.precision_um}
(out / "geometry_smoke.json").write_text(json.dumps(record, indent=2)+"\n")
print(json.dumps(record), flush=True)
raise SystemExit(0 if record["all_pass"] else 2)
