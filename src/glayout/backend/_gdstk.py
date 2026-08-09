"""Native gdstk implementation of glayout's Component, ComponentReference, and Port.

Designed as a drop-in replacement for the corresponding gdsfactory types
(as used inside this repo). Coverage focuses on the API surface actually
exercised by gLayout — not full gdsfactory parity.
"""
from __future__ import annotations

import itertools
import math
import os
from pathlib import Path as _Path
from typing import Any, Callable, Iterable, Optional, Sequence, Union

import gdstk

# ---------------------------------------------------------------------------
# Type aliases (gdsfactory.typings shims)
# ---------------------------------------------------------------------------

Layer = tuple[int, int]
Coord = tuple[float, float]
PathType = Union[str, _Path]


# --- Pdk (minimal pydantic BaseModel replacement for gdsfactory.pdk.Pdk) ---
# MappedPDK inherits from this, so we match enough of the gdsfactory shape for
# MappedPDK to work (name, layers, default_decorator, gds_write_settings,
# cell_decorator_settings, .activate()). Extra fields are allowed so callers
# can pass arbitrary pdk-specific config.
from pydantic import BaseModel, ConfigDict  # noqa: E402
import os as _os


class _GdsWriteSettings(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    precision: float = 1e-9
    unit: float = 1e-6
    flatten_invalid_refs: bool = False


class _CellDecoratorSettings(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    cache: bool = False


class Pdk(BaseModel):
    """Minimal shim for gdsfactory.pdk.Pdk. Holds enough state for
    MappedPDK to function."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    name: str
    layers: Optional[dict] = None
    default_decorator: Optional[Any] = None
    grid_size: float = 0.001  # microns; matches gdsfactory default
    gds_write_settings: _GdsWriteSettings = _GdsWriteSettings()
    cell_decorator_settings: _CellDecoratorSettings = _CellDecoratorSettings()

    def activate(self) -> None:
        """No-op. gdsfactory's activate() registered the PDK in a global
        registry; that registry is a gdsfactory concern and isn't needed
        once gdsfactory is out of the import graph."""
        return None

    def validate_layers(self, layers_required) -> None:
        """Mimics gdsfactory.pdk.Pdk.validate_layers — raise if any named
        layer isn't in `self.layers`."""
        if self.layers is None:
            return
        for lay in layers_required:
            if lay not in self.layers:
                raise ValueError(f"layer {lay!r} not in pdk.layers")

    def get_layer(self, layer_name: str):
        """Return the (layer, datatype) tuple for a named layer."""
        if self.layers is None:
            raise ValueError("pdk.layers is not set")
        if layer_name not in self.layers:
            raise ValueError(f"layer {layer_name!r} not in pdk.layers")
        return self.layers[layer_name]


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


def _pydantic_instance_schema(cls):
    """pydantic v2 hook: treat the class as an opaque type (isinstance check)."""
    try:
        from pydantic_core import core_schema
    except ImportError:  # pragma: no cover
        return None
    return core_schema.is_instance_schema(cls)


class Port:
    """Lightweight mutable port.

    Mirrors the fields gLayout reads/writes on `gdsfactory.port.Port`.
    Positional args match gdsfactory's positional order used in this repo:
    `Port(name, orientation, center, width, layer=..., ...)`.
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type, _handler):
        return _pydantic_instance_schema(cls)


    __slots__ = (
        "name",
        "orientation",
        "_center",
        "width",
        "layer",
        "port_type",
        "parent",
        "cross_section",
        "shear_angle",
    )

    @property
    def center(self) -> Coord:
        return self._center

    @center.setter
    def center(self, value: Coord) -> None:
        self._center = (float(value[0]), float(value[1]))

    @property
    def x(self) -> float:
        return self._center[0]

    @x.setter
    def x(self, value: float) -> None:
        self._center = (float(value), self._center[1])

    @property
    def y(self) -> float:
        return self._center[1]

    @y.setter
    def y(self, value: float) -> None:
        self._center = (self._center[0], float(value))

    def __init__(
        self,
        name: Optional[str] = None,
        orientation: float = 0.0,
        center: Coord = (0.0, 0.0),
        width: float = 0.0,
        layer: Optional[Layer] = None,
        port_type: str = "electrical",
        parent: Optional["Component"] = None,
        cross_section=None,
        shear_angle: Optional[float] = None,
    ):
        self.name = name
        self.orientation = float(orientation) if orientation is not None else 0.0
        self._center = (float(center[0]), float(center[1]))
        self.width = float(width)
        self.layer = tuple(layer) if layer is not None else None
        self.port_type = port_type
        self.parent = parent
        self.cross_section = cross_section
        self.shear_angle = shear_angle

    def __repr__(self) -> str:
        return (
            f"Port(name={self.name!r}, center={self.center}, "
            f"orientation={self.orientation}, width={self.width}, layer={self.layer})"
        )

    def copy(self, name: Optional[str] = None) -> "Port":
        return Port(
            name=name if name is not None else self.name,
            orientation=self.orientation,
            center=self.center,
            width=self.width,
            layer=self.layer,
            port_type=self.port_type,
            parent=self.parent,
            cross_section=self.cross_section,
            shear_angle=self.shear_angle,
        )

    def move_copy(self, offset: Coord) -> "Port":
        c = self.copy()
        c._center = (c._center[0] + float(offset[0]), c._center[1] + float(offset[1]))
        return c


def _apply_transform_to_port(
    port: Port,
    origin: Coord,
    rotation_deg: float,
    x_reflection: bool,
) -> Port:
    """Return a copy of `port` with the GDS reference transform applied.

    GDS convention: x_reflection first (y -> -y), then rotation, then translation.
    """
    p = port.copy()
    x, y = p._center
    o = p.orientation
    if x_reflection:
        y = -y
        o = -o
    if rotation_deg:
        rad = math.radians(rotation_deg)
        cs, sn = math.cos(rad), math.sin(rad)
        x, y = x * cs - y * sn, x * sn + y * cs
        o += rotation_deg
    x += origin[0]
    y += origin[1]
    p._center = (x, y)
    p.orientation = o % 360.0
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_name_counter = itertools.count()


def _unique_name(prefix: str = "Component") -> str:
    return f"{prefix}_{next(_name_counter)}"


def _bbox_or_zero(bbox) -> tuple[Coord, Coord]:
    if bbox is None:
        return ((0.0, 0.0), (0.0, 0.0))
    (x0, y0), (x1, y1) = bbox
    return ((float(x0), float(y0)), (float(x1), float(y1)))


def _as_layer(layer) -> Layer:
    if layer is None:
        raise ValueError("layer is required")
    return (int(layer[0]), int(layer[1]))


# ---------------------------------------------------------------------------
# ComponentReference
# ---------------------------------------------------------------------------


class ComponentReference:
    """Wraps a `gdstk.Reference`. Exposes transform mutation and transformed
    views of the parent component's ports/bbox."""

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type, _handler):
        return _pydantic_instance_schema(cls)


    def __init__(self, parent: "Component", gref: Optional[gdstk.Reference] = None):
        self.parent = parent
        if gref is None:
            gref = gdstk.Reference(parent._cell, origin=(0.0, 0.0))
        self._ref = gref
        # owner is the Component this reference has been added to (not the target)
        self.owner: Optional["Component"] = None
        # a label for this placement; falls back to the target cell's name
        self._name: Optional[str] = None


    # --- metadata ----------------------------------------------------------
    @property
    def info(self) -> dict:
        """Metadata of the referenced component.

        gdsfactory exposes the parent's `info` through the reference, and cells
        rely on that: mimcap_array writes `info['netlist']` on the Component,
        while opamp_twostage reads it back off the reference returned by `<<`.
        A reference has no metadata of its own, so delegate.
        """
        return self.parent.info

    @info.setter
    def info(self, value: dict) -> None:
        self.parent.info = value

    # --- transform properties ---------------------------------------------
    @property
    def origin(self) -> Coord:
        return tuple(self._ref.origin)  # type: ignore[return-value]

    @origin.setter
    def origin(self, value: Coord) -> None:
        self._ref.origin = (float(value[0]), float(value[1]))

    @property
    def rotation(self) -> float:
        # gdstk stores rotation in radians
        return math.degrees(self._ref.rotation)

    @rotation.setter
    def rotation(self, value_deg: float) -> None:
        self._ref.rotation = math.radians(float(value_deg))

    @property
    def x_reflection(self) -> bool:
        return bool(self._ref.x_reflection)

    @x_reflection.setter
    def x_reflection(self, value: bool) -> None:
        self._ref.x_reflection = bool(value)

    # --- movement (mutate + return self) ----------------------------------
    def movex(
        self,
        origin: float = 0.0,
        destination: Optional[float] = None,
    ) -> "ComponentReference":
        """Move along x, mirroring ``move``'s calling conventions:
          - movex(dx)                 — translate by dx
          - movex(destination=x)      — translate by x
          - movex(origin=x0,
                  destination=x1)     — translate by x1-x0
        """
        dx = float(origin) if destination is None else float(destination) - float(origin)
        ox, oy = self.origin
        self.origin = (ox + dx, oy)
        return self

    def movey(
        self,
        origin: float = 0.0,
        destination: Optional[float] = None,
    ) -> "ComponentReference":
        """Move along y. See :meth:`movex` for the calling conventions."""
        dy = float(origin) if destination is None else float(destination) - float(origin)
        ox, oy = self.origin
        self.origin = (ox, oy + dy)
        return self

    def move(
        self,
        origin: Optional[Coord] = None,
        destination: Optional[Coord] = None,
    ) -> "ComponentReference":
        """Move this reference. Two calling conventions:
          - move((dx, dy))                    — translate by offset
          - move(destination=(x, y))          — move so the ref's center lands at (x, y)
          - move(origin=(x0, y0),
                 destination=(x1, y1))        — translate by (x1-x0, y1-y0)
        """
        if destination is None and origin is not None and not isinstance(origin, ComponentReference):
            # single-arg form: treat as offset
            return self.movex(origin[0]).movey(origin[1])
        if destination is None:
            return self
        if origin is None:
            # move by (destination - current center)
            cx, cy = self.center
            dx, dy = destination[0] - cx, destination[1] - cy
        else:
            dx, dy = destination[0] - origin[0], destination[1] - origin[1]
        return self.movex(dx).movey(dy)

    def rotate(self, angle_deg: float, center: Coord = (0.0, 0.0)) -> "ComponentReference":
        # rotate the reference's placement about `center`
        ox, oy = self.origin
        cx, cy = center
        rad = math.radians(float(angle_deg))
        cs, sn = math.cos(rad), math.sin(rad)
        dx, dy = ox - cx, oy - cy
        self.origin = (cx + dx * cs - dy * sn, cy + dx * sn + dy * cs)
        self.rotation = self.rotation + float(angle_deg)
        return self

    def mirror_x(self, x0: float = 0.0) -> "ComponentReference":
        """Mirror across the vertical line x=x0 (flip left-right)."""
        return self.mirror(p1=(x0, 0.0), p2=(x0, 1.0))

    def mirror_y(self, y0: float = 0.0) -> "ComponentReference":
        """Mirror across the horizontal line y=y0 (flip top-bottom)."""
        return self.mirror(p1=(0.0, y0), p2=(1.0, y0))

    def mirror(self, p1: Coord = (0.0, 0.0), p2: Coord = (0.0, 1.0)) -> "ComponentReference":
        """Mirror across the line through p1-p2. Limited impl: supports the
        x-axis (horizontal) and y-axis (vertical) cases gLayout routing uses."""
        x1, y1 = p1
        x2, y2 = p2
        if x1 == x2:  # vertical line: mirror across x = x1
            self._ref.x_reflection = not self._ref.x_reflection
            self.rotation = 180.0 - self.rotation
            ox, oy = self.origin
            self.origin = (2 * x1 - ox, oy)
        elif y1 == y2:  # horizontal line: mirror across y = y1
            self._ref.x_reflection = not self._ref.x_reflection
            ox, oy = self.origin
            self.origin = (ox, 2 * y1 - oy)
        else:
            raise NotImplementedError("mirror only supports axis-aligned lines")
        return self

    # --- views -------------------------------------------------------------
    @property
    def ports(self) -> dict[str, Port]:
        origin = self.origin
        rot = self.rotation
        xr = self.x_reflection
        return {
            name: _apply_transform_to_port(p, origin, rot, xr)
            for name, p in self.parent.ports.items()
        }

    def get_ports_list(self, prefix: str = "", **filters) -> list[Port]:
        """Filter ports. `prefix` filters to names starting with that prefix
        (matches gdsfactory.component.Component.get_ports_list). Extra
        kwargs filter by attribute equality."""
        out: list[Port] = []
        for name, p in self.ports.items():
            if prefix and not name.startswith(prefix):
                continue
            if filters:
                skip = False
                for k, v in filters.items():
                    if getattr(p, k, None) != v:
                        skip = True
                        break
                if skip:
                    continue
            out.append(p)
        return out

    @property
    def bbox(self) -> tuple[Coord, Coord]:
        return _bbox_or_zero(self._ref.bounding_box())

    @property
    def center(self) -> Coord:
        (x0, y0), (x1, y1) = self.bbox
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)

    @property
    def x(self) -> float:
        """Centre x. gdsfactory exposes this on references, not just on cells."""
        return self.center[0]

    @property
    def y(self) -> float:
        """Centre y. Counterpart of :attr:`x`."""
        return self.center[1]

    @property
    def xmin(self) -> float: return self.bbox[0][0]
    @property
    def xmax(self) -> float: return self.bbox[1][0]
    @property
    def ymin(self) -> float: return self.bbox[0][1]
    @property
    def ymax(self) -> float: return self.bbox[1][1]

    @property
    def name(self) -> str:
        return self._name if self._name is not None else self.parent.name

    @name.setter
    def name(self, value: str) -> None:
        # gdsfactory lets callers label a placement without touching the cell it
        # points at (``ref.name = "pfet_2"``), and cells and tutorials do exactly
        # that. Keep it on the reference: renaming the parent here would rename
        # every other reference to the same cell too.
        self._name = str(value)

    def __repr__(self) -> str:
        return f"ComponentReference(parent={self.parent.name!r}, origin={self.origin}, rotation={self.rotation})"


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


