"""Lazy-safe PDK exports.

Importing the package should not hard-fail when local PDK files are absent.
The concrete mapped PDK objects remain ``None`` until their environments are
available.
"""

try:
    from .gf180_mapped.gf180_mapped import gf180_mapped_pdk
except Exception:
    gf180_mapped_pdk = None

try:
    from .ihp130_mapped.ihp130_mapped import ihp130_mapped_pdk
except Exception:
    ihp130_mapped_pdk = None

try:
    from .sky130_mapped.sky130_mapped import sky130_mapped_pdk
except Exception:
    sky130_mapped_pdk = None

__all__ = [
    "gf180_mapped_pdk",
    "ihp130_mapped_pdk",
    "sky130_mapped_pdk",
]
