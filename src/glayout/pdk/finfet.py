"""FinFET dimensions and placement lattice, in micrometres.

A manufacturing grid is not a placement grid: rounding every vertex cannot
repair a displaced fin or gate without changing the transistor. Validate those
layers and snap reference origins instead. No foundry rules are implied here.
"""

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from contextvars import ContextVar
import math
import inspect
import numpy as np


@dataclass(frozen=True)
class FinFETFlavor:
    """A model pair and optional threshold-adjust mask, separate from the lattice."""

    nfet: str
    pfet: str
    marker: Optional[str] = None


@dataclass(frozen=True)
class FinFETTechnology:
    fin_pitch: float
    fin_width: float
    gate_pitch: float
    gate_length: float
    manufacturing_grid: float = 0.0005
    fin_min_length: float = 0.108
    active_fin_enclosure: float = 0.010
    active_gate_extension: float = 0.027
    gate_extension: float = 0.054
    select_enclosure: float = 0.054
    well_enclosure: float = 0.054
    sd_width: float = 0.024
    lig_width: float = 0.022
    lig_height: float = 0.016
    via_width: float = 0.018
    metal_width: float = 0.018
    route_pitch: float = 0.054
    row_separation: float = 0.324
    fin_layer: tuple[int, int] = (2, 0)
    gate_layer: tuple[int, int] = (7, 0)

    def __post_init__(self):
        for key, value in vars(self).items():
            if not key.endswith("_layer") and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{key} must be finite and positive")
        if self.fin_width >= self.fin_pitch or self.gate_length >= self.gate_pitch:
            raise ValueError("fin/gate width must be smaller than pitch")
        for dim in (
            self.fin_pitch,
            self.gate_pitch,
            self.fin_width / 2,
            self.gate_length / 2,
        ):
            if not _on_grid(dim, self.manufacturing_grid):
                raise ValueError("FinFET dimensions must fit the manufacturing grid")

    def fin_count(
        self, width: Optional[float] = None, nfin: Optional[int] = None
    ) -> int:
        if nfin is not None:
            if isinstance(nfin, bool) or not isinstance(nfin, int) or nfin < 1:
                raise ValueError("nfin must be a positive integer")
            return nfin
        if width is None or not math.isfinite(width) or width <= 0:
            raise ValueError("width must be finite and positive when nfin is omitted")
        return max(
            1,
            math.ceil(
                float(Decimal(str(width)) / Decimal(str(self.fin_pitch))) - 1e-10
            ),
        )

    def snap_placement(self, xy):
        return tuple(
            float(
                (Decimal(str(v)) / Decimal(str(p))).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
                * Decimal(str(p))
            )
            for v, p in zip(xy, (self.gate_pitch, self.fin_pitch))
        )

    def place(self, reference, origin=(0, 0)):
        """Move a reference origin to the nearest legal site (not its bbox centre)."""
        reference.origin = self.snap_placement(origin)
        return reference

    def validate(self, component):
        """Check flattened world coordinates, including transformed hierarchy."""
        polys = polygons_by_layer(component)
        inv_grid = 1.0 / self.manufacturing_grid
        for layer, polygons in polys.items():
            if not polygons:
                continue
            all_pts = np.vstack([np.asarray(p, dtype=float) for p in polygons])
            scaled = all_pts * inv_grid
            if not np.isfinite(all_pts).all() or not np.allclose(
                scaled, np.round(scaled), atol=1e-6, rtol=0
            ):
                raise ValueError(f"off manufacturing grid on layer {layer}")
            if layer not in (self.fin_layer, self.gate_layer):
                continue
            axis = 1 if layer == self.fin_layer else 0
            pitch = self.fin_pitch if axis == 1 else self.gate_pitch
            width = self.fin_width if axis == 1 else self.gate_length
            for points in polygons:
                pts = np.asarray(points, dtype=float)
                lo, hi = pts.min(axis=0), pts.max(axis=0)
                # Fins and gates are unbent rectangles, with a fixed orientation.
                if not np.all(
                    np.logical_or(
                        np.isclose(pts, lo, atol=1e-9), np.isclose(pts, hi, atol=1e-9)
                    )
                ):
                    raise ValueError(f"nonrectangular fin/gate on layer {layer}")
                if not math.isclose(hi[axis] - lo[axis], width, abs_tol=1e-9):
                    raise ValueError(
                        f"incorrect fin/gate width or rotation on layer {layer}"
                    )
                if not _on_grid((hi[axis] + lo[axis]) / 2, pitch):
                    raise ValueError(f"off fin/gate placement grid on layer {layer}")
        for port in component.ports.values():
            normal = 0 if round(port.orientation or 0) % 180 == 0 else 1
            tangent = 1 - normal
            edges = (
                port.center[normal],
                port.center[tangent] - port.width / 2,
                port.center[tangent] + port.width / 2,
            )
            if not all(_on_grid(v, self.manufacturing_grid) for v in edges):
                raise ValueError(f"off manufacturing grid port edges {port.name}")
        return component