class Component:
    """Mutable layout cell backed by a `gdstk.Cell`.

    Shape of the public API matches what gLayout uses from gdsfactory's
    Component — not the entire gdsfactory surface.
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type, _handler):
        return _pydantic_instance_schema(cls)


    def __init__(self, name: Optional[str] = None):
        self._cell = gdstk.Cell(name if name is not None else _unique_name())
        self.ports: dict[str, Port] = {}
        self._references: list[ComponentReference] = []
        self._locked = False
        self.info: dict = {}

    # --- identity ----------------------------------------------------------
    @property
    def name(self) -> str:
        return self._cell.name

    @name.setter
    def name(self, value: str) -> None:
        self._cell.name = str(value)

    def show(self, *args, **kwargs) -> None:
        """Open the layout in KLayout, like gdsfactory's Component.show().

        Writes a temp .gds and hands it to klive when reachable. Tutorials
        call this for interactive viewing, so it must stay quiet headless.
        """
        import tempfile
        path = _os.path.join(tempfile.gettempdir(), f"{self.name}.gds")
        self.write_gds(path)
        try:
            from gdsfactory.show import show as _gf_show  # type: ignore
            _gf_show(path)
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"Component(name={self.name!r}, ports={list(self.ports)}, refs={len(self._references)})"

    # --- lock/unlock (no-op; gdsfactory compat) ---------------------------
    def lock(self) -> "Component":
        self._locked = True
        return self

    def unlock(self) -> "Component":
        self._locked = False
        return self

    # --- add / << ----------------------------------------------------------
    def add_ref(self, component: "Component", alias: Optional[str] = None) -> ComponentReference:
        ref = component.ref()
        self.add(ref)
        return ref

    def __lshift__(self, component: "Component") -> ComponentReference:
        return self.add_ref(component)

    def add(
        self,
        element: Union["Component", ComponentReference, gdstk.Reference, gdstk.Polygon, gdstk.Label, Iterable],
    ) -> "Component":
        """Add a component, reference, polygon, label, or iterable of those."""
        if isinstance(element, ComponentReference):
            self._cell.add(element._ref)
            element.owner = self
            self._references.append(element)
        elif isinstance(element, Component):
            # gdsfactory accepts a bare Component here and references it
            # implicitly; opamp_twostage and others rely on that.
            self.add_ref(element)
        elif isinstance(element, (gdstk.Reference, gdstk.Polygon, gdstk.Label)):
            self._cell.add(element)
        elif isinstance(element, Iterable):
            for e in element:
                self.add(e)
        else:
            raise TypeError(f"Component.add: unsupported type {type(element).__name__}")
        return self

    def ref(
        self,
        position: Coord = (0.0, 0.0),
        rotation: float = 0.0,
        x_reflection: bool = False,
    ) -> ComponentReference:
        """Return a fresh ComponentReference pointing at this Component.

        Not yet attached to any parent. `position`, `rotation` and
        `x_reflection` mirror gdsfactory's signature; opamp.py calls
        `rect.ref(position=...)`.
        """
        r = ComponentReference(self)
        if x_reflection:
            r.mirror(p1=(0.0, 0.0), p2=(1.0, 0.0))
        if rotation:
            r.rotate(rotation)
        if position != (0.0, 0.0):
            r.movex(position[0]).movey(position[1])
        return r

    # --- ports -------------------------------------------------------------
    def add_port(
        self,
        name: Optional[str] = None,
        center: Coord = (0.0, 0.0),
        width: float = 0.0,
        orientation: float = 0.0,
        layer: Optional[Layer] = None,
        port_type: str = "electrical",
        port: Optional[Port] = None,
    ) -> Port:
        if port is not None:
            p = port.copy(name=name if name is not None else port.name)
        else:
            p = Port(
                name=name,
                orientation=orientation,
                center=center,
                width=width,
                layer=layer,
                port_type=port_type,
                parent=self,
            )
        if p.name is None:
            raise ValueError("port name is required")
        if p.name in self.ports:
            raise ValueError(f"duplicate port name {p.name!r} on component {self.name!r}")
        self.ports[p.name] = p
        return p

    def add_ports(
        self,
        ports: Iterable[Port],
        prefix: str = "",
    ) -> "Component":
        for p in ports:
            new_name = f"{prefix}{p.name}" if prefix else p.name
            np = p.copy(name=new_name)
            np.parent = self
            if new_name in self.ports:
                raise ValueError(f"duplicate port name {new_name!r} on component {self.name!r}")
            self.ports[new_name] = np
        return self

    def pprint_ports(self) -> None:
        """Print the ports, one per line.

        gdsfactory offers this on Component and the tutorials use it to look
        at a cell while building it. Without it a notebook that runs fine on
        the other backend dies with AttributeError halfway through.
        """
        for name in sorted(self.ports):
            p = self.ports[name]
            print("%-42s (%9.3f, %9.3f)  ancho %7.3f  %5.1f  %s"
                  % (name, p.center[0], p.center[1], p.width,
                     p.orientation or 0.0, p.layer))

    def get_ports_list(self, prefix: str = "", **filters) -> list[Port]:
        out: list[Port] = []
        for name, p in self.ports.items():
            if filters:
                skip = False
                for k, v in filters.items():
                    if getattr(p, k, None) != v:
                        skip = True
                        break
                if skip:
                    continue
            if prefix:
                out.append(p.copy(name=f"{prefix}{name}"))
            else:
                out.append(p)
        return out

    # --- geometry ---------------------------------------------------------
    def add_polygon(self, points, layer: Optional[Layer] = None) -> gdstk.Polygon:
        """Add a polygon. Accepts:
          - a gdstk.Polygon                      (layer ignored)
          - an iterable of gdstk.Polygon         (layer ignored)
          - a list of (x,y) points + a layer=(l,dt)
        """
        if isinstance(points, gdstk.Polygon):
            self._cell.add(points)
            return points
        if isinstance(points, (list, tuple)) and points and isinstance(points[0], gdstk.Polygon):
            for p in points:
                self._cell.add(p)
            return points[0]
        l, dt = _as_layer(layer)
        poly = gdstk.Polygon(list(points), layer=l, datatype=dt)
        self._cell.add(poly)
        return poly

    def add_padding(
        self,
        layers: Sequence[Layer] = (),
        default: float = 0.0,
        top: Optional[float] = None,
        bottom: Optional[float] = None,
        left: Optional[float] = None,
        right: Optional[float] = None,
    ) -> "Component":
        """Add a background rectangle on each layer in `layers`, padded around
        the current bbox. Matches gdsfactory.add_padding.add_padding semantics
        used in this repo."""
        (x0, y0), (x1, y1) = self.bbox
        t = top if top is not None else default
        b = bottom if bottom is not None else default
        l = left if left is not None else default
        r = right if right is not None else default
        for layer in layers:
            ll, dt = int(layer[0]), int(layer[1])
            self._cell.add(gdstk.rectangle((x0 - l, y0 - b),
                                           (x1 + r, y1 + t),
                                           layer=ll, datatype=dt))
        return self

    def add_label(
        self,
        text: str,
        position: Coord = (0.0, 0.0),
        layer: Optional[Layer] = None,
        anchor: str = "o",
        rotation: float = 0.0,
        magnification: float = 1.0,
    ) -> gdstk.Label:
        l, dt = _as_layer(layer)
        lbl = gdstk.Label(
            str(text),
            (float(position[0]), float(position[1])),
            anchor=anchor,
            rotation=math.radians(rotation),
            magnification=magnification,
            layer=l,
            texttype=dt,
        )
        self._cell.add(lbl)
        return lbl

    # --- bbox / center ----------------------------------------------------
    @property
    def bbox(self) -> tuple[Coord, Coord]:
        return _bbox_or_zero(self._cell.bounding_box())

    @property
    def center(self) -> Coord:
        (x0, y0), (x1, y1) = self.bbox
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)

    @property
    def xmin(self) -> float: return self.bbox[0][0]
    @property
    def xmax(self) -> float: return self.bbox[1][0]
    @property
    def ymin(self) -> float: return self.bbox[0][1]
    @property
    def ymax(self) -> float: return self.bbox[1][1]

    @property
    def size(self) -> Coord:
        (x0, y0), (x1, y1) = self.bbox
        return (x1 - x0, y1 - y0)

    @property
    def references(self) -> list[ComponentReference]:
        return list(self._references)

    # --- structural transforms --------------------------------------------
    def flatten(self, single_layer: Optional[Layer] = None) -> "Component":
        """Resolve all references into this cell's polygons/labels. Mutates."""
        self._cell.flatten()
        self._references.clear()
        if single_layer is not None:
            l, dt = _as_layer(single_layer)
            for p in self._cell.polygons:
                p.layer = l
                p.datatype = dt
        return self

    def extract(self, layers: Sequence[Layer]) -> "Component":
        """Return a new Component containing only polygons on the given layers.
        Hierarchy is resolved (flattened) in the output."""
        layer_set = {(int(l), int(dt)) for (l, dt) in layers}
        new = Component(name=_unique_name(self.name + "_extract"))
        for (l, dt) in layer_set:
            for p in self._cell.get_polygons(layer=l, datatype=dt):
                new._cell.add(p.copy())
        return new

    def remove_layers(self, layers: Sequence[Layer]) -> "Component":
        """Remove all polygons on the given layers. Flattens references first
        so polygons inside sub-cells also disappear. Mutates and returns self."""
        layer_set = {(int(l), int(dt)) for (l, dt) in layers}
        self.flatten()
        keep = [p for p in self._cell.polygons if (p.layer, p.datatype) not in layer_set]
        for p in list(self._cell.polygons):
            self._cell.remove(p)
        for p in keep:
            self._cell.add(p)
        return self

    def copy(self, name: Optional[str] = None) -> "Component":
        """Deep-copy this Component. References keep pointing at the same
        target cells (same semantics as gdsfactory's Component.copy)."""
        new_name = name if name is not None else _unique_name(self.name + "_copy")
        new = Component.__new__(Component)
        new._cell = self._cell.copy(new_name, deep_copy=False)
        new._locked = False
        new.info = dict(self.info)
        # ports
        new.ports = {}
        for pname, p in self.ports.items():
            pc = p.copy()
            pc.parent = new
            new.ports[pname] = pc
        # references: rebuild wrappers around the copied cell's refs
        new._references = []
        for src_ref, new_gref in zip(self._references, new._cell.references):
            wrapper = ComponentReference(src_ref.parent, new_gref)
            wrapper.owner = new
            new._references.append(wrapper)
        return new

    # --- GDS I/O ----------------------------------------------------------
    def _collect_cells(self) -> list[gdstk.Cell]:
        """Depth-first collect this cell + all cells reachable via references,
        uniqued by identity, with referenced cells before their users."""
        seen: dict[int, gdstk.Cell] = {}
        order: list[gdstk.Cell] = []

        def visit(cell: gdstk.Cell) -> None:
            if id(cell) in seen:
                return
            seen[id(cell)] = cell
            for r in cell.references:
                visit(r.cell)
            order.append(cell)

        visit(self._cell)
        return order

    def write_gds(
        self,
        filename: Optional[str] = None,
        unit: float = 1e-6,
        precision: float = 1e-9,
        gdsdir: Optional[str] = None,
    ) -> str:
        # Match gdsfactory's write_gds(gdspath=None, gdsdir=None): the path
        # may be omitted (defaults to "<name>.gds") and a directory may be
        # given on its own. Tutorials use both call styles.
        if filename is None:
            filename = f"{self.name}.gds"
        if gdsdir is not None:
            filename = str(_os.path.join(str(gdsdir), str(filename)))
        lib = gdstk.Library(unit=unit, precision=precision)
        used_names: set[str] = set()
        for cell in self._collect_cells():
            # avoid same-name collisions within the library
            if cell.name in used_names:
                cell.name = _unique_name(cell.name)
            used_names.add(cell.name)
            lib.add(cell)
        lib.write_gds(str(filename))
        return str(filename)


