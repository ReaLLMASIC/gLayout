"""Geometry-only E2 duplicate checks using exact per-layer mask unions.

No electrical labels are read. Polygon partitioning, hierarchy, translation,
cell names and text labels do not make a new candidate. XOR is evaluated at
the GDS database precision; no coarser convenience grid is introduced.
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MaskGeometry:
    precision_um: float
    masks: dict
    summary: dict


def read_masks(path, excluded_layer_datatypes=()):
    import gdstk
    library = gdstk.read_gds(str(Path(path)))
    top, = library.top_level()
    scale = library.unit / 1e-6
    precision = library.precision / 1e-6
    excluded = {tuple(pair) for pair in excluded_layer_datatypes}
    polygons = [p for p in top.get_polygons(apply_repetitions=True, include_paths=True)
                if (p.layer, p.datatype) not in excluded]
    if not polygons:
        raise ValueError("No physical mask polygons")
    origin = (min(round(float(x)*scale/precision) for p in polygons for x, _ in p.points),
              min(round(float(y)*scale/precision) for p in polygons for _, y in p.points))
    layers = {}
    for polygon in polygons:
        points = [((round(float(x)*scale/precision)-origin[0])*precision,
                   (round(float(y)*scale/precision)-origin[1])*precision) for x, y in polygon.points]
        layers.setdefault((polygon.layer, polygon.datatype), []).append(gdstk.Polygon(points))
    masks = {key: gdstk.boolean(shapes, [], "or", precision=precision)
             for key, shapes in layers.items()}
    masks = {key: shapes for key, shapes in masks.items() if shapes}
    layer_summary = {}
    for key, shapes in masks.items():
        lower_x = min(p.bounding_box()[0][0] for p in shapes)
        lower_y = min(p.bounding_box()[0][1] for p in shapes)
        upper_x = max(p.bounding_box()[1][0] for p in shapes)
        upper_y = max(p.bounding_box()[1][1] for p in shapes)
        layer_summary[key] = {"twice_area_in_grid_units": round(sum(p.area() for p in shapes)*2/precision**2),
            "bbox_in_grid_units": [round(v/precision) for v in [lower_x, lower_y, upper_x, upper_y]]}
    return MaskGeometry(precision, masks, {"precision_um": precision,
        "ignored_common_translation_um": [v*precision for v in origin],
        "physical_layer_count": len(masks), "excluded_layer_datatypes": sorted(excluded),
        "layers": {f"{key[0]}/{key[1]}": value for key, value in sorted(layer_summary.items())},
        "equality_rule": "Boolean XOR has no polygons on every physical (layer,datatype), at original GDS precision"})


def same_masks(first, second):
    """Area/bbox only reject cheap mismatches; the final equality test is XOR."""
    import gdstk
    if first.precision_um != second.precision_um:
        raise ValueError("Frozen E2 stream must use one GDS database precision")
    if first.summary["layers"] != second.summary["layers"]:
        return False
    return all(not gdstk.boolean(first.masks[key], second.masks[key], "xor",
        precision=first.precision_um) for key in first.masks)


def first_duplicate(candidate, accepted_masks):
    return next((index for index, prior in enumerate(accepted_masks) if same_masks(candidate, prior)), None)
