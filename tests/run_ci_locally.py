#!/usr/bin/env python3
"""Reproduce the CI workflows (Cell DRC + Cell LVS) locally inside the same
iic-osic-tools docker image GitHub Actions uses.

Usage:
    tests/run_ci_locally.py                       # DRC then LVS for sky130+gf180
    tests/run_ci_locally.py --skip-lvs            # just DRC
    tests/run_ci_locally.py --pdks sky130         # only sky130 (DRC + LVS)
    tests/run_ci_locally.py --cells current_mirror_nfet,diff_pair  # subset

The first run takes ~5 min (apt + pip install gdsfactory). Subsequent runs
reuse the venv cached at ``.drc-cache/venv/`` and finish in ~1 min.

Outputs (mirrors the CI artifact layout):
    .drc-cache/reports/<pdk>/   — DRC results (gds, netlists, lyrdb, junit)
    .drc-cache/lvs/<pdk>/       — LVS results (reports, junit)
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE = REPO_ROOT / ".drc-cache"
DRC_DIR = CACHE / "reports"
LVS_DIR = CACHE / "lvs"

# Default sets — match the CI workflow matrices.
DEFAULT_DRC_PDKS = ("sky130", "gf180")
DEFAULT_LVS_PDKS = ("sky130", "gf180")  # both PDKs supported; mirrors lvs.yml

IMAGE = "hpretl/iic-osic-tools:latest"


# Bash that boots Python 3.10 + the cached venv inside the container. Mirrors
# what .github/workflows/{drc,lvs}.yml do: install Python 3.10 via uv (from
# python-build-standalone, hosted on GitHub releases) instead of via the
# deadsnakes PPA, which has been flaky.
BOOTSTRAP = r"""
set -uo pipefail
unset PYTHONPATH
export DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

