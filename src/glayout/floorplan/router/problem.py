"""The routing problem (cells, pins and their access options) and the routing result."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from glayout.floorplan.router.geometry import Rect
from glayout.floorplan.router.tech import RouterTech

if TYPE_CHECKING:
    from glayout.floorplan.router.grid import RoutingGrid


@dataclass
class AccessOption:
    """One port a pin can be reached through: the cell side it faces, its centre, layer and width.

    ``foreign`` lists the cell's other shapes in the stub's corridor, each as an absolute
    rectangle plus the spacing the stub must keep to it.
    """
    side: str
    x: float                # absolute port centre
    y: float
    layer: str
    width: float
    foreign: tuple[tuple[float, float, float, float, float], ...] = ()   # absolute rect + spacing to keep


@dataclass
class RouterPin:
    """A pin to connect: its net, a readable owner name, the index of its cell, and its access options."""
    net: str
    owner: str              # e.g. "DP.VOUT1"
    cell: int               # index of the obstacle this pin belongs to
    options: list[AccessOption]


@dataclass
class RoutingProblem:
    """Routing area (from the origin), cell bounding boxes as obstacles, and the pins of every net."""
    width: float
    height: float
    cells: list[Rect]                       # obstacles (cell bounding boxes)
    nets: dict[str, list[RouterPin]]


@dataclass
class Landing:
    """Where a pin joins the grid: the option used, the via point, and the stub and pads drawn there.

    ``node`` is the pin's own graph node, ``("P", k)``; ``neighbours`` are the grid nodes a wire
    may leave it through.
    """
    pin: RouterPin
    option: AccessOption
    x: float                # landing (via) point
    y: float
    z: int                  # router layer of the pin node
    node: tuple
    neighbours: list[tuple]
    shapes: list[tuple[str, Rect]]          # stub + via pads, for geometry and spacing checks


@dataclass
class RoutingResult:
    """Outcome of ``route``: success, the paths and landings of every net, and their cost.

    ``wirelength`` and ``vias`` include the stubs and one via stack per landing. ``hotspots``
    are the points where routing failed, which the closed loop uses to choose what to pad.
    """
    success: bool
    iterations: int
    failed_nets: list[str]
    unreachable: list[str]                  # pins that got no legal landing
    paths: dict[str, list[list[tuple]]]     # net -> node paths
    landings: dict[str, list[Landing]]
    wirelength: float
    vias: int
    conflicts: int
    tech: RouterTech
    grid: "RoutingGrid"
    history: list[dict] = field(default_factory=list)
    hotspots: list[tuple[float, float]] = field(default_factory=list)   # where routing failed

    def summary(self) -> dict:
        """The headline numbers as a plain dict (what the annealer's router check returns)."""
        return {"success": self.success, "iterations": self.iterations, "failed_nets": self.failed_nets,
                "unreachable": self.unreachable, "wirelength_um": round(self.wirelength, 3),
                "vias": self.vias, "conflicts": self.conflicts, "hotspots": len(self.hotspots)}
