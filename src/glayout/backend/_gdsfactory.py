"""gdsfactory passthrough backend.

Re-exports the gdsfactory symbols the rest of glayout depends on, under the
same names the gdstk backend uses. This keeps `from glayout.backend import X`
working identically regardless of which backend is active.
"""
from gdsfactory.component import Component, copy
from gdsfactory.component_reference import ComponentReference
from gdsfactory.port import Port
from gdsfactory.polygon import Polygon
from gdsfactory.cell import cell, clear_cache
from gdsfactory.components.rectangle import rectangle
from gdsfactory.components.rectangular_ring import rectangular_ring
from gdsfactory.snap import snap_to_grid
from gdsfactory.functions import transformed
from gdsfactory.geometry.boolean import boolean
from gdsfactory.read.import_gds import import_gds
from gdsfactory.routing.route_quad import route_quad
from gdsfactory.typings import Layer, ComponentOrReference, PathType

# Pdk lives in a separate module in newer gdsfactory
try:
    from gdsfactory.pdk import Pdk
except Exception:  # pragma: no cover
    from typing import Any as Pdk  # type: ignore


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


# gdsfactory 7.7 truncates fractional nanometres to int(0), producing NaN
# ports for a 0.5nm PDK. Preserve its behavior for planar PDKs, but keep the
# fractional grid for FinFETs. Patch the core aliases used to copy ports too.
def _fractional_snap(x, grid_factor=1):
    from glayout.pdk.finfet import _active_technology
    technology = _active_technology.get()
    if technology is None:
        return _original_snap(x, grid_factor=grid_factor)
    import numpy as np
    pitch = technology.manufacturing_grid * grid_factor
    result = pitch * np.round(np.asarray(x, dtype=float) / pitch)
    if isinstance(x, tuple):
        return tuple(result)
    if np.isscalar(x):
        return float(result)
    return result


_original_snap = snap_to_grid
snap_to_grid = _fractional_snap
import importlib as _importlib
for _name in ('snap', 'port', 'component', 'component_reference'):
    _module = _importlib.import_module('gdsfactory.' + _name)
    if hasattr(_module, 'snap_to_grid'):
        _module.snap_to_grid = _fractional_snap


def _fractional_port_snap(x,grid_factor=1):
    from glayout.pdk.finfet import _active_technology
    if _active_technology.get() is None:return _original_snap(x,grid_factor=grid_factor)
    # An on-grid edge with an odd number of grid units has a half-grid
    # midpoint. Preserve it when gdsfactory constructs or copies a Port.
    import numpy as np
    pitch=_active_technology.get().manufacturing_grid*grid_factor/2
    result=pitch*np.round(np.asarray(x,dtype=float)/pitch)
    return tuple(result) if isinstance(x,tuple) else float(result) if np.isscalar(x) else result

_importlib.import_module('gdsfactory.port').snap_to_grid=_fractional_port_snap
