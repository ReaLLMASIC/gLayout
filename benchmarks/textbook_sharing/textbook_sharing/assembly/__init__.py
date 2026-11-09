"""textbook_sharing.assembly: harness-provided row/channel assembly for small analog cells.

Used identically by the baseline (upstream gLayout primitives) and the extended
(glayout.sharing groups) tracks.  It knows nothing about sharing: it takes
*pin cells* (a layout component plus a list of net-labelled pins on its top or
bottom edge), stacks them in polarity-homogeneous rows, connects equal nets
with met3 trunks in the channels between rows via met2 stubs, adds tap strips,
row-level well/implant blankets and port labels, and reports geometry
statistics (bounding box, wire length, via counts).
"""
from .pincell import PinCell, Pin
from .engine import RowSpec, assemble, AssemblyError
from glayout.sharing.rules import rules_for, GroupRules
__all__ = ["PinCell", "Pin", "RowSpec", "assemble", "AssemblyError", "rules_for", "GroupRules"]
