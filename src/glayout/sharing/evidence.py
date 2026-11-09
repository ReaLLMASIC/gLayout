"""Physical sharing evidence derived from geometry (never from plan labels).

Two entry points:
  evidence_from_rects  - used by build_mos_group on the rectangles it just drew
  evidence_from_gds    - used by the evaluator on a written GDS file (independent re-derivation)
Both reduce to evidence_from_regions, which works on merged klayout Regions.
"""
from __future__ import annotations
import klayout.db as kdb

DBU = 0.001


def _region(rects, layer, dbu=DBU):
    r = kdb.Region()
    for (x0, y0, x1, y1) in rects.get(tuple(layer), []):
        r.insert(kdb.Box(int(round(x0 / dbu)), int(round(y0 / dbu)), int(round(x1 / dbu)), int(round(y1 / dbu))))
    r.merge()
    return r


def evidence_from_regions(active: kdb.Region, poly: kdb.Region, cont: kdb.Region, met1: kdb.Region,
                          node_records, gate_records, W, n_devices, dbu=DBU) -> dict:
    """node_records: [{node, x, net, terminals:[dev:T], ...}], gate_records: [{device, x, net, group}]"""
    def pt(x, y):
        return kdb.Point(int(round(x / dbu)), int(round(y / dbu)))
    islands = [p for p in active.merged().each()]
    def island_of(x, y):
        p = pt(x, y)
        for i, isl in enumerate(islands):
            if isl.inside(p): return i
        return None
    # diffusion nodes -> islands; a node shared across devices is a cross-device diffusion share
    node_island = {}; cross_nodes = []; dev_islands = {}
    for nd in node_records:
        isl = island_of(nd["x"], W / 2)
        node_island[nd["node"]] = isl
        devs = sorted({t.split(":")[0] for t in nd["terminals"]})
        for d in devs: dev_islands.setdefault(d, set()).add(isl)
        if len(devs) > 1:
            cross_nodes.append({"node": nd["node"], "island": isl, "net": nd["net"], "terminals": nd["terminals"]})
    # gate conductors: connected poly components containing gates of >1 device
    polys = [p for p in poly.merged().each()]
    comp_devs = {}
    for g in gate_records:
        p = pt(g["x"], W / 2)
        for i, pp in enumerate(polys):
            if pp.inside(p):
                comp_devs.setdefault(i, set()).add(g["device"]); break
    shared_gate = [{"poly_component": i, "devices": sorted(d)} for i, d in comp_devs.items() if len(d) > 1]
    # transistor count = connected regions of poly AND active
    chan = (poly & active).merged()
    n_channels = chan.count()
    # contacts on active vs on poly
    cont_act = (cont & active).count(); cont_poly = (cont & poly).count()
    # island sharing: islands hosting >1 device
    isl_devs = {}
    for d, s in dev_islands.items():
        for i in s: isl_devs.setdefault(i, set()).add(d)
    shared_islands = [{"island": i, "devices": sorted(ds)} for i, ds in isl_devs.items() if len(ds) > 1]
    return {
        "active_islands": len(islands),
        "shared_diffusion_islands": shared_islands,
        "cross_device_shared_nodes": cross_nodes,
        "n_cross_device_shared_nodes": len(cross_nodes),
        "shared_gate_conductors": shared_gate,
        "n_cross_device_gate_conductors": len(shared_gate),
        "poly_components": len(polys),
        "channel_regions": n_channels,
        "expected_fingers": len(gate_records),
        "extra_mos_check": "ok" if n_channels == len(gate_records) else f"mismatch: {n_channels} channel regions vs {len(gate_records)} fingers",
        "contacts_on_active": cont_act, "contacts_on_poly": cont_poly,
        "active_area_um2": round(active.area() * dbu * dbu, 6),
        "active_perimeter_um": round(active.merged().perimeter() * dbu, 4),
        "poly_area_um2": round(poly.area() * dbu * dbu, 6),
        "met1_area_um2": round(met1.area() * dbu * dbu, 6),
    }


def evidence_from_rects(rules, rects, node_records, gate_records, W, n_devices, plan) -> dict:
    lay = rules.layers
    ev = evidence_from_regions(_region(rects, lay["active"]), _region(rects, lay["poly"]), _region(rects, lay["cont"]), _region(rects, lay["met1"]),
                               node_records, gate_records, W, n_devices)
    ev["source"] = "builder_rectangles"
    ev["plan_summary"] = plan.summary()
    ev["consistency"] = {
        "cross_device_joins_requested": plan.summary()["cross_device_diffusion_joins"],
        "cross_device_nodes_found": ev["n_cross_device_shared_nodes"],
        "cross_device_gate_groups_requested": plan.summary()["cross_device_gate_groups"],
        "cross_device_gate_conductors_found": ev["n_cross_device_gate_conductors"],
    }
    return ev


def evidence_from_gds(gds_path: str, rules, node_records, gate_records, W, n_devices, cell=None, origin=(0.0, 0.0)) -> dict:
    """Re-derive the evidence from a GDS file. node/gate records are in the group's local frame; origin shifts them."""
    ly = kdb.Layout(); ly.read(str(gds_path))
    top = ly.cell(cell) if cell else ly.top_cell()
    dbu = ly.dbu
    def reg(layer):
        li = ly.layer(kdb.LayerInfo(int(layer[0]), int(layer[1])))
        return kdb.Region(top.begin_shapes_rec(li)).merged()
    lay = rules.layers
    ox = origin[0]
    nr = [dict(n, x=n["x"] + ox) for n in node_records]
    gr = [dict(g, x=g["x"] + ox) for g in gate_records]
    ev = evidence_from_regions(reg(lay["active"]), reg(lay["poly"]), reg(lay["cont"]), reg(lay["met1"]), nr, gr, W, n_devices, dbu=dbu)
    ev["source"] = "gds_file"
    return ev
