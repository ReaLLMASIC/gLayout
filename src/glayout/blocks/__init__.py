"""Compatibility layer for the historical ``glayout.blocks`` namespace."""

from __future__ import annotations

import sys

from glayout import verification as _verification
from glayout.cells import composite as _composite
from glayout.cells import elementary as _elementary
from glayout.cells import (
    add_fvf_labels,
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

# Alias the old package paths so nested imports keep working after the move to
# ``glayout.cells`` and ``glayout.verification``.
sys.modules.setdefault(f"{__name__}.elementary", _elementary)
sys.modules.setdefault(f"{__name__}.composite", _composite)
sys.modules.setdefault(f"{__name__}.evaluator_box", _verification)

__all__ = [
    "add_fvf_labels",
    "add_tg_labels",
    "current_mirror",
    "current_mirror_netlist",
    "diff_pair",
    "diff_pair_generic",
    "diff_pair_netlist",
    "flipped_voltage_follower",
    "fvf_netlist",
    "sky130_add_fvf_labels",
    "tg_netlist",
    "transmission_gate",
]
