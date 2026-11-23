"""Router technology: layers, pitch, wire widths, spacing rules, via pads and search costs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from glayout.floorplan.router.geometry import H, V


@dataclass
class RouterTech:
    """Everything the router needs to know about the process, and its cost constants.

    Costs left at 0 are set from the pitch (``__post_init__``). ``access_pads`` gives, for a pin
    on ``port layer`` landing on router layer ``z``, the pad size the via stack draws on each
    metal layer; stubs and landings are checked against ``layer_sep`` on those layers.
    """
    layers: tuple[str, str]                  # (horizontal, vertical) glayer names
    pitch: float
    wire: tuple[float, float]                # drawn wire width per router layer
    sep: tuple[float, float]                 # spacing rule per router layer
    layer_sep: dict[str, float]              # spacing rule for every layer a stub/pad may use
    access_pads: dict[tuple[str, int], dict[str, float]]   # (port layer, landing z) -> {layer: pad}
    snap: Callable[[float], float] = lambda v: v
    c_via: float = 0.0
    c_drc: float = 0.0
    h_inc: float = 0.0
    q: float = 1e-4
    kappa: float = 3.0
    max_iterations: int = 35
    detour_ratio: float = 2.0                # 0 turns detour re-landing off
    detour_min: float = 0.0                  # minimum excess wire to count as a detour
    max_relands: int = 8

    def __post_init__(self):
        """Default the costs from the pitch: via 2p, conflict 20p, history step 2p, detour minimum 4p."""
        p = self.pitch
        self.c_via = self.c_via or 2 * p
        self.c_drc = self.c_drc or 20 * p
        self.h_inc = self.h_inc or 2 * p
        self.detour_min = self.detour_min or 4 * p

    def pad(self, port_layer: str, z: int, layer: str) -> float:
        """Pad size on ``layer`` of the via stack from ``port_layer`` up to router layer ``z`` (0 if none)."""
        return self.access_pads.get((port_layer, z), {}).get(layer, 0.0)

    @classmethod
    def from_pdk(cls, pdk, layers: Sequence[str] = ("met3", "met4"), **costs) -> "RouterTech":
        """Measure the via stacks of ``pdk`` and derive pitch, wire widths and pads.

        Wires are drawn at via-pad width, so a via never needs extra enclosure, and the pitch is
        the larger of (pad + spacing) on the two layers, so a via or wire end on any node is
        legal next to any other net on the neighbouring tracks. ``costs`` override the defaults.
        """
        from glayout.primitives.via_gen import via_stack
        from glayout.util.comp_utils import evaluate_bbox
        pdk.activate()

        def pads(a: str, b: str) -> dict[str, float]:
            """Pad size on each metal layer of the via stack from ``a`` to ``b``."""
            v = via_stack(pdk, a, b)
            out = {}
            for lay in v.get_layers():
                g = pdk.layer_to_glayer(tuple(lay))
                if g.startswith("met"):
                    out[g] = max(evaluate_bbox(v.extract(layers=[tuple(lay)])))
            return out

        hl, vl = layers
        grid_pads = pads(hl, vl)
        wire = (grid_pads[hl], grid_pads[vl])
        sep = (float(pdk.get_grule(hl)["min_separation"]), float(pdk.get_grule(vl)["min_separation"]))
        pitch = pdk.snap_to_2xgrid(max(wire[0] + sep[0], wire[1] + sep[1]))
        access = {}
        for port_layer in ("met1", "met2"):
            for z, top in ((H, hl), (V, vl)):
                access[(port_layer, z)] = pads(port_layer, top)
        layer_sep = {f"met{i}": float(pdk.get_grule(f"met{i}")["min_separation"]) for i in range(1, 6)}
        return cls(tuple(layers), pitch, wire, sep, layer_sep, access, snap=pdk.snap_to_2xgrid, **costs)

    @classmethod
    def abstract(cls, pitch: float = 1.0, **costs) -> "RouterTech":
        """Unit tech for tests: pads = wire = 0.5·pitch, spacing = 0.5·pitch."""
        w, s = 0.5 * pitch, 0.5 * pitch
        pads = {"met1": w, "met2": w, "met3": w, "met4": w}
        access = {(pl, z): dict(pads) for pl in ("met1", "met2") for z in (H, V)}
        return cls(("met3", "met4"), pitch, (w, w), (s, s), {k: s for k in pads}, access, **costs)


def track_pitch(pdk, layers: Sequence[str] = ("met3", "met4")) -> float:
    """The router's pitch on ``layers`` for ``pdk`` (one routing track, as DRR padding counts them)."""
    return RouterTech.from_pdk(pdk, layers).pitch
