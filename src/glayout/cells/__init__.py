"""Canonical package for analog cell generators.

This package supersedes the historical ``glayout.blocks`` namespace while the
compatibility layer remains available for downstream users.
"""

from . import composite, elementary
from glayout.cells.elementary import (
    add_tg_labels,
    current_mirror,
    current_mirror_netlist,
    diff_pair,
    diff_pair_generic,
    diff_pair_netlist,
    flipped_voltage_follower,
    fvf_netlist,
    sky130_add_fvf_labels,
    tg_netlist,
    transmission_gate,
)

# Preserve the old export name for callers that used ``add_fvf_labels``.
add_fvf_labels = sky130_add_fvf_labels

__all__ = [
    "add_fvf_labels",
    "add_tg_labels",
    "composite",
    "current_mirror",
    "current_mirror_netlist",
    "diff_pair",
    "diff_pair_generic",
    "diff_pair_netlist",
    "elementary",
    "flipped_voltage_follower",
    "fvf_netlist",
    "sky130_add_fvf_labels",
    "tg_netlist",
    "transmission_gate",
]
