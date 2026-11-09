"""Dynamic routing resource (DRR) padding, paper Eq. 2:

    λ_[h,v] = ζ + |p_[h,v]| · (max spacing + max width)

``|p_h|`` counts pins that leave the block left/right (they pad left and
right), ``|p_v|`` pins that leave top/bottom (they pad top and bottom). The
bracket is one routing track: the inter-block router's pitch (via pad +
spacing on met3/met4 by default), so the padding is sized for that router.

``ζ`` is the paper's minimum grid step. Here it is half the largest spacing
rule between two blocks' outer layers (wells, taps, metals), so two padded
blocks that abut are always DRC-legal with each other, even with scale=0.
``scale`` multiplies the track term: 1 is the paper, 0 is the "without DRR"
ablation of Table 5.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

from glayout.floorplan.block import Block, Padding
from glayout.pdk.mappedpdk import MappedPDK
from glayout.util.process_table import ProcessTable


def _rule(pdk: MappedPDK, layer: str, key: str) -> float:
    try:
        return float(pdk.get_grule(layer)[key])
    except Exception:
        return 0.0


def block_keepout(pdk: MappedPDK) -> float:
    """Smallest gap that keeps any two glayout cells legal with each other."""
    layers = ["nwell", "pwell", "active_tap", "active_diff", "n+s/d", "p+s/d"] + [f"met{i}" for i in range(1, 6)]
    return pdk.snap_to_2xgrid(max(_rule(pdk, l, "min_separation") for l in layers))


def routing_track(pdk: MappedPDK, layers: Sequence[str] = ("met3", "met4")) -> float:
    """One routing track = the inter-block router's pitch on these layers
    (via pad + spacing), so the padding holds exactly the tracks the router uses."""
    from glayout.floorplan.router import track_pitch
    return track_pitch(pdk, layers)


def apply_drr(pdk: MappedPDK, blocks: Iterable[Block], scale: float = 1.0,
              layers: Sequence[str] = ("met3", "met4"), zeta: float | None = None,
              scales: Optional[Mapping[str, float]] = None, title: str = "DRR padding") -> dict:
    """Set ``variant.pad`` on every variant of every block. Returns the parameters used.

    ``scales`` overrides ``scale`` per block name (the router-feedback loop uses it).
    """
    blocks = list(blocks)
    zeta = pdk.snap_to_2xgrid(block_keepout(pdk) / 2) if zeta is None else zeta
    track = routing_track(pdk, layers)
    scales = dict(scales or {})
    with ProcessTable(title, f"ζ={zeta}µm, track={track}µm ({'/'.join(layers)}), scale={scales or scale}") as pt:
        for b in blocks:
            with pt.stage(b.name) as st:
                parts = []
                sc = scales.get(b.name, scale)
                for i, v in enumerate(b.variants):
                    n_h = sum(p.horizontal for p in v.pins.values())
                    n_v = sum(p.vertical for p in v.pins.values())
                    lh = pdk.snap_to_2xgrid(zeta + sc * n_h * track)
                    lv = pdk.snap_to_2xgrid(zeta + sc * n_v * track)
                    v.pad = Padding(left=lh, right=lh, bottom=lv, top=lv)
                    grow = (v.padded_size[0] * v.padded_size[1]) / v.area - 1
                    parts.append(f"v{i}: |p_h|={n_h} |p_v|={n_v} λ_h={lh} λ_v={lv} (+{grow:.0%} area)")
                st.detail("; ".join(parts))
        pt.result("zeta_um", zeta)
        pt.result("track_um", track)
    return {"zeta": zeta, "track": track, "scale": scale, "scales": scales, "layers": list(layers)}
