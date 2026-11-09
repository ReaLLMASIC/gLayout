"""The three open PDKs, as mapped by gLayout."""
from __future__ import annotations
import importlib

PDKS = {"sky130": "glayout.pdk.sky130_mapped:sky130_mapped_pdk",
        "gf180": "glayout.pdk.gf180_mapped:gf180_mapped_pdk",
        "ihp130": "glayout.pdk.ihp130_mapped:ihp130_mapped_pdk"}
_CACHE = {}


def load_pdk(name: str):
    mod, attr = PDKS[name].split(":")
    return getattr(importlib.import_module(mod), attr)


def pdk_obj(name: str):
    """Cached MappedPDK object for 'sky130', 'gf180' or 'ihp130'."""
    if name not in _CACHE:
        _CACHE[name] = load_pdk(name)
    return _CACHE[name]
