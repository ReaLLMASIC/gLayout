"""Adapters that turn layout components into textbook_sharing.assembly PinCells."""
from __future__ import annotations
from .pincell import PinCell, Pin


def from_group_result(res, name: str, polarity: str, body_net: str) -> PinCell:
    """glayout.sharing GroupResult -> PinCell (pins are already met2 pads on the top/bottom edges)."""
    comp = res.component
    meta = comp.info["pin_meta"]
    pins = []
    for pname, m in meta.items():
        pins.append(Pin(pname, m["net"], m["x"], m["y"], m["side"], m["width"], tuple(comp.ports[pname].layer), m.get("terminals", [])))
    bb = res.geometry_stats["bbox"]
    W = res.geometry_stats["unit_width"]
    # active extent: from the outermost diffusion pins when the group does not report it (y spans [0, W])
    act_x0 = min(m["x"] for m in meta.values() if m["side"] == "top" and "node" in m) - 0.5
    act_x1 = max(m["x"] for m in meta.values() if m["side"] == "top" and "node" in m) + 0.5
    active_bbox = res.geometry_stats.get("active_bbox", (act_x0, 0.0, act_x1, W))
    return PinCell(name, comp, pins, polarity, tuple(bb), active_bbox=active_bbox, body_net=body_net,
                   info={"group_stats": res.geometry_stats, "evidence": res.physical_sharing_evidence, "device_map": res.device_map, "applied_plan": res.applied_plan})
