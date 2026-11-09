"""Compose the rendered views of a review record for the visual reviewer.
Output: composite.png = the three views (all layers / front end / back end) stacked vertically at full width with
panel titles, 1 um and 10 um scale bars and x/y coordinate ticks (um, DUT coordinates); for DUTs wider than
TILE_UM the all-layers view is additionally re-rendered as tile_<i>.png windows of <= TILE_UM width (coordinate ticks
every 5 um) so that fingers and contacts remain resolvable.  Paths and sha256 of all images are stored in the record."""
import json, sys, hashlib, math, subprocess
from pathlib import Path
from PIL import Image, ImageDraw
from textbook_sharing import paths

TILE_UM = 30.0
VERSION = 3


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _mapping(view):
    """px -> um mapping for a rendered view: x_um = cx + (px - W/2) * fit, y_um = cy - (py - H/2) * fit."""
    w, h = view.get("size_px", [1400, 1000]); x0, y0, x1, y1 = view["window_um"]
    fit = max((x1 - x0) / w, (y1 - y0) / h)
    return (x0 + x1) / 2, (y0 + y1) / 2, fit, w, h


def _ticks(d, im_w, im_h, top, cx, cy, fit, step, scale):
    """draw coordinate ticks (um) along the bottom and left edges of a panel placed at vertical offset 'top'."""
    def x_px(xu): return int(round((im_w / 2 + (xu - cx) / fit) * scale))
    def y_px(yu): return int(round(top + (im_h / 2 - (yu - cy) / fit) * scale))
    xa = cx - (im_w / 2) * fit; xb = cx + (im_w / 2) * fit; ya = cy - (im_h / 2) * fit; yb = cy + (im_h / 2) * fit
    for xu in range(int(math.floor(xa / step)) * step, int(math.ceil(xb / step)) * step + 1, step):
        px = x_px(xu)
        if 0 <= px < im_w * scale:
            d.line([px, y_px(ya) - 8, px, y_px(ya)], fill=(255, 255, 0)); d.text((px + 2, y_px(ya) - 20), f"{xu}", fill=(255, 255, 0))
    for yu in range(int(math.floor(ya / step)) * step, int(math.ceil(yb / step)) * step + 1, step):
        py = y_px(yu)
        if top <= py < top + im_h * scale:
            d.line([0, py, 8, py], fill=(255, 255, 0)); d.text((10, py - 6), f"{yu}", fill=(255, 255, 0))


