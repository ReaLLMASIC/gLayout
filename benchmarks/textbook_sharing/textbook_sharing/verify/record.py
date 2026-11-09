"""Per-GDS physical review records (first tier automated + second tier visual).

A review record is created for every generated, parsable GDS.  The cache key includes the GDS
sha256, the target/constraint hash, the PDK, the layer map version and the reviewer version.
Visual review requires an actual viewer (human or a vision model with a fixed protocol); until a
viewer has recorded observations the record stays 'review_pending' and the case cannot be 'passed'.
"""
from __future__ import annotations
import json, hashlib, time, subprocess, sys
from pathlib import Path
from textbook_sharing import paths

REVIEWER_VERSION = "review-v1"
LAYERMAP_VERSION = {"sky130": "sky130A.lyp@volare-0fe599b2", "gf180": "gf180mcu.lyp@ciel-f2e289da", "ihp130": "sg13g2.lyp@iic-2025-06"}


def review_key(gds_sha, target_sha, pdk):
    return hashlib.sha256(f"{gds_sha}|{target_sha}|{pdk}|{LAYERMAP_VERSION[pdk]}|{REVIEWER_VERSION}".encode()).hexdigest()[:20]


def render_views(gds, prefix, pdk, zoom=None, cell=None):
    tool = Path(__file__).resolve().parents[1] / "review" / "render_gds.py"
    cmd = [sys.executable, str(tool), str(gds), str(prefix), pdk]
    if zoom: cmd += ["--zoom", ",".join(f"{v:.3f}" for v in zoom)]
    if cell: cmd += ["--cell", cell]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    rj = Path(f"{prefix}_render.json")
    return json.load(open(rj)) if rj.exists() else {"error": r.stderr[-500:]}


def make_record(gds, pdk, target_sha, physical, raw_checks, render_info, zoom_group=None, context=None):
    gds_sha = physical["gds_sha256"]
    rec = {"review_id": review_key(gds_sha, target_sha, pdk), "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "gds": paths.rel(gds), "gds_sha256": gds_sha, "target_sha256": target_sha, "pdk": pdk, "layermap_version": LAYERMAP_VERSION[pdk], "reviewer_version": REVIEWER_VERSION,
           "view_paths": {k: paths.rel(v["path"]) for k, v in render_info.get("views", {}).items()}, "image_sha256": {k: v["sha256"] for k, v in render_info.get("views", {}).items()},
           "static_checks": {"physical": physical, "raw": raw_checks}, "visual": {"reviewer_type": None, "reviewer_id": None, "observed_findings": [], "issue_locations": [], "verdict": "review_pending"},
           "linked_raw_checks": {k: (v.get("status") if isinstance(v, dict) else v) for k, v in raw_checks.items()}, "context": context or {}, "verdict": "review_pending"}
    return rec
