"""Layout backend selector.

All glayout code imports layout primitives from this package instead of
reaching into gdsfactory directly. That gives a single switch — set by the
`GLAYOUT_BACKEND` env var or `set_backend(...)` — between:

  - "gdsfactory" (default): thin passthrough to gdsfactory. Preserves
    existing behavior so the repo keeps working unchanged.
  - "gdstk": native gdstk implementation. Faster; intended to be the
    eventual default.

Only symbols gLayout actually uses are exposed. Both backends present the
same surface.
"""
import os

_VALID = ("gdsfactory", "gdstk")
_backend = os.environ.get("GLAYOUT_BACKEND", "gdsfactory").lower().strip()

_EXPORTS = (
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
)


def _load(name: str):
    if name == "gdstk":
        from . import _gdstk as mod
    elif name == "gdsfactory":
        from . import _gdsfactory as mod
    else:
        raise ValueError(f"unknown GLAYOUT_BACKEND={name!r}; valid: {_VALID}")
    return mod


def _bind(mod) -> None:
    g = globals()
    for name in _EXPORTS:
        g[name] = getattr(mod, name)


def get_backend() -> str:
    return _backend


def set_backend(name: str) -> None:
    """Switch backend at runtime. Rebinds the module-level names for callers
    that do `from glayout.backend import X` AFTER this call."""
    global _backend
    name = name.lower().strip()
    if name not in _VALID:
        raise ValueError(f"unknown backend {name!r}; valid: {_VALID}")
    _backend = name
    _bind(_load(name))


_bind(_load(_backend))

# Opt-in debug tagging of geometry with the code that drew it.
if os.environ.get("GLAYOUT_PROVENANCE"):
    from glayout.util import provenance as _provenance
    _provenance.enable()

__all__ = (*_EXPORTS, "get_backend", "set_backend")