def _on_grid(value, pitch):
    return math.isfinite(value) and math.isclose(
        value / pitch, round(value / pitch), abs_tol=1e-6, rel_tol=0
    )


def polygons_by_layer(component):
    if hasattr(component, "_cell"):  # native gdstk
        result = {}
        for poly in component._cell.get_polygons():
            result.setdefault((poly.layer, poly.datatype), []).append(poly.points)
        return result
    return component.get_polygons(by_spec=True)


_active_technology = ContextVar("glayout_finfet_technology", default=None)


def activate_grid(technology):
    _active_technology.set(technology)


def component_technology(component):
    configs = []
    seen = set()

    def visit(c):
        if id(c) in seen:
            return
        seen.add(id(c))
        config = c.info.get("finfet_technology")
        if config is not None:
            configs.append(FinFETTechnology(**config))
        for ref in c.references:
            visit(ref.parent)

    visit(component)
    if configs and any(t != configs[0] for t in configs[1:]):
        raise ValueError("cannot mix different FinFET placement lattices")
    return configs[0] if configs else _active_technology.get()


def _reference_anchor(parent):
    """Return cached (FinFETTechnology, gate_x0, fin_y0) or None if parent has no gates."""
    cell = getattr(parent, "_cell", parent)
    n_polys = len(getattr(cell, "polygons", ()))
    n_refs = len(getattr(parent, "references", ()))
    cached = parent.info.get("_finfet_anchor_cache")
    if cached is not None and cached[0] == (n_polys, n_refs):
        data = cached[1]
        if data is None:
            return None
        return FinFETTechnology(**data[0]), data[1], data[2]
    t = component_technology(parent)
    if t is None:
        return None
    polys = polygons_by_layer(parent)
    gate_polys = polys.get(t.gate_layer, [])
    if not gate_polys:
        parent.info["_finfet_anchor_cache"] = ((n_polys, n_refs), None)
        return None
    points = np.asarray(gate_polys[0])
    gx = float((points[:, 0].min() + points[:, 0].max()) / 2)
    fin_polys = polys.get(t.fin_layer, [])
    fy = 0.0
    if fin_polys:
        fpts = np.asarray(fin_polys[0])
        fy = float((fpts[:, 1].min() + fpts[:, 1].max()) / 2)
    parent.info["_finfet_anchor_cache"] = ((n_polys, n_refs), (asdict(t), gx, fy))
    return t, gx, fy


def install_export_guard(component_class):
    """Install once for either geometry backend. Planar PDKs retain defaults.

    Persist the lattice through flattening and PDK changes: a generated FinFET
    must not lose enforcement because a planar PDK was activated afterwards.
    """
    original = component_class.write_gds
    if getattr(original, "_finfet_guard", False):
        return
    original_flatten = component_class.flatten

    def flatten(self, *args, **kwargs):
        technology = component_technology(self)
        result = original_flatten(self, *args, **kwargs)
        if technology is not None:
            result.info["finfet_technology"] = asdict(technology)
        return result

    def write_gds(self, *args, **kwargs):
        technology = component_technology(self)
        if technology is not None:
            technology.validate(self)
            self = legalize_redundant_vias(self, technology)
            bound = inspect.signature(original).bind_partial(self, *args, **kwargs)
            unit = kwargs.get("unit", bound.arguments.get("unit")) or 1e-6
            precision = technology.manufacturing_grid * unit
            given = kwargs.get("precision", bound.arguments.get("precision"))
            if given is not None and given > precision * (1 + 1e-9):
                raise ValueError(
                    "GDS precision would lose the FinFET manufacturing grid"
                )
            if given is None:
                kwargs["precision"] = precision
        return original(self, *args, **kwargs)

    write_gds._finfet_guard = True
    component_class.write_gds = write_gds
    component_class.flatten = flatten


