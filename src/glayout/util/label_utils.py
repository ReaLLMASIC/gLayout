"""PDK-agnostic helpers for adding LVS pin rectangles and text labels to a cell.

Two labeling paradigms were previously copy-pasted across the codebase.

Both are unified here. Layers are resolved from the PDK's ``<glayer>_pin`` /
``<glayer>_label`` glayers, and the glayer defaults to the *port's own* metal
(``pdk.layer_to_glayer(port.layer)``) so a pin always lands on the same layer as the
port it marks -- correct on any PDK, and immune to sky130's glayer/li1 offset that the
old hardcoded constants could get wrong.
"""

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Union

from glayout.backend import Component, Port, rectangle
from glayout.pdk.mappedpdk import MappedPDK
from glayout.util.comp_utils import align_comp_to_port


@dataclass
class LabelSpec:
    """One label: which ``name`` goes on which ``port``.

    port:      a port name (looked up on the component) or a ``Port`` object.
    glayer:    generic layer (e.g. ``"met2"``); ``None`` derives it from the port.
    size:      pin-rectangle size, a float (square) or ``(x, y)``.
    alignment: how the pin rect is aligned to the port (see ``align_comp_to_port``).
    """

    name: str
    port: Union[str, Port]
    glayer: Optional[str] = None
    size: Union[float, tuple[float, float]] = 0.5
    alignment: tuple[str, str] = ("c", "b")


SpecLike = Union[LabelSpec, tuple]


def _as_spec(spec: SpecLike) -> LabelSpec:
    """Coerce a tuple into a LabelSpec, positionally in field order:
    ``(name, port[, glayer[, size[, alignment]]])``."""
    if isinstance(spec, LabelSpec):
        return spec
    if isinstance(spec, tuple) and 2 <= len(spec) <= 5:
        out = LabelSpec(*spec)
        # `glayer` is the third field, but the label tables this replaced were
        # (comp, port, alignment) triples. Catch a tuple landing in the glayer
        # slot here rather than failing later inside get_glayer("('c', 'b')").
        if out.glayer is not None and not isinstance(out.glayer, str):
            raise TypeError(
                f"glayer must be a glayer name, got {out.glayer!r}. Alignment is "
                "the 5th element -- pass LabelSpec(name, port, alignment=...) instead."
            )
        return out
    raise TypeError(f"cannot interpret label spec: {spec!r}")


def _as_xy(size: Union[float, tuple[float, float]]) -> tuple[float, float]:
    return size if isinstance(size, tuple) else (size, size)


def _resolve_port(component: Component, port: Union[str, Port]) -> Port:
    return component.ports[port] if isinstance(port, str) else port


def _port_glayer(pdk: MappedPDK, port: Port, glayer: Optional[str]) -> str:
    return glayer if glayer is not None else pdk.layer_to_glayer(port.layer)


def add_pin_label(
    component: Component,
    pdk: MappedPDK,
    port: Port,
    name: str,
    *,
    glayer: Optional[str] = None,
    size: Union[float, tuple[float, float]] = 0.5,
    alignment: tuple[str, str] = ("c", "b"),
) -> Component:
    """Add a single LVS pin rectangle + text label at ``port``.

    The rectangle is drawn on ``<glayer>_pin`` and the text on ``<glayer>_label``,
    where ``glayer`` defaults to the port's own metal.
    """
    glayer = _port_glayer(pdk, port, glayer)
    pin = rectangle(
        layer=pdk.get_glayer(f"{glayer}_pin"), size=_as_xy(size), centered=True
    ).copy()
    pin.add_label(text=name, layer=pdk.get_glayer(f"{glayer}_label"))
    component.add(align_comp_to_port(pin, port, alignment=alignment))
    return component


def add_pin_labels(
    component: Component,
    pdk: MappedPDK,
    specs: Iterable[SpecLike],
    *,
    flatten: bool = True,
) -> Component:
    """Add LVS pin rectangles + labels for every spec.

    Replaces the ``move_info`` boilerplate in the ``sky130_add_*_labels`` functions;
    each caller now supplies only its port->name data table.
    """
    component.unlock()
    for raw in specs:
        spec = _as_spec(raw)
        port = _resolve_port(component, spec.port)
        add_pin_label(
            component,
            pdk,
            port,
            spec.name,
            glayer=spec.glayer,
            size=spec.size,
            alignment=spec.alignment,
        )
    return component.flatten() if flatten else component


def expose_ports(
    component: Component,
    pdk: MappedPDK,
    specs: Iterable[SpecLike],
    *,
    inset: float = 0.1,
) -> Component:
    """Register a named ``Port`` and drop an inward-offset text label for each spec.

    Replaces the inline ``expose()`` closures in the gf180 cells: a routing port plus
    a text label nudged ``inset`` um inside the shape (so Magic attaches it to the
    underlying geometry). No pin rectangle is added.
    """
    for raw in specs:
        spec = _as_spec(raw)
        port = _resolve_port(component, spec.port)
        component.add_port(name=spec.name, port=port)
        glayer = _port_glayer(pdk, port, spec.glayer)
        angle = port.orientation
        if angle is not None:
            dx = -inset * math.cos(math.radians(angle))
            dy = -inset * math.sin(math.radians(angle))
        else:
            dx, dy = 0.0, 0.0
        pos = (port.center[0] + dx, port.center[1] + dy)
        component.add_label(
            text=spec.name, position=pos, layer=pdk.get_glayer(f"{glayer}_label")
        )
    return component
