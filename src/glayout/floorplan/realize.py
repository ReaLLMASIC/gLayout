"""Turn a FloorplanResult into geometry: one reference per instance, moved
to its placed position (padding excluded) and snapped to the 2x grid.

No inter-block wires are drawn yet; the padding is the space reserved for the
router. Ports of each block are re-exported as ``<instance>_<port>``.
"""
from __future__ import annotations

from glayout.backend import Component
from glayout.floorplan.anneal import FloorplanResult
from glayout.pdk.mappedpdk import MappedPDK
from glayout.util.process_table import ProcessTable


def cell_origin(pdk: MappedPDK, placed, variant) -> tuple[float, float]:
    """Lower-left corner of a placed cell (padding excluded), on the 2x grid."""
    return (pdk.snap_to_2xgrid(placed.x + variant.pad.left), pdk.snap_to_2xgrid(placed.y + variant.pad.bottom))


def realize_floorplan(pdk: MappedPDK, result: FloorplanResult, name: str = "floorplan",
                      flatten: bool = True) -> Component:
    top = Component(f"{name}_hier")
    with ProcessTable(f"Realise floorplan {result.circuit.name}") as pt:
        for inst_name, p in result.placed.items():
            with pt.stage(inst_name) as st:
                inst = result.circuit[inst_name]
                v = inst.block.variants[p.variant]
                if v.component is None:
                    raise ValueError(f"{inst_name}: variant {p.variant} has no built component")
                ref = top << v.component
                if p.mirrored:
                    ref.mirror((0, 0), (0, 1))
                tx, ty = cell_origin(pdk, p, v)
                # cells are on the 1x grid and origins on the 2x grid, so the move
                # is on grid; not snapping it keeps the origin exact for the router
                ref.movex(tx - ref.xmin).movey(ty - ref.ymin)
                top.add_ports(ref.get_ports_list(), prefix=f"{inst_name}_")
                st.detail(f"variant {p.variant} at ({ref.xmin:.3f}, {ref.ymin:.3f}){' mirrored' if p.mirrored else ''}")
        with pt.stage("Check spacing") as st:
            boxes = [(n, top.references[i].bbox) for i, n in enumerate(result.placed)]
            gaps = []
            for i, (na, a) in enumerate(boxes):
                for nb, b in boxes[i + 1:]:
                    dx = max(b[0][0] - a[1][0], a[0][0] - b[1][0])
                    dy = max(b[0][1] - a[1][1], a[0][1] - b[1][1])
                    gaps.append((max(dx, dy), na, nb))
            g, na, nb = min(gaps) if gaps else (float("inf"), "", "")
            st.detail(f"min block gap {g:.3f}µm ({na}/{nb})")
            if g < 0:
                st.fail("blocks overlap")
        if not flatten:
            return top
        flat = top.flatten()
        flat.name = name
        pt.result("size_um", f"{flat.xsize:.2f}x{flat.ysize:.2f}")
    flat.info["placement"] = {n: {"x": p.x, "y": p.y, "variant": p.variant, "mirrored": p.mirrored}
                              for n, p in result.placed.items()}
    flat.info["metrics"] = {k: v for k, v in result.metrics.items() if isinstance(v, (int, float, str))}
    return flat