def composite(record_path, out_path=None, width=1500, tile_um=TILE_UM):
    rec = json.load(open(record_path)); views = {k: str(paths.resolve(v)) for k, v in rec["view_paths"].items()}
    rj = Path(views["full"]).with_name(Path(views["full"]).name.replace("_full.png", "_render.json"))
    info = json.load(open(rj)) if rj.exists() else {}
    panels = []; vinfo = {}
    bb = info.get("bbox_um")
    for key in ("full", "fe", "be"):
        pth = views.get(key)
        if not (pth and Path(pth).exists()): continue
        im = Image.open(pth).convert("RGB"); v = dict(info.get("views", {}).get(key) or {})
        if v.get("window_um") and bb:
            # crop the rendered view to the DUT bounding box (+ margin) so that wide/flat DUTs do not waste panel height
            cx, cy, fit, w, h = _mapping(v); m = 0.05 * max(bb[2] - bb[0], bb[3] - bb[1]) + 0.4
            X0 = max(0, int((w / 2 + (bb[0] - m - cx) / fit))); X1 = min(w, int((w / 2 + (bb[2] + m - cx) / fit)) + 1)
            Y0 = max(0, int((h / 2 - (bb[3] + m - cy) / fit))); Y1 = min(h, int((h / 2 - (bb[1] - m - cy) / fit)) + 1)
            if X1 - X0 > 50 and Y1 - Y0 > 50:
                im = im.crop((X0, Y0, X1, Y1))
                ncx = cx + ((X0 + X1) / 2 - w / 2) * fit; ncy = cy - ((Y0 + Y1) / 2 - h / 2) * fit
                v["window_um"] = [ncx - (X1 - X0) / 2 * fit, ncy - (Y1 - Y0) / 2 * fit, ncx + (X1 - X0) / 2 * fit, ncy + (Y1 - Y0) / 2 * fit]
                v["size_px"] = [X1 - X0, Y1 - Y0]
        panels.append((key, im)); vinfo[key] = v
    if not panels: return None
    titles = {"full": "all layers", "fe": "front end: active / poly / contact / implant / well", "be": "back end: metals / vias / pin labels"}
    hdr = 24; ph = []
    for key, im in panels:
        ph.append(int(round(width * im.height / im.width)))
    out = Image.new("RGB", (width, sum(ph) + hdr * len(panels) + 30), (20, 20, 20)); d = ImageDraw.Draw(out)
    y = 0
    for (key, im), h in zip(panels, ph):
        d.text((6, y + 5), f"{titles[key]}   (DUT bbox {info.get('width_um')} x {info.get('height_um')} um; ticks in um)", fill=(230, 230, 230))
        y += hdr; out.paste(im.resize((width, h)), (0, y))
        v = vinfo.get(key)
        if v and "window_um" in v:
            cx, cy, fit, w, hh = _mapping(v); scale = width / w
            step = 5 if (v["window_um"][2] - v["window_um"][0]) > 20 else (2 if (v["window_um"][2] - v["window_um"][0]) > 8 else 1)
            _ticks(d, w, hh, y, cx, cy, fit, step, scale)
            if key == "full":
                px1 = int(1.0 / fit * scale); px10 = int(10.0 / fit * scale)
                d.rectangle([width - 20 - px10, y + 8, width - 20, y + 14], fill=(255, 255, 0)); d.text((width - 20 - px10, y + 16), "10 um", fill=(255, 255, 0))
                d.rectangle([width - 20 - px1, y + 30, width - 20, y + 36], fill=(0, 255, 255)); d.text((width - 20 - px1 - 40, y + 28), "1 um", fill=(0, 255, 255))
        y += h
    d.text((6, y + 8), f"review {rec['review_id']}  pdk {rec.get('pdk')}  composite v{VERSION}", fill=(200, 200, 200))
    out_path = out_path or Path(record_path).with_name("composite.png"); out.save(out_path)
    comp = {"version": VERSION, "path": paths.rel(out_path), "sha256": sha(out_path), "tiles": [], "tile_windows": []}
    # tiles for wide DUTs
    bb = info.get("bbox_um"); wum = info.get("width_um") or 0
    if bb and wum > tile_um * 1.15:
        n = int(math.ceil(wum / tile_um)); tw = wum / n; m = 0.3
        wins = [[round(bb[0] + i * tw - m, 3), round(bb[1] - m, 3), round(bb[0] + (i + 1) * tw + m, 3), round(bb[3] + m, 3)] for i in range(n)]
        prefix = Path(out_path).with_name("tile")
        r = subprocess.run([sys.executable, str(Path(__file__).with_name("render_gds.py")), str(paths.resolve(rec["gds"])), str(prefix), rec["pdk"], "--tiles=" + ";".join(",".join(str(c) for c in w_) for w_ in wins), "--width=1500"],
                           capture_output=True, text=True)
        tj = Path(str(prefix) + "_tiles.json")
        if r.returncode == 0 and tj.exists():
            tinfo = json.load(open(tj))
            for i, win in enumerate(wins):
                v = tinfo["views"].get(f"tile{i}")
                if not v: continue
                im = Image.open(v["path"]).convert("RGB"); ann = Image.new("RGB", (im.width, im.height + 26), (20, 20, 20)); ann.paste(im, (0, 26)); dd = ImageDraw.Draw(ann)
                dd.text((6, 6), f"tile {i + 1}/{n}: x {win[0]:.1f} .. {win[2]:.1f} um (all layers; ticks in um)   review {rec['review_id']}", fill=(230, 230, 230))
                cx, cy, fit, w, hh = _mapping(v); _ticks(dd, w, hh, 26, cx, cy, fit, 5, 1.0)
                px1 = int(1.0 / fit); dd.rectangle([im.width - 20 - px1, 32, im.width - 20, 38], fill=(0, 255, 255)); dd.text((im.width - 20 - px1 - 40, 30), "1 um", fill=(0, 255, 255))
                tp = Path(out_path).with_name(f"tile_{i}.png"); ann.save(tp)
                comp["tiles"].append(paths.rel(tp)); comp["tile_windows"].append(win)
        else:
            comp["tile_error"] = (r.stderr or "")[-400:]
    rec["composite"] = comp
    json.dump(rec, open(record_path, "w"), indent=1)
    return str(out_path)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(composite(p))
