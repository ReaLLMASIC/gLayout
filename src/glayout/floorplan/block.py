"""Block abstraction: what the floorplanner needs to know about a cell.

A ``Block`` is one functional group (a mirror, a differential pair, ...)
with one or more ``Variant``s: the same circuit drawn with a different shape,
e.g. the same total W split into 2, 4 or 8 fingers. These are the paper's
"candidate shapes" (§1.3). Each variant records its bounding box and its
external pins, with positions relative to the bbox lower-left corner and the
sides from which a router can reach them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from glayout.backend import Component
from glayout.pdk.mappedpdk import MappedPDK
from glayout.util.process_table import ProcessTable, print_table

_SIDE = {0: "E", 90: "N", 180: "W", 270: "S"}


@dataclass
class Access:
    """A port a router can leave the block from, relative to the bbox lower-left."""
    side: str             # N/E/S/W: direction the port faces
    x: float
    y: float
    layer: str
    width: float
    # (x0, y0, x1, y1, spacing): bboxes of the cell's *other* shapes on ``layer``
    # between the port and the cell edge. A stub leaving through this port must
    # stay ``spacing`` away: the layer rule, or less where the cell itself already
    # sits closer to the port's own metal (a stub that continues a rail keeps
    # the rail's spacing; glayout's rules can be stricter than the DRC deck's)
    foreign: tuple[tuple[float, float, float, float, float], ...] = ()


@dataclass
class Pin:
    net: str
    x: float              # relative to the variant bbox lower-left, µm
    y: float
    sides: str            # subset of "NESW": where the pin's metal reaches the block edge
    layer: str = ""
    ports: tuple[str, ...] = ()
    access: tuple[Access, ...] = ()

    @property
    def horizontal(self) -> bool:
        """Exits left/right (counts toward left/right padding)."""
        return "E" in self.sides or "W" in self.sides

    @property
    def vertical(self) -> bool:
        return "N" in self.sides or "S" in self.sides


@dataclass
class Padding:
    left: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    top: float = 0.0


@dataclass
class Variant:
    params: dict
    width: float
    height: float
    pins: dict[str, Pin]
    component: Optional[Component] = None
    pad: Padding = field(default_factory=Padding)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def padded_size(self) -> tuple[float, float]:
        return (self.width + self.pad.left + self.pad.right, self.height + self.pad.bottom + self.pad.top)

    def pin_xy(self, net: str, mirrored: bool = False) -> tuple[float, float]:
        """Pin position relative to the *padded* box lower-left."""
        p = self.pins[net]
        x = self.width - p.x if mirrored else p.x
        return (self.pad.left + x, self.pad.bottom + p.y)


@dataclass
class Block:
    name: str
    kind: str                       # functional type, e.g. "CM", "DP", "CS", "BIAS"
    variants: list[Variant]

    @property
    def nets(self) -> list[str]:
        return list(self.variants[0].pins)

    @property
    def area(self) -> float:
        """Smallest variant area: the block's intrinsic area."""
        return min(v.area for v in self.variants)


def _bboxes(component: Component, layer) -> list[tuple[float, float, float, float]]:
    out = []
    for poly in component.extract(layers=[layer]).get_polygons():
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        out.append((min(xs), min(ys), max(xs), max(ys)))
    return out


def _foreign_shapes(boxes, port, bbox, sep: float, band: float = 2.5) -> tuple:
    """Shapes in the stub corridor from ``port`` to the cell edge that are not
    the port's own metal (the shape under the port and what touches it), each
    with the spacing a stub must keep to it."""
    (x0, y0), (x1, y1) = bbox
    px, py = float(port.center[0]), float(port.center[1])
    side = _SIDE.get(round(port.orientation) % 360, "")
    if side == "W":
        corr = (x0, py - band, px + band, py + band)
    elif side == "E":
        corr = (px - band, py - band, x1, py + band)
    elif side == "S":
        corr = (px - band, y0, px + band, py + band)
    else:
        corr = (px - band, py - band, px + band, y1)
    eps = 1e-6
    own = [b for b in boxes if b[0] - eps <= px <= b[2] + eps and b[1] - eps <= py <= b[3] + eps]
    for _ in range(2):   # what touches the port's own shape is the same net
        own += [b for b in boxes if b not in own and any(
            b[0] <= o[2] + eps and o[0] <= b[2] + eps and b[1] <= o[3] + eps and o[1] <= b[3] + eps for o in own)]
    out = []
    for b in boxes:
        if b in own or not (b[0] < corr[2] and corr[0] < b[2] and b[1] < corr[3] and corr[1] < b[3]):
            continue
        d = min(max(max(o[0] - b[2], b[0] - o[2]), max(o[1] - b[3], b[1] - o[3])) for o in own) if own else sep
        out.append((*b, min(sep, d) if d > 0 else sep))
    return tuple(out)


