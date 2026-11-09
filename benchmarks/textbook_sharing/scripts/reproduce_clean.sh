#!/bin/bash
# Clean-process reproduction: export the committed tree (git archive HEAD) into a fresh folder, rebuild and verify a
# few cases there from scratch (geometry, DRC, LVS, extraction, post-layout simulation), then compare geometry hash,
# area, status, every verification stage and the post-layout measures with the recorded runs (default:
# <benchmark>/runs).  Nothing from the recorded runs is copied into the fresh tree.
# usage: scripts/reproduce_clean.sh [CASE/PDK/SIZE/MODE ...]
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd); REPO=$(cd "$HERE/../.." && pwd)
REF=${TSB_RUNS:-$HERE/runs}; OUT=${TSB_RESULTS:-$HERE/results}/analysis
STAMP=$(date -u +%Y%m%dT%H%M%SZ); C=${TSB_REPRO_DIR:-/tmp/tsb_repro_$STAMP}
CASES=${*:-"C08/sky130/sW1_sL1/combined C08/gf180/sW1_sL1/combined C08/ihp130/sW1_sL1/combined C11/ihp130/sW1_sL1/gate_only C02/gf180/sW1_sL1/combined"}
mkdir -p "$C/tree"; git -C "$REPO" archive HEAD | tar -x -C "$C/tree"
tar -xJf "$C/tree/benchmarks/textbook_sharing/data/cases.tar.xz" -C "$C/tree/benchmarks/textbook_sharing"
git -C "$REPO" rev-parse HEAD > "$C/SOURCE_COMMIT.txt"
TSB_RUNS="$C/runs" TSB_RESULTS="$C/results" TSB_ENV=${TSB_ENV:-$HERE/.env} \
  "$C/tree/benchmarks/textbook_sharing/scripts/run_in_container.sh" "python - <<'PY'
from textbook_sharing.run_case import run
from textbook_sharing import paths
for spec in '$CASES'.split():
    cid, pdk, size, mode = spec.split('/')
    r = run(paths.CASES / cid / pdk / size, paths.GRID_RUNS / cid / pdk / size / mode, mode=mode, label='repro')
    print(spec, r.get('primary_status'), r.get('area_um2'), flush=True)
PY"
mkdir -p "$OUT"
python3 - "$C" "$REF" "$OUT/repro_clean_$STAMP.json" $CASES <<'PY'
import json, sys
from pathlib import Path
fresh, ref, out, specs = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4:]
runs = []
for spec in specs:
    a = json.load(open(fresh / "runs/grid" / spec / "result.json")); b = json.load(open(ref / "grid" / spec / "result.json"))
    match = {k: a.get(k) == b.get(k) for k in ("geometry_hash", "area_um2", "primary_status", "verify")}
    ma, mb = (a.get("postsim") or {}).get("measures") or {}, (b.get("postsim") or {}).get("measures") or {}
    diffs = [abs(ma[k] - mb[k]) / max(abs(mb[k]), 1e-30) for k in mb if isinstance(mb[k], (int, float)) and isinstance(ma.get(k), (int, float))]
    runs.append({"run": spec, "match": match, "max_rel_measure_diff": max(diffs) if diffs else None})
    print(spec, match, "largest relative difference of a post-layout measure:", runs[-1]["max_rel_measure_diff"])
json.dump({"commit": (fresh / "SOURCE_COMMIT.txt").read_text().strip(), "runs": runs}, open(out, "w"), indent=1)
PY
echo "fresh tree in $C; summary in $OUT/repro_clean_$STAMP.json"