if [ ! -x "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
fi
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.10 >/dev/null 2>&1
PYTHON310="$(uv python find 3.10)"

if [ ! -f /work/.drc-cache/venv/.installed ]; then
    rm -rf /work/.drc-cache/venv
    "$PYTHON310" -m venv /work/.drc-cache/venv
    . /work/.drc-cache/venv/bin/activate
    uv pip install -e .
    touch /work/.drc-cache/venv/.installed
else
    # Cache hit: glayout's .pth points to /work which is the same on every
    # run, so no refresh is needed (matches the workflows).
    . /work/.drc-cache/venv/bin/activate
fi
"""


def _run_parallel(label: str, jobs: list[tuple[str, list[str]]]) -> int:
    """Launch jobs concurrently, stream each into a per-job log file, return
    the worst exit code. ``jobs`` is a list of (name, command) tuples."""
    if not jobs:
        return 0
    CACHE.mkdir(exist_ok=True)
    log_dir = CACHE / "logs"
    log_dir.mkdir(exist_ok=True)
    procs: list[tuple[str, subprocess.Popen, Path]] = []
    for name, cmd in jobs:
        log_path = log_dir / f"{label}_{name}.log"
        log = log_path.open("w")
        log.write(f"$ {' '.join(shlex.quote(c) for c in cmd)}\n")
        log.flush()
        print(f"  → {label} {name}: streaming to {log_path}")
        procs.append((name, subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT), log_path))
    overall = 0
    for name, proc, log_path in procs:
        rc = proc.wait()
        proc.stdout = None  # close fd via gc
        print(f"  ← {label} {name}: exit {rc}  (log: {log_path})")
        overall = overall or rc
    return overall


def _drc_command(pdk: str, cells: str | None, image: str) -> list[str]:
    cells_arg = f" --cells {shlex.quote(cells)}" if cells else ""
    script = BOOTSTRAP + (
        f"\npython tests/drc/run_cell_drc.py "
        f"--pdk {shlex.quote(pdk)} "
        f"--out-dir /work/.drc-cache/reports/{shlex.quote(pdk)}"
        f"{cells_arg}\n"
    )
    return [
        "docker", "run", "--rm", "--user", "root",
        "--entrypoint", "/bin/bash",
        "-v", f"{REPO_ROOT}:/work",
        "-w", "/work", image, "-lc", script,
    ]


def _lvs_command(pdk: str, cells: str | None, image: str) -> list[str]:
    inputs = f"/work/.drc-cache/reports/{pdk}"
    out = f"/work/.drc-cache/lvs/{pdk}"
    cells_arg = f" --cells {shlex.quote(cells)}" if cells else ""
    script = BOOTSTRAP + (
        f"\npython tests/lvs/run_cell_lvs.py "
        f"--pdk {shlex.quote(pdk)} "
        f"--inputs-dir {inputs} "
        f"--out-dir {out}"
        f"{cells_arg}\n"
    )
    return [
        "docker", "run", "--rm", "--user", "root",
        "--entrypoint", "/bin/bash",
        "-v", f"{REPO_ROOT}:/work",
        "-w", "/work", image, "-lc", script,
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdks", default=",".join(DEFAULT_DRC_PDKS),
                        help="Comma-separated PDKs to run DRC on (default: sky130,gf180).")
    parser.add_argument("--cells", default=None,
                        help="Comma-separated cell names; default runs every cell in the CSV.")
    parser.add_argument("--skip-drc", action="store_true", help="Skip DRC, run only LVS (requires existing DRC artifacts).")
    parser.add_argument("--skip-lvs", action="store_true", help="Skip LVS.")
    parser.add_argument("--lvs-pdks", default=",".join(DEFAULT_LVS_PDKS),
                        help="Comma-separated PDKs to run LVS on (default: sky130).")
    parser.add_argument("--image", default=IMAGE, help=f"Docker image to use (default: {IMAGE}).")
    parser.add_argument(
        "--serial", action="store_true",
        help="Run PDKs sequentially instead of in parallel containers.",
    )
    args = parser.parse_args()

    pdks = [p.strip() for p in args.pdks.split(",") if p.strip()]
    lvs_pdks = [p.strip() for p in args.lvs_pdks.split(",") if p.strip()]

    if subprocess.call(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        print("error: docker is not available — start Docker Desktop / dockerd first.", file=sys.stderr)
        return 2

    CACHE.mkdir(exist_ok=True)
    DRC_DIR.mkdir(exist_ok=True)
    LVS_DIR.mkdir(exist_ok=True)

    overall = 0

    if not args.skip_drc:
        if args.serial or len(pdks) <= 1:
            for pdk in pdks:
                print(f"\n========== DRC: {pdk} ==========")
                rc = subprocess.call(_drc_command(pdk, args.cells, args.image))
                print(f"---------- DRC: {pdk} → exit {rc} ----------")
                overall = overall or rc
        else:
            print(f"\n========== DRC: {pdks} (parallel) ==========")
            jobs = [(pdk, _drc_command(pdk, args.cells, args.image)) for pdk in pdks]
            overall = overall or _run_parallel("drc", jobs)

    if not args.skip_lvs:
        if args.serial or len(lvs_pdks) <= 1:
            for pdk in lvs_pdks:
                print(f"\n========== LVS: {pdk} ==========")
                rc = subprocess.call(_lvs_command(pdk, args.cells, args.image))
                print(f"---------- LVS: {pdk} → exit {rc} ----------")
                overall = overall or rc
        else:
            print(f"\n========== LVS: {lvs_pdks} (parallel) ==========")
            jobs = [(pdk, _lvs_command(pdk, args.cells, args.image)) for pdk in lvs_pdks]
            overall = overall or _run_parallel("lvs", jobs)

    print("\nResults:")
    for pdk in pdks:
        rpt = DRC_DIR / pdk / "summary.json"
        print(f"  DRC {pdk}: {'present' if rpt.exists() else 'MISSING'}  ({rpt})")
    for pdk in lvs_pdks:
        rpt = LVS_DIR / pdk / "summary.json"
        print(f"  LVS {pdk}: {'present' if rpt.exists() else 'MISSING'}  ({rpt})")
    return overall


if __name__ == "__main__":
    sys.exit(main())