def extract_pins(component: Component, net_ports: Mapping[str, Sequence[str]],
                 pdk: Optional[MappedPDK] = None) -> dict[str, Pin]:
    """One Pin per net, at the mean of the given ports' centres."""
    (x0, y0), _ = component.bbox
    pins = {}
    layer_boxes: dict = {}
    for net, names in net_ports.items():
        ports = [component.ports[n] for n in names if n in component.ports]
        if not ports:
            raise KeyError(f"net {net}: none of the ports {list(names)} exist")
        cx = sum(p.center[0] for p in ports) / len(ports) - x0
        cy = sum(p.center[1] for p in ports) / len(ports) - y0
        sides = "".join(sorted({_SIDE.get(round(p.orientation) % 360, "") for p in ports}))
        layer = pdk.layer_to_glayer(ports[0].layer) if pdk is not None else str(ports[0].layer)
        access = []
        for p in ports:
            key = tuple(p.layer)
            if key not in layer_boxes:
                layer_boxes[key] = _bboxes(component, p.layer)
            lname = pdk.layer_to_glayer(p.layer) if pdk is not None else str(p.layer)
            try:
                sep = float(pdk.get_grule(lname)["min_separation"]) if pdk is not None else 0.0
            except Exception:
                sep = 0.0
            foreign = _foreign_shapes(layer_boxes[key], p, component.bbox, sep)
            access.append(Access(_SIDE.get(round(p.orientation) % 360, ""), p.center[0] - x0, p.center[1] - y0,
                                 pdk.layer_to_glayer(p.layer) if pdk is not None else str(p.layer), float(p.width),
                                 tuple((b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0, b[4]) for b in foreign)))
        access = tuple(access)
        pins[net] = Pin(net, cx, cy, sides, layer, tuple(p.name for p in ports), access)
    return pins


def build_block(
    pdk: MappedPDK,
    name: str,
    kind: str,
    builder: Callable[..., Component],
    variants: Sequence[Mapping[str, Any]],
    net_ports: Optional[Callable[[Component], Mapping[str, Sequence[str]]]] = None,
) -> Block:
    """Build every variant of a block and extract its pins.

    ``net_ports(component)`` maps nets to port names; by default it reads
    ``component.info["pins"]`` (set by the finger-sequence cells).
    """
    built = []
    with ProcessTable(f"Block {name}", f"{kind}, {len(variants)} variant(s)") as pt:
        for i, params in enumerate(variants):
            with pt.stage(f"variant {i}") as st:
                comp = builder(pdk, **params)
                ports = net_ports(comp) if net_ports else comp.info["pins"]
                pins = extract_pins(comp, ports, pdk)
                v = Variant(dict(params), float(comp.xsize), float(comp.ysize), pins, comp)
                built.append(v)
                st.detail(f"{_short(params)} → {v.width:.2f}x{v.height:.2f}µm, {len(pins)} pins")
        pt.result("nets", ",".join(built[0].pins))
        pt.result("min_area_um2", f"{min(v.area for v in built):.1f}")
    return Block(name, kind, built)


def _short(params: Mapping[str, Any]) -> str:
    return " ".join(f"{k}={v}" for k, v in params.items() if k not in ("pdk",))


def print_blocks(blocks: Sequence[Block], title: str = "Blocks") -> None:
    rows = []
    for b in blocks:
        for i, v in enumerate(b.variants):
            pw, ph = v.padded_size
            rows.append((b.name, b.kind, i, _short(v.params), f"{v.width:.2f}x{v.height:.2f}",
                         f"{v.width / v.height:.2f}", f"{pw:.2f}x{ph:.2f}",
                         f"L{v.pad.left:.2f} R{v.pad.right:.2f} B{v.pad.bottom:.2f} T{v.pad.top:.2f}"))
    print_table(title, ["block", "kind", "var", "params", "size µm", "aspect", "padded µm", "padding µm"], rows)
