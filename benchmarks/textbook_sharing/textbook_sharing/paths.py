"""Where the benchmark reads and writes.

Everything lives under the benchmark folder (``benchmarks/textbook_sharing``) unless an environment variable points
elsewhere:

  TSB_RUNS     run outputs: GDS, verification logs and one ``result.json`` per layout   (default: <benchmark>/runs)
  TSB_RESULTS  analysis outputs: the JSON tables behind every reported number            (default: <benchmark>/results)

Inputs that are part of the repository (frozen case definitions, nominal design points, frozen rules) are always read
from ``<benchmark>/data``.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # benchmarks/textbook_sharing
REPO = ROOT.parents[1]                              # repository root (provides src/glayout)
DATA = ROOT / "data"
CASES = DATA / "cases"                              # one folder per request: <topology>/<pdk>/<size>/
NOMINAL = DATA / "nominal"                          # nominal design point of every topology and PDK
FROZEN = DATA / "frozen"                            # rules and orders frozen before the measurements they govern
RUNS = Path(os.environ.get("TSB_RUNS", ROOT / "runs"))
RESULTS = Path(os.environ.get("TSB_RESULTS", ROOT / "results"))
GRID_RUNS = RUNS / "grid"                           # main grid: <topology>/<pdk>/<size>/<mode>/
SELECTION_RUNS = RUNS / "selection"                 # plan selection: <task>/<candidate>/
MODEL_RUNS = RUNS / "models"                        # model sessions: <model tag>/<task>/r<rep>/
MODEL_TASKS = RUNS / "model_tasks"                  # task folders handed to the models
MODEL_EXAMPLES = RUNS / "model_examples"            # worked examples shown to the models
PVT_RUNS = RUNS / "pvt"
REVIEW_BATCHES = RUNS / "review"                    # visual-review batches (rendered images and verdicts)
ANALYSIS = RESULTS / "analysis"
LEDGER = RESULTS / "count_ledger.json"


def setup_imports():
    """Make ``glayout`` (from this repository) and ``textbook_sharing`` importable when running from a checkout."""
    for p in (str(REPO / "src"), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    os.environ.setdefault("GLAYOUT_BACKEND", "gdsfactory")


def rel(path) -> str:
    """Path relative to the run or benchmark root, for records that must not contain machine-specific prefixes."""
    p = Path(path).resolve()
    for base, tag in ((RUNS.resolve(), "runs"), (ROOT.resolve(), "")):
        try:
            r = p.relative_to(base)
            return str(Path(tag) / r) if tag else str(r)
        except ValueError:
            continue
    return str(p)


def resolve(path) -> Path:
    """Inverse of rel(): a recorded path ('runs/...', 'data/...' or absolute) back to a file on this machine."""
    p = Path(path)
    if p.is_absolute():
        return p
    if p.parts and p.parts[0] == "runs":
        return RUNS.joinpath(*p.parts[1:])
    return ROOT / p