# ---------------------------------------------------------------------------
# ComponentOrReference type alias (after Component/CR are defined)
# ---------------------------------------------------------------------------

ComponentOrReference = Union[Component, ComponentReference]


# ---------------------------------------------------------------------------
# Polygon — gdstk.Polygon with a couple of gdsfactory-style accessors
# ---------------------------------------------------------------------------


def _normalize_layer(layer, datatype=None) -> tuple[int, int]:
    if datatype is not None:
        return int(layer), int(datatype)
    if isinstance(layer, tuple) and len(layer) == 2:
        return int(layer[0]), int(layer[1])
    return int(layer), 0


def Polygon(points, layer=(0, 0), datatype=None) -> gdstk.Polygon:
    """Build a gdstk.Polygon from (points, layer=(l,dt))."""
    l, dt = _normalize_layer(layer, datatype)
    return gdstk.Polygon(list(points), l, dt)


# ---------------------------------------------------------------------------
# snap_to_grid
# ---------------------------------------------------------------------------


def snap_to_grid(x, nm: int = 1):
    """Snap `x` (in micrometers) to an `nm`-nanometer grid.

    Matches gdsfactory.snap.snap_to_grid semantics used in this repo.
    Accepts scalars or iterables.
    """
    if x is None:
        return None
    if isinstance(x, (list, tuple)):
        return type(x)(snap_to_grid(v, nm) for v in x)
    return round(float(x) * 1000.0 / nm) * nm / 1000.0