def install_reference_grid(reference_class):
    """Legalize device reference translations below all circuit generators.

    Routes and contact references keep their original coordinates. References
    containing actual FIN/GATE masks move by whole process pitches; no device
    mask is stretched, and the existing generator placement pattern is retained.
    """
    if getattr(reference_class.move, "_finfet_reference_guard", False):
        return

    def align(ref):
        if _active_technology.get() is None and "finfet_technology" not in ref.parent.info:
            return
        anchor = _reference_anchor(ref.parent)
        if anchor is None:
            return
        t, x, y = anchor
        if not math.isclose(float(ref.rotation or 0) % 180, 0, abs_tol=1e-8):
            raise ValueError("FinFET devices cannot rotate by 90 degrees")
        sign = (
            -1 if math.isclose(float(ref.rotation or 0) % 360, 180, abs_tol=1e-8) else 1
        )
        x *= sign
        y *= sign * (-1 if ref.x_reflection else 1)
        ox, oy = ref.origin
        sx, sy = t.snap_placement((ox + x, oy + y))
        ref.origin = (sx - x, sy - y)
        if hasattr(ref, "_bb_valid"):
            ref._bb_valid = False

    for name in ("move", "movex", "movey", "rotate", "mirror", "mirror_x", "mirror_y"):
        if not hasattr(reference_class, name):
            continue
        original = getattr(reference_class, name)

        def wrapper(self, *args, _original=original, **kwargs):
            result = _original(self, *args, **kwargs)
            align(self)
            return result

        wrapper._finfet_reference_guard = True
        setattr(reference_class, name, wrapper)


def legalize_redundant_vias(component, technology):
    """Coalesce collinear cuts only when both metals already cover the hull.

    Legacy wide-wire landings can duplicate a cut 9 nm from another cut on
    the same metal pair. A longer cut is legal (V1-V3.W.1 is a minimum), and
    does not alter placement, routing or connectivity. Never bridge a metal
    gap or connect distinct conductors to make DRC pass.
    """
    import klayout.db as k
    import gdstk

    dbu = technology.manufacturing_grid
    polygons = polygons_by_layer(component)

    def region(layer):
        r = k.Region()
        for points in polygons.get(layer, []):
            r.insert(
                k.Polygon([k.Point(round(x / dbu), round(y / dbu)) for x, y in points])
            )
        return r.merged()

    changed = {}
    for low, via, high in ((16, 18, 19), (19, 21, 20), (20, 25, 30), (30, 35, 40), (40, 45, 50)):
        cuts = region((via, 0))
        if cuts.is_empty():
            continue
        lower = region((low, 0)) if low != 16 else (region((16, 0)) + region((17, 0)))
        upper = region((high, 0))
        boxes = [p.bbox() for p in cuts.each() if p.is_box()]
        if len(boxes) != cuts.size():
            continue
        did_change = False
        for axis in (0, 1):
            groups = {}
            for box in boxes:
                key = (box.bottom, box.top) if axis == 0 else (box.left, box.right)
                groups.setdefault(key, []).append(box)
            new = []
            for group in groups.values():
                group.sort(key=lambda b: b.left if axis == 0 else b.bottom)
                current = group[0]
                for box in group[1:]:
                    gap = (
                        box.left - current.right
                        if axis == 0
                        else box.bottom - current.top
                    )
                    hull = current + box
                    footprint = k.Region(hull)
                    if (
                        0 < gap * dbu < 0.018 - 1e-9
                        and (footprint - lower).is_empty()
                        and (footprint - upper).is_empty()
                    ):
                        current = hull
                        did_change = True
                    else:
                        new.append(current)
                        current = box
                new.append(current)
            boxes = new
        if did_change:
            changed[via] = boxes
    if not changed:
        return component
    result = component.copy().flatten()
    # This private export copy replaces the original; preserve its GDS name.
    result._cell.name = component.name
    for polygon in list(result._cell.polygons):
        if polygon.datatype == 0 and polygon.layer in changed:
            result._cell.remove(polygon)
    for layer, boxes in changed.items():
        for b in boxes:
            result._cell.add(
                gdstk.rectangle(
                    (b.left * dbu, b.bottom * dbu),
                    (b.right * dbu, b.top * dbu),
                    layer=layer,
                )
            )
    return result
