# gLayout — Cleanup & Runability Work

This update focuses on making the project easy to run and debug, and on getting the PCells into a stable, testable state.

## What changed
- Fixed/standardized import paths so modules under `src/glayout/` resolve reliably.
- Touched up the PCell scripts so they can be executed directly from the repo (without needing a package install).
- Collected helper scripts under `scripts/dataset/` for assembling and analyzing sweep/LHS results.
- Left design logic intact — the intent is to keep behavior the same while removing run blockers.

## Where things are
- The environment now loads cleanly (no missing `glayout`/`gdsfactory` imports if `src` is on `PYTHONPATH`).
- Remaining issues, if any, are *logic-level* in PCell code (e.g., undefined vars or incomplete construction) and can be iterated in-place.

## How to run locally
1. Use Python 3.10+.
2. From repo root, expose `src` on the import path:
   ```bash
   export PYTHONPATH=$(pwd)/src:$PYTHONPATH
   ```
   On Windows (PowerShell):
   ```powershell
   $env:PYTHONPATH = (Get-Location).Path + "\src;" + $env:PYTHONPATH
   ```
3. Run any PCell directly, e.g.:
   ```bash
   python blocks/elementary/FVF/fvf.py
   ```
4. Dataset helpers live in `scripts/dataset/`:
   - `analyze_dataset.py` expects `lhs_dataset_robust/lhs_results.json`
   - `assemble_dataset.py` expects `sweep_outputs/sweep_results.json`

## Notes
- If you need full GDS generation and LVS/DRC, install the real dependencies:
  ```bash
  pip install gdsfactory gdsfactory-sky130 gdsfactory-gf180
  ```
- For CI or quick checks, running with `PYTHONPATH=src` is usually enough.

---
If anything feels rough or you want a different layout for scripts, happy to adjust.