# ---------------------------------------------------------------------------
# @cell decorator + clear_cache (no-ops; caching was a gdsfactory concern)
# ---------------------------------------------------------------------------


def cell(func: Optional[Callable] = None, **_kwargs):
    """Pass-through cell decorator. gdsfactory's `@cell` cached by args and
    named the Component after the function — we don't need either: Component
    names are auto-generated for uniqueness on write, and caching introduces
    subtle aliasing bugs (shared mutable state across calls)."""
    if func is None:
        return lambda f: f
    return func


def clear_cache() -> None:
    """No-op; kept for API compatibility with gdsfactory."""
    return None


def copy(component: "Component") -> "Component":
    """Drop-in for `gdsfactory.component.copy`."""
    return component.copy()


# ---------------------------------------------------------------------------
# rectangle + rectangular_ring + primitive_rectangle
# ---------------------------------------------------------------------------


def _add_edge_ports(
    comp: "Component",
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    layer: Layer,
) -> None:
    """Add e1 (W), e2 (N), e3 (E), e4 (S) ports on the edges of the rect."""
    w = x1 - x0
    h = y1 - y0
    comp.add_port(name="e1", center=(x0, (y0 + y1) / 2.0),
                  orientation=180, width=h, layer=layer, port_type="electrical")
    comp.add_port(name="e2", center=((x0 + x1) / 2.0, y1),
                  orientation=90, width=w, layer=layer, port_type="electrical")
    comp.add_port(name="e3", center=(x1, (y0 + y1) / 2.0),
                  orientation=0, width=h, layer=layer, port_type="electrical")
    comp.add_port(name="e4", center=((x0 + x1) / 2.0, y0),
                  orientation=270, width=w, layer=layer, port_type="electrical")


