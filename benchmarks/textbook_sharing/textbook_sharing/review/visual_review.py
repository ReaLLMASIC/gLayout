"""Visual review driver: one blinded review per UNIQUE layout, the verdict reused for every record of that layout.

  prepare <batch> --limit N [--roots grid,selection,models] [--width 1100] [--include <file of run directories>]
      groups every review_record.json under the roots by (geometry_hash of the run, pdk); a group is pending when none of its records
      has a verdict; for N pending groups (deterministic order by a hash of the key, so batches mix circuits, sizes and
      methods) builds the composite of one representative record and copies composite + tiles into
      <runs>/review/<batch>/transfer/ named <review_id>.png / <review_id>_t<i>.png (no path, mode or method in
      any name); items.jsonl lists only review ids and file names.  manifest.json (not shown to the reviewer) maps ids to
      records.  The reviewer follows reviewer_guide.md and returns outputs.json.
  apply <batch> <outputs.json>
      writes each verdict into the representative record and copies it into every record of the same (geometry_hash, pdk)
      with reused_from = representative review id; checks >= 3 observations and a known verdict, else rejects the item.
  resolve <review_id> <resolved_ok|confirmed_issue> <note> <evidence> [--by NAME]
      records how a 'suspicious' / 'fail' verdict was settled by objective checks (the verdict itself is kept).
  status
      counts records / unique layouts by verdict (reviewed directly, reused, pending)."""
from __future__ import annotations
import json, glob, shutil, hashlib, argparse, time, collections
from pathlib import Path
from textbook_sharing import paths
OUT = paths.REVIEW_BATCHES
ROOTS = ["grid", "selection", "models"]          # relative to the run folder
VERDICTS = ("pass", "suspicious", "fail")
TILE_W = 1200
MAX_TILES = 99


