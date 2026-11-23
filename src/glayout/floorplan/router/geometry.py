"""Geometry shared by the router modules: layer indices, rectangles and the spacing test."""
from __future__ import annotations

H, V = 0, 1                                   # router layer 0 carries horizontal wires, layer 1 vertical ones
Rect = tuple[float, float, float, float]      # x0, y0, x1, y1

# unit step away from a cell, for a port facing each side
DIRS = {"W": (-1, 0), "E": (1, 0), "S": (0, -1), "N": (0, 1)}


def gap(a: Rect, b: Rect) -> tuple[float, float]:
    """(x gap, y gap) between two rectangles; negative along an axis where they overlap."""
    return (max(b[0] - a[2], a[0] - b[2]), max(b[1] - a[3], a[1] - b[3]))


def too_close(a: Rect, b: Rect, sep: float, eps: float = 1e-9) -> bool:
    """Square-metric spacing check (stricter than euclidean at corners).

    True when the rectangles are closer than ``sep`` along both axes, which includes overlapping.
    """
    gx, gy = gap(a, b)
    return gx < sep - eps and gy < sep - eps


def square(x: float, y: float, s: float) -> Rect:
    """Square of side ``s`` centred on (x, y)."""
    return (x - s / 2, y - s / 2, x + s / 2, y + s / 2)