def rectangle(
    size: tuple[float, float] = (4.0, 2.0),
    layer: Layer = (0, 0),
    centered: bool = False,
    port_type: str = "electrical",
    port_orientations: Optional[tuple] = None,
) -> "Component":
    """Rectangle Component with 4 edge ports (e1/e2/e3/e4 = W/N/E/S)."""
    w, h = float(size[0]), float(size[1])
    if centered:
        x0, y0, x1, y1 = -w / 2.0, -h / 2.0, w / 2.0, h / 2.0
    else:
        x0, y0, x1, y1 = 0.0, 0.0, w, h
    c = Component(_unique_name("rectangle"))
    c.add_polygon(gdstk.rectangle((x0, y0), (x1, y1),
                                  layer=int(layer[0]), datatype=int(layer[1])))
    _add_edge_ports(c, x0, y0, x1, y1, layer)
    return c


def rectangular_ring(
    enclosed_size: tuple[float, float] = (4.0, 2.0),
    width: float = 0.5,
    layer: Layer = (0, 0),
    centered: bool = True,
) -> "Component":
    """Frame/ring Component. `enclosed_size` is the inner empty region;
    `width` is the frame thickness on each side."""
    iw, ih = float(enclosed_size[0]), float(enclosed_size[1])
    w = float(width)
    ow, oh = iw + 2 * w, ih + 2 * w
    if centered:
        ox0, oy0 = -ow / 2.0, -oh / 2.0
    else:
        ox0, oy0 = 0.0, 0.0
    ox1, oy1 = ox0 + ow, oy0 + oh
    ix0, iy0 = ox0 + w, oy0 + w
    ix1, iy1 = ix0 + iw, iy0 + ih

    l, dt = int(layer[0]), int(layer[1])
    outer = gdstk.rectangle((ox0, oy0), (ox1, oy1), layer=l, datatype=dt)
    inner = gdstk.rectangle((ix0, iy0), (ix1, iy1), layer=l, datatype=dt)
    diff = gdstk.boolean(outer, inner, "not", layer=l, datatype=dt)

    c = Component(_unique_name("rectangular_ring"))
    for p in diff:
        c._cell.add(p)
    _add_edge_ports(c, ox0, oy0, ox1, oy1, layer)
    return c