def _small(src, dst, max_w=None, colors=128):
    """Transfer copy for the reviewer: 128-colour palette PNG (layer colours stay distinct), optional downscale."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    if max_w and im.width > max_w: im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT).save(dst, format="PNG", optimize=True)
    return hashlib.sha256(open(dst, "rb").read()).hexdigest()


def groups(roots):
    g = collections.defaultdict(list)
    for root in roots:
        for rp in sorted(glob.glob(str(paths.RUNS / root / "**" / "review_record.json"), recursive=True)):
            try: rec = json.load(open(rp))
            except Exception: continue
            # key: cell-name-independent geometry hash of the run (identical geometry under another cell name, e.g. a
            # selection named mode equal to a main-grid mode, is the same layout); GDS sha256 when no hash is recorded
            res_p = Path(rp).parent.parent.parent / "result.json"
            gh = None
            if res_p.exists():
                try: gh = json.load(open(res_p)).get("geometry_hash")
                except Exception: gh = None
            g[(gh or rec["gds_sha256"], rec["pdk"])].append((rp, rec))
    return g


def propagate():
    """Copy an existing direct verdict to the other records of the same layout key (after a key change)."""
    g = groups(ROOTS); n = 0
    for key, recs in g.items():
        direct = [r for _, r in recs if r["visual"]["verdict"] != "review_pending" and not r["visual"].get("reused_from")]
        if not direct: continue
        src = direct[0]
        for rp, r in recs:
            if r["visual"]["verdict"] == "review_pending":
                v = dict(src["visual"]); v["reused_from"] = src["review_id"]; v["reuse_key"] = "geometry_hash+pdk"
                r["visual"] = v; r["verdict"] = v["verdict"]; json.dump(r, open(rp, "w"), indent=1); n += 1
    print("propagated to", n, "records")


def taken_ids():
    t = set()
    for m in OUT.glob("*/manifest.json"):
        d = json.load(open(m))
        if not d.get("applied"): t |= {k for k in d["items"]}
    return t


def prepare(batch, limit, roots, width, include=None):
    from textbook_sharing.review.composite import composite
    bd = OUT / batch; tr = bd / "transfer"
    if bd.exists(): raise SystemExit(f"{bd} exists")
    tr.mkdir(parents=True)
    g = groups(roots); taken = taken_ids(); items = {}
    pend = [k for k, recs in g.items() if all(r["visual"]["verdict"] == "review_pending" for _, r in recs)]
    if include is not None:   # only layouts whose run directory is listed (for example every layout that is reported)
        inc = {str(paths.resolve(x).resolve()) for x in include}
        pend = [k for k in pend if any(str(Path(rp).parent.parent.parent.resolve()) in inc for rp, _ in g[k])]
    pend.sort(key=lambda k: hashlib.sha256((k[0] + k[1]).encode()).hexdigest())
    for key in pend:
        if len(items) >= limit: break
        rp, rec = sorted(g[key])[0]
        if rec["review_id"] in taken: continue
        cp = composite(rp, width=width)
        if not cp: continue
        rec = json.load(open(rp)); comp = rec["composite"]
        tsha = {}
        tsha[f"{rec['review_id']}.png"] = _small(cp, tr / f"{rec['review_id']}.png")
        tiles = []
        for i, t in enumerate(comp.get("tiles", [])[:MAX_TILES]):
            tsha[f"{rec['review_id']}_t{i}.png"] = _small(t, tr / f"{rec['review_id']}_t{i}.png", max_w=TILE_W); tiles.append(f"{rec['review_id']}_t{i}.png")
        items[rec["review_id"]] = {"record": paths.rel(rp), "layout_key": key[0], "pdk": key[1], "n_records_same_layout": len(g[key]),
                                   "composite": f"{rec['review_id']}.png", "tiles": tiles, "composite_sha256": comp["sha256"], "transfer_sha256": tsha,
                                   "n_tiles_total": len(comp.get("tiles", [])), "n_tiles_sent": len(tiles)}
    with open(tr / "items.jsonl", "w") as f:
        for rid, it in items.items(): f.write(json.dumps({"review_id": rid, "composite": it["composite"], "tiles": it["tiles"]}) + "\n")
    json.dump({"batch": batch, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "width": width, "items": items, "applied": False},
              open(bd / "manifest.json", "w"), indent=1)
    print(batch, len(items), "items", sum(len(v["tiles"]) for v in items.values()), "tiles", "pending groups", len(pend))


def apply(batch, outputs):
    bd = OUT / batch; man = json.load(open(bd / "manifest.json")); outs = json.load(open(outputs))
    g = groups(ROOTS); ok = 0; rejected = []; reused = 0
    rec_key = {str(Path(rp).resolve()): k for k, recs in g.items() for rp, _ in recs}
    for o in outs:
        it = man["items"].get(o.get("review_id"))
        if not it: rejected.append({"review_id": o.get("review_id"), "why": "unknown id"}); continue
        if o.get("verdict") not in VERDICTS or len(o.get("observed_findings") or []) < 3:
            rejected.append({"review_id": o["review_id"], "why": "verdict unknown or fewer than 3 observations"}); continue
        vis = {"reviewer_type": o.get("reviewer_type", "vision_model"), "reviewer_id": o["reviewer_id"], "observed_findings": o["observed_findings"],
               "issue_locations": o.get("issue_locations", []), "verdict": o["verdict"], "reviewed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "image_sha256": it["composite_sha256"], "batch": batch, "protocol": "blinded, one review per unique layout",
               "coverage": ("full" if it.get("n_tiles_sent", 0) >= it.get("n_tiles_total", 0) else f"partial: composite + {it.get('n_tiles_sent')} of {it.get('n_tiles_total')} zoom tiles")}
        rep_path = str(paths.resolve(it["record"]).resolve()); key = rec_key.get(rep_path)
        if key is None: rejected.append({"review_id": o["review_id"], "why": "representative record not found"}); continue
        for rp, rec in g[key]:
            v = dict(vis)
            if str(Path(rp).resolve()) != rep_path: v["reused_from"] = o["review_id"]; v["reuse_key"] = "geometry_hash+pdk"; reused += 1
            rec["visual"] = v; rec["verdict"] = o["verdict"]; json.dump(rec, open(rp, "w"), indent=1)
        ok += 1
    man["applied"] = True; man["applied_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); man["rejected"] = rejected
    missing = sorted(set(man["items"]) - {o.get("review_id") for o in outs})
    man["missing"] = missing
    json.dump(man, open(bd / "manifest.json", "w"), indent=1)
    shutil.copy(outputs, bd / "outputs.json")
    print("applied", ok, "reused into", reused, "records; rejected", len(rejected), "missing", len(missing))


def resolve(rid, outcome, note, evidence, by="maintainer"):
    """Record how a 'suspicious' / 'fail' visual verdict was resolved (outcome: resolved_ok | confirmed_issue), on the
    reviewed record and every record that reuses it.  The reviewer's verdict itself is never overwritten."""
    assert outcome in ("resolved_ok", "confirmed_issue")
    n = 0
    for k, recs in groups(ROOTS).items():
        for rp, rec in recs:
            if rec["review_id"] == rid or rec["visual"].get("reused_from") == rid:
                rec["visual_resolution"] = {"outcome": outcome, "note": note, "evidence": evidence, "by": by,
                                            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                json.dump(rec, open(rp, "w"), indent=1); n += 1
    print(rid, outcome, "records", n)


def status():
    g = groups(ROOTS); c = collections.Counter(); cr = collections.Counter()
    for k, recs in g.items():
        vs = {r["visual"]["verdict"] for _, r in recs}; c[sorted(vs)[0] if len(vs) == 1 else "mixed"] += 1
        for _, r in recs: cr[(r["visual"]["verdict"], "reused" if r["visual"].get("reused_from") else "direct")] += 1
    print(json.dumps({"unique_layouts": dict(c), "records": {f"{a}/{b}": n for (a, b), n in cr.items()}}, indent=1))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("args", nargs="*"); ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--roots", default=",".join(ROOTS)); ap.add_argument("--width", type=int, default=1000); ap.add_argument("--tile-width", type=int, default=1200); ap.add_argument("--max-tiles", type=int, default=99); ap.add_argument("--include", default=None); ap.add_argument("--by", default="maintainer"); a = ap.parse_args()
    global MAX_TILES; MAX_TILES = a.max_tiles
    global TILE_W; TILE_W = a.tile_width
    if a.cmd == "prepare": prepare(a.args[0], a.limit, a.roots.split(","), a.width,
                                   include=[l.strip() for l in open(a.include) if l.strip()] if a.include else None)
    elif a.cmd == "apply": apply(a.args[0], a.args[1])
    elif a.cmd == "status": status()
    elif a.cmd == "propagate": propagate()
    elif a.cmd == "resolve": resolve(*a.args[:4], by=a.by)


if __name__ == "__main__":
    main()
