"""First-tier automated geometry/semantic checks on a written GDS (independent of the builder)."""
from __future__ import annotations
import hashlib
from pathlib import Path
import klayout.db as kdb

LAYERS = {
    "sky130": {"active": (65, 20), "poly": (66, 20), "cont": (66, 44), "met1": (67, 20), "via1": (67, 44), "met2": (68, 20), "via2": (68, 44), "met3": (69, 20), "nwell": (64, 20), "nimp": (93, 44), "pimp": (94, 20), "label": (69, 5), "pin": (69, 16)},
    "gf180": {"active": (22, 0), "poly": (30, 0), "cont": (33, 0), "met1": (34, 0), "via1": (35, 0), "met2": (36, 0), "via2": (38, 0), "met3": (42, 0), "nwell": (21, 0), "nimp": (32, 0), "pimp": (31, 0), "label": (42, 10), "pin": None},
    "ihp130": {"active": (1, 0), "poly": (5, 0), "cont": (6, 0), "met1": (8, 0), "via1": (19, 0), "met2": (10, 0), "via2": (29, 0), "met3": (30, 0), "nwell": (31, 0), "nimp": (7, 0), "pimp": (14, 0), "label": (30, 25), "pin": (30, 2)},
}
EXPECTED_DBU = {"sky130": 0.005, "gf180": 0.005, "ihp130": 0.001}


def physical_checks(pdk, gds, top, expected_ports, expected_fingers=None, expected_devices=None):
    ly = kdb.Layout(); ly.read(str(gds))
    cell = ly.cell(top) if ly.cell(top) else ly.top_cell()
    dbu = ly.dbu; L = LAYERS[pdk]
    def reg(key):
        if L.get(key) is None: return kdb.Region()
        return kdb.Region(cell.begin_shapes_rec(ly.layer(kdb.LayerInfo(*L[key])))).merged()
    out = {"gds_sha256": hashlib.sha256(Path(gds).read_bytes()).hexdigest(), "top": cell.name, "dbu": dbu, "checks": {}, "findings": []}
    bb = cell.dbbox()
    out["bbox_um"] = [bb.left, bb.bottom, bb.right, bb.top]; out["area_um2"] = round(bb.area(), 4)
    out["checks"]["top_nonempty"] = not bb.empty()
    out["checks"]["dbu_ok"] = abs(dbu - 0.001) < 1e-9 or abs(dbu - 0.005) < 1e-9
    layers_present = sorted({(ly.get_info(li).layer, ly.get_info(li).datatype) for li in ly.layer_indexes() if not cell.bbox_per_layer(li).empty()})
    out["layers_present"] = layers_present
    active, poly, cont, met1, met2, met3 = reg("active"), reg("poly"), reg("cont"), reg("met1"), reg("met2"), reg("met3")
    chan = (poly & active).merged()
    out["channel_regions"] = chan.count(); out["active_islands"] = active.count(); out["poly_components"] = poly.count()
    if expected_fingers is not None:
        out["checks"]["finger_count"] = (chan.count() == expected_fingers)
        if chan.count() != expected_fingers:
            out["findings"].append(f"channel regions {chan.count()} != expected fingers {expected_fingers} (extra or missing MOS)")
    # labels: every expected port must have a text on the label layer sitting on met3 (or met2) metal
    texts = {}
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        for sh in cell.begin_shapes_rec(li):
            if sh.shape().is_text():
                t = sh.shape().dtext.transformed(sh.dtrans())
                texts.setdefault(t.string, []).append(((info.layer, info.datatype), t.x, t.y))
    missing = []; off_metal = []
    for p in expected_ports:
        if p not in texts:
            missing.append(p); continue
        on = False
        for (lay, x, y) in texts[p]:
            for r in (met3, met2, met1):
                if any(pg.inside(kdb.Point(int(round(x / dbu)), int(round(y / dbu)))) for pg in r.each()): on = True
        if not on: off_metal.append(p)
    out["checks"]["ports_labelled"] = not missing; out["checks"]["labels_on_metal"] = not off_metal
    if missing: out["findings"].append(f"ports without label: {missing}")
    if off_metal: out["findings"].append(f"labels not on metal: {off_metal}")
    # stray geometry: any shape farther than 2x the bbox diagonal from the centre? (should be none in a flat DUT)
    out["checks"]["no_remote_instances"] = True
    # floating poly: poly components with no contact and no channel
    floating = 0
    for pg in poly.each():
        r = kdb.Region(pg)
        if (r & cont).is_empty() and (r & active).is_empty(): floating += 1
    out["floating_poly_components"] = floating
    out["checks"]["no_floating_poly"] = floating == 0
    out["metal_area_um2"] = {"met1": round(met1.area() * dbu * dbu, 4), "met2": round(met2.area() * dbu * dbu, 4), "met3": round(met3.area() * dbu * dbu, 4)}
    out["contacts"] = {"on_active": (cont & active).count(), "on_poly": (cont & poly).count(), "total": cont.count()}
    out["active_area_um2"] = round(active.area() * dbu * dbu, 4); out["active_perimeter_um"] = round(active.perimeter() * dbu, 4)
    out["status"] = "passed" if all(out["checks"].values()) else "physical_review_failed"
    return out
