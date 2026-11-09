from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Pin:
    name: str
    net: str
    x: float            # local coordinates of the cell
    y: float            # edge position (top edge y for side 'top', bottom edge y for 'bottom')
    side: Literal["top", "bottom"]
    width: float
    layer: tuple        # met2 layer tuple
    terminals: list = field(default_factory=list)


@dataclass
class PinCell:
    name: str
    component: object                  # Component in local coordinates
    pins: list                         # list[Pin]
    polarity: Literal["n", "p", "passive"]
    bbox: tuple                        # (x0,y0,x1,y1) in local coordinates
    active_bbox: tuple | None = None   # extent of diffusion (for tap spacing)
    well_bbox: tuple | None = None     # extent of the cell's own nwell (p cells)
    implant_bbox: tuple | None = None
    body_net: str | None = None
    info: dict = field(default_factory=dict)

    def pins_on(self, side):
        return [p for p in self.pins if p.side == side]