# ---------------------------------------------------------------------------
# boolean
# ---------------------------------------------------------------------------


def _as_polygon_list(obj) -> list[gdstk.Polygon]:
    if isinstance(obj, Component):
        return list(obj._cell.get_polygons())
    if isinstance(obj, ComponentReference):
        # resolve the reference's transform by baking in
        return list(obj._ref.get_polygons())
    if isinstance(obj, gdstk.Polygon):
        return [obj]
    if isinstance(obj, Iterable):
        out: list[gdstk.Polygon] = []
        for x in obj:
            out.extend(_as_polygon_list(x))
        return out
    raise TypeError(f"boolean: unsupported operand type {type(obj).__name__}")


def boolean(
    A=None,
    B=None,
    operation: str = "or",
    layer: Layer = (0, 0),
    **kwargs,
) -> "Component":
    """Boolean of A and B.

    Supports operations used in this repo: 'and', 'or', 'xor', 'not', 'A-B'.
    Accepts Component, ComponentReference, gdstk.Polygon, or iterables.
    """
    # gdsfactory-style keyword args
    if "A" in kwargs and A is None:
        A = kwargs["A"]
    if "B" in kwargs and B is None:
        B = kwargs["B"]

    op = operation.lower().strip()
    if op == "a-b":
        op = "not"
    if op not in ("and", "or", "xor", "not"):
        raise ValueError(f"boolean: unsupported operation {operation!r}")

    polys_a = _as_polygon_list(A)
    polys_b = _as_polygon_list(B) if B is not None else []
    l, dt = int(layer[0]), int(layer[1])
    result = gdstk.boolean(polys_a, polys_b, op, layer=l, datatype=dt)

    c = Component(_unique_name("boolean"))
    for p in result:
        c._cell.add(p)
    return c


