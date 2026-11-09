"""Render a GDS to PNG views with the PDK layer properties (headless, klayout.lay).
usage: python render_gds.py <gds> <out_prefix> <pdk> [--zoom x0,y0,x1,y1] [--cell NAME] [--tiles x0,y0,x1,y1;...]
Produces <out_prefix>_full.png, _fe.png (active/poly/contact/implant/well), _be.png (metals/vias/pins), [_zoom.png]
Also writes <out_prefix>_render.json with image sha256, layer legend and scale bar info."""
import os, json, hashlib, argparse
import klayout.lay as lay
import klayout.db as db

LYP = {"sky130": "/foss/pdks/sky130A/libs.tech/klayout/tech/sky130A.lyp",
       "gf180": "/foss/pdks/gf180mcuD/libs.tech/klayout/tech/gf180mcu.lyp",
       "ihp130": "/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/sg13g2.lyp"}
FE = {"sky130": [(65, 20), (66, 20), (66, 44), (93, 44), (94, 20), (64, 20), (64, 44), (64, 18)],
      "gf180": [(22, 0), (30, 0), (33, 0), (32, 0), (31, 0), (21, 0), (204, 0), (12, 0)],
      "ihp130": [(1, 0), (5, 0), (6, 0), (14, 0), (7, 0), (31, 0), (46, 0)]}
BE = {"sky130": [(67, 20), (67, 44), (68, 20), (68, 44), (69, 20), (69, 44), (70, 20), (70, 44), (67, 16), (68, 16), (69, 16), (70, 16), (67, 5), (68, 5), (69, 5), (70, 5)],
      "gf180": [(34, 0), (35, 0), (36, 0), (38, 0), (42, 0), (40, 0), (46, 0), (34, 10), (36, 10), (42, 10), (46, 10)],
      "ihp130": [(8, 0), (19, 0), (10, 0), (29, 0), (30, 0), (49, 0), (50, 0), (8, 2), (10, 2), (30, 2), (50, 2), (8, 25), (10, 25), (30, 25), (50, 25)]}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def render(gds, prefix, pdk, zoom=None, cell=None, width=1400, height=1000, tiles=None):
    os.makedirs(os.path.dirname(os.path.abspath(str(prefix))) or '.', exist_ok=True)
    ly = db.Layout(); ly.read(gds)
    top = ly.cell(cell) if cell else ly.top_cell()
    lv = lay.LayoutView()
    lv.load_layout(gds, True)
    if os.path.exists(LYP.get(pdk, "")):
        lv.load_layer_props(LYP[pdk])
    lv.max_hier()
    lv.set_config("background-color", "#000000")
    lv.set_config("grid-visible", "false")
    bb = top.dbbox()
    out = {"gds": gds, "gds_sha256": sha(gds), "cell": top.name, "bbox_um": [bb.left, bb.bottom, bb.right, bb.top],
           "width_um": round(bb.width(), 4), "height_um": round(bb.height(), 4), "pdk": pdk, "lyp": LYP.get(pdk), "views": {}}
    margin = max(bb.width(), bb.height()) * 0.08 + 0.3
    full = db.DBox(bb.left - margin, bb.bottom - margin, bb.right + margin, bb.top + margin)

    def shoot(name, box, layers=None, size=None):
        w_px, h_px = size or (width, height)
        if layers is not None:
            it = lv.begin_layers()
            while not it.at_end():
                lp = it.current()
                info = (lp.source_layer, lp.source_datatype)
                vis = info in layers
                nlp = lp.dup(); nlp.visible = vis
                lv.set_layer_properties(it, nlp)
                it.next()
        else:
            it = lv.begin_layers()
            while not it.at_end():
                nlp = it.current().dup(); nlp.visible = True
                lv.set_layer_properties(it, nlp); it.next()
        lv.zoom_box(box)
        path = f"{prefix}_{name}.png"
        lv.save_image(path, w_px, h_px)
        fit = max(box.width() / w_px, box.height() / h_px)      # KLayout fits the box into the viewport keeping the aspect ratio
        out["views"][name] = {"path": path, "sha256": sha(path), "window_um": [box.left, box.bottom, box.right, box.top],
                              "um_per_px": round(fit, 5), "size_px": [w_px, h_px], "center_um": [box.center().x, box.center().y]}
    if tiles:
        # tiles mode: only the requested windows, all layers, image height follows the window aspect (width fits exactly)
        for i, (x0, y0, x1, y1) in enumerate(tiles):
            box = db.DBox(x0, y0, x1, y1)
            h_px = max(200, min(1400, int(round(width * box.height() / box.width()))))
            shoot(f"tile{i}", box, None, (width, h_px))
        json.dump(out, open(f"{prefix}_tiles.json", "w"), indent=1)
        return out
    shoot("full", full)
    shoot("fe", full, set(FE.get(pdk, [])))
    shoot("be", full, set(BE.get(pdk, [])))
    if zoom:
        x0, y0, x1, y1 = zoom
        shoot("zoom", db.DBox(x0, y0, x1, y1))
    # legend: visible layers with names from the lyp
    legend = []
    it = lv.begin_layers()
    while not it.at_end():
        lp = it.current()
        if lp.source_layer >= 0:
            legend.append({"layer": [lp.source_layer, lp.source_datatype], "name": lp.name, "fill": lp.fill_color, "frame": lp.frame_color})
        it.next()
    out["legend"] = legend
    json.dump(out, open(f"{prefix}_render.json", "w"), indent=1)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("gds"); ap.add_argument("prefix"); ap.add_argument("pdk")
    ap.add_argument("--zoom"); ap.add_argument("--cell"); ap.add_argument("--width", type=int, default=1400); ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--tiles", help="semicolon-separated windows x0,y0,x1,y1 (um); renders only these, all layers")
    a = ap.parse_args()
    z = [float(v) for v in a.zoom.split(",")] if a.zoom else None
    t = [[float(v) for v in win.split(",")] for win in a.tiles.split(";")] if a.tiles else None
    r = render(a.gds, a.prefix, a.pdk, z, a.cell, a.width, a.height, t)
    print(json.dumps({k: v for k, v in r.items() if k != "legend"}, indent=1))