# ---------------------------------------------------------------------------
# import_gds
# ---------------------------------------------------------------------------


def import_gds(
    gdspath: PathType,
    cellname: Optional[str] = None,
    **_kwargs,
) -> "Component":
    """Read `gdspath` and return its top cell (or the named cell) as a Component."""
    lib = gdstk.read_gds(str(gdspath))
    cells = {c.name: c for c in lib.cells}
    if cellname is not None:
        if cellname not in cells:
            raise KeyError(f"cell {cellname!r} not in {gdspath}")
        src = cells[cellname]
    else:
        # top cells = cells not referenced by any other cell
        referenced: set[str] = set()
        for c in lib.cells:
            for r in c.references:
                referenced.add(r.cell.name)
        tops = [c for c in lib.cells if c.name not in referenced]
        if not tops:
            raise ValueError(f"no top cell in {gdspath}")
        src = tops[0]

    # Wrap the gdstk.Cell in a Component without copying.
    wrapped = Component.__new__(Component)
    wrapped._cell = src
    wrapped.ports = {}
    wrapped._references = []
    for gref in src.references:
        # find target cell
        target = Component.__new__(Component)
        target._cell = gref.cell
        target.ports = {}
        target._references = []
        target._locked = False
        target.info = {}
        wrapper = ComponentReference(target, gref)
        wrapper.owner = wrapped
        wrapped._references.append(wrapper)
    wrapped._locked = False
    wrapped.info = {}
    return wrapped


# ---------------------------------------------------------------------------
# transformed — bake a ComponentReference's transform into a new Component
# ---------------------------------------------------------------------------


def transformed(ref: "ComponentReference") -> "Component":
    """Return a new Component whose contents are `ref.parent` flattened with
    the reference's transform applied. Ports are transformed accordingly."""
    if not isinstance(ref, ComponentReference):
        raise TypeError("transformed expects a ComponentReference")
    new = Component(_unique_name("transformed"))
    # Place the ref inside a throwaway cell and flatten to bake in transforms.
    new._cell.add(ref._ref)
    new._cell.flatten()
    # Transform ports
    origin = ref.origin
    rot = ref.rotation
    xr = ref.x_reflection
    for pname, p in ref.parent.ports.items():
        tp = _apply_transform_to_port(p, origin, rot, xr)
        tp.parent = new
        new.ports[pname] = tp
    return new


# ---------------------------------------------------------------------------
# route_quad — 4-sided polygon connecting two ports
# ---------------------------------------------------------------------------


def _port_end_corners(port: Port) -> tuple[Coord, Coord]:
    """Return the two corner points at the end of `port` (perpendicular to
    orientation, separated by port.width)."""
    cx, cy = port.center
    w = port.width / 2.0
    o = (port.orientation % 360.0 + 360.0) % 360.0
    # unit vector perpendicular to port's orientation
    # port points outward at angle `o`; the port face is perpendicular
    perp = math.radians(o + 90.0)
    dx, dy = math.cos(perp), math.sin(perp)
    return ((cx + dx * w, cy + dy * w), (cx - dx * w, cy - dy * w))


def route_quad(
    port1: Port,
    port2: Port,
    layer: Optional[Layer] = None,
    width1: Optional[float] = None,
    width2: Optional[float] = None,
    manhattan_target_step: Optional[float] = None,
    **_kwargs,
) -> "Component":
    """Create a Component holding a 4-vertex polygon that joins `port1`-`port2`.

    Matches the gdsfactory.routing.route_quad signature used in this repo.
    Each port's end-face becomes one side of the quadrilateral. Widths
    override the port widths if given.
    """
    if layer is None:
        layer = port1.layer if port1.layer is not None else (0, 0)
    p1 = port1.copy()
    p2 = port2.copy()
    if width1 is not None:
        p1.width = float(width1)
    if width2 is not None:
        p2.width = float(width2)
    a, b = _port_end_corners(p1)
    c, d = _port_end_corners(p2)
    # Order so the quad doesn't self-intersect: a, b, c, d where b→c crosses
    # from port1 to port2 on one side and d→a on the other.
    points = [a, b, c, d]
    # Ensure consistent winding by picking the ordering with the smaller
    # total perimeter (the non-self-intersecting one).
    def perim(pts):
        return sum(math.hypot(pts[(i+1) % 4][0] - pts[i][0],
                              pts[(i+1) % 4][1] - pts[i][1]) for i in range(4))
    alt = [a, b, d, c]
    if perim(alt) < perim(points):
        points = alt
    comp = Component(_unique_name("route_quad"))
    comp.add_polygon(points, layer=tuple(layer))
    return comp


__all__ = [
    "Component",
    "ComponentReference",
    "Port",
    "Polygon",
    "Layer",
    "PathType",
    "Pdk",
    "ComponentOrReference",
    "snap_to_grid",
    "cell",
    "clear_cache",
    "copy",
    "rectangle",
    "rectangular_ring",
    "boolean",
    "import_gds",
    "transformed",
    "route_quad",
]
