"""Execute every tutorial notebook end-to-end and emit a pass/fail report.

Used by the GitHub Actions CI workflow at ``.github/workflows/notebooks.yml``.

Discovery & ordering
--------------------
Picks up every ``.ipynb`` under ``tutorial/`` and runs each one via
``jupyter nbconvert --to notebook --execute``. Within a single run, notebooks
that *write* helper modules (FVF/INV part 1) must execute before the notebooks
that *import* those helpers (FVF/INV part 2). We sort everything so that
``…_part1.ipynb`` deterministically lands before ``…_part2.ipynb``, then fall
back to alphabetical order.

Output layout
-------------
::

    <out-dir>/
      executed/<notebook-stem>.ipynb     # post-execution copy, kept on PASS too for diffing
      logs/<notebook-stem>.log           # full nbconvert stdout+stderr
      summary.json                       # { total, pass, fail, error, results: [...] }
      junit.xml                          # JUnit shaped like tests/drc/run_cell_drc.py

Exit code
---------
Non-zero if any notebook failed (cell error / kernel crash / timeout). Mirrors
the DRC runner so the workflow surfaces a red check + JUnit annotations.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
TUTORIAL_DIR = REPO_ROOT / "tutorial"


def _order_key(nb: Path) -> tuple:
    """Sort notebooks so helper-writers (part 1) precede helper-consumers
    (part 2), then alphabetical. We also pull the env-probing
    ``GLayout_Introduction`` to the front so any import-time failure shows up
    against the simplest notebook (easier triage in the JUnit view).
    """
    name = nb.name.lower()
    rel = str(nb.relative_to(TUTORIAL_DIR)).lower()
    # Tier 0: GLayout_Introduction — runs first as a smoke-test.
    if "glayout_introduction" in name:
        return (0, rel)
    # Tier 1: other layout-only walkthroughs.
    if any(s in name for s in ("glayout_via", "glayout_cmirror", "glayout_cells")):
        return (1, rel)
    # Tier 2: part-1 notebooks that emit helpers for part-2.
    if "part1" in name:
        return (2, rel)
    # Tier 3: part-2 notebooks that consume helpers from part-1.
    if "part2" in name:
        return (3, rel)
    # Tier 4: everything else (BJT, opamp, …).
    return (4, rel)


def _discover() -> List[Path]:
    nbs = sorted(TUTORIAL_DIR.rglob("*.ipynb"), key=_order_key)
    # Defensively skip checkpoint files in case .ipynb_checkpoints survives.
    return [p for p in nbs if ".ipynb_checkpoints" not in p.parts]


@dataclass
class NotebookResult:
    notebook: str          # path relative to repo root
    status: str            # pass / fail / error
    duration_s: float
    errored_cell: Optional[int] = None
    error_name: Optional[str] = None
    error_message: Optional[str] = None
    nbconvert_returncode: Optional[int] = None
    log_tail: Optional[str] = None
    executed_path: Optional[str] = None  # path relative to out-dir

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _scan_executed(path: Path) -> Optional[Dict[str, Any]]:
    """Return the first errored code cell from an executed notebook, or None
    if every code cell ran to completion. Strips ANSI so the JUnit body is
    readable in GitHub's UI.
    """
    try:
        nb = json.loads(path.read_text())
    except Exception as exc:  # nbconvert crashed before writing a parseable file
        return {"cell": -1, "ename": "NotebookParseError", "evalue": str(exc), "tb": ""}
    for i, c in enumerate(nb.get("cells", [])):
        if c.get("cell_type") != "code":
            continue
        for out in c.get("outputs", []):
            if out.get("output_type") == "error":
                tb = _ANSI.sub("", "\n".join(out.get("traceback", [])))
                return {
                    "cell": i,
                    "ename": out.get("ename", "?"),
                    "evalue": out.get("evalue", ""),
                    "tb": tb,
                }
    return None


def _as_text(data) -> str:
    """str/bytes/None -> str (subprocess.TimeoutExpired yields bytes)."""
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


# IPython startup file injected into every kernel nbconvert spawns (via
# IPYTHONDIR). It stops ipywidgets.Output from *capturing* cell output.
#
# Why: the tutorials wrap generation/display in `with widgets.Output():`
# blocks laid out in a GridspecLayout. Under headless nbconvert that capture
# makes nbclient sit idle for the full per-cell timeout after each such cell
# even though the kernel already reported idle - measured: GLayout_Cells took
# 10+ min per widget cell with capture, 11 s end-to-end without it. Grids,
# sliders and buttons still render as widgets; only the capture is disabled,
# so printed text and SVGs land in the normal cell output instead (which is
# also more useful in the executed notebook artifact).
_NOWIDGET_CAPTURE = """\
try:
    import ipywidgets as _w
    class _PassthroughOutput(_w.Output):
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
    _w.Output = _PassthroughOutput
    _w.widgets.Output = _PassthroughOutput
except Exception:
    pass
"""


def _kernel_env(out_dir: Path) -> dict:
    """Environment for nbconvert: IPYTHONDIR with the widget-capture stub."""
    ipy = out_dir / "ipythondir" / "profile_default" / "startup"
    ipy.mkdir(parents=True, exist_ok=True)
    (ipy / "00-ci-nowidget-capture.py").write_text(_NOWIDGET_CAPTURE)
    env = dict(os.environ)
    env["IPYTHONDIR"] = str(out_dir / "ipythondir")
    return env


def _run_one(
    nb: Path,
    executed_dir: Path,
    log_dir: Path,
    timeout_per_cell: int,
    timeout_per_notebook: int,
    kernel_name: str,
) -> NotebookResult:
    rel = str(nb.relative_to(REPO_ROOT))
    stem = nb.stem
    workdir = nb.parent
    executed = executed_dir / f"{stem}.ipynb"
    log = log_dir / f"{stem}.log"
    executed.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "jupyter", "nbconvert", "--to", "notebook", "--execute",
        f"--ExecutePreprocessor.timeout={timeout_per_cell}",
        "--ExecutePreprocessor.allow_errors=True",
        # On a per-cell timeout, interrupt the kernel and carry on so the
        # executed .ipynb is still written and _scan_executed can point at the
        # exact cell. nbconvert's default (False) kills the kernel and writes
        # nothing, which surfaces as an opaque "NbconvertCrash".
        "--ExecutePreprocessor.interrupt_on_timeout=True",
        f"--ExecutePreprocessor.kernel_name={kernel_name}",
        "--output", str(executed),
        nb.name,
    ]
    print(f"[RUN]  {rel}", flush=True)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, capture_output=True, text=True,
            timeout=timeout_per_notebook, env=_kernel_env(executed_dir.parent),
        )
        rc = proc.returncode
        log.write_text((proc.stdout or "") + "\n" + (proc.stderr or ""))
    except subprocess.TimeoutExpired as exc:
        # nbconvert blew through the per-notebook timeout — treat as error,
        # not failure, so the matrix view differentiates "test broke" from
        # "test ran and a cell complained".
        elapsed = time.monotonic() - start
        # TimeoutExpired carries bytes even when run() was given text=True.
        out = _as_text(exc.stdout)
        err = _as_text(exc.stderr)
        log.write_text(out + "\n" + err + f"\n[timeout after {timeout_per_notebook}s]\n")
        return NotebookResult(
            notebook=rel, status="error", duration_s=elapsed,
            error_name="NotebookTimeout",
            error_message=f"nbconvert exceeded {timeout_per_notebook}s",
            log_tail=err[-800:],
            executed_path=str(executed.relative_to(executed_dir.parent)) if executed.exists() else None,
        )

    elapsed = time.monotonic() - start
    rel_executed = str(executed.relative_to(executed_dir.parent)) if executed.exists() else None

    if rc != 0 and not executed.exists():
        # nbconvert crashed before writing the executed file (e.g. kernel
        # spec missing). Surface stderr so triage is one click away.
        return NotebookResult(
            notebook=rel, status="error", duration_s=elapsed,
            nbconvert_returncode=rc,
            error_name="NbconvertCrash",
            error_message=f"nbconvert exit {rc} with no output notebook",
            log_tail=(proc.stderr or proc.stdout or "")[-800:],
            executed_path=rel_executed,
        )

    err = _scan_executed(executed) if executed.exists() else None
    if err is None:
        return NotebookResult(
            notebook=rel, status="pass", duration_s=elapsed,
            nbconvert_returncode=rc,
            executed_path=rel_executed,
        )
    # The executed notebook has at least one error cell. Build a one-line
    # human summary plus the (trimmed) traceback so JUnit can render it.
    tb_lines = [l for l in err["tb"].splitlines() if l.strip()]
    tb_tail = "\n".join(tb_lines[-12:])
    return NotebookResult(
        notebook=rel, status="fail", duration_s=elapsed,
        nbconvert_returncode=rc,
        errored_cell=err["cell"],
        error_name=err["ename"],
        error_message=err.get("evalue", "")[:200],
        log_tail=tb_tail,
        executed_path=rel_executed,
    )


def _write_summary(results: List[NotebookResult], out: Path) -> None:
    body = {
        "total": len(results),
        "pass":  sum(1 for r in results if r.status == "pass"),
        "fail":  sum(1 for r in results if r.status == "fail"),
        "error": sum(1 for r in results if r.status == "error"),
        "results": [r.to_dict() for r in results],
    }
    out.write_text(json.dumps(body, indent=2))
    print(json.dumps({k: body[k] for k in ("total", "pass", "fail", "error")}, indent=2), flush=True)


def _write_junit(results: List[NotebookResult], out: Path) -> None:
    suite = ET.Element(
        "testsuite",
        attrib={
            "name": "glayout-tutorial-notebooks",
            "tests":    str(len(results)),
            "failures": str(sum(1 for r in results if r.status == "fail")),
            "errors":   str(sum(1 for r in results if r.status == "error")),
            "skipped":  "0",
        },
    )
    for r in results:
        case = ET.SubElement(
            suite, "testcase",
            attrib={
                "classname": "tutorial.notebooks",
                "name": r.notebook,
                "time": f"{r.duration_s:.2f}",
            },
        )
        if r.status == "fail":
            msg = f"{r.error_name or 'cell error'}: {r.error_message or ''}".strip()
            ET.SubElement(case, "failure", attrib={"message": msg}).text = json.dumps(r.to_dict(), indent=2)
        elif r.status == "error":
            msg = f"{r.error_name or 'error'}: {r.error_message or ''}".strip()
            ET.SubElement(case, "error", attrib={"message": msg}).text = json.dumps(r.to_dict(), indent=2)
    ET.ElementTree(suite).write(out, encoding="utf-8", xml_declaration=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default="notebook_results")
    p.add_argument(
        "--cell-timeout", type=int, default=600,
        help="Per-cell timeout passed to nbconvert (default: 600s; the magic "
             "PEX / netgen LVS cells are the long pole).",
    )
    p.add_argument(
        "--notebook-timeout", type=int, default=1200,
        help="Hard wall-clock cap per notebook (default: 1200s). Keep this well "
             "under the CI job timeout so junit.xml is always written.",
    )
    p.add_argument(
        "--kernel-name", default="python3",
        help="Jupyter kernel name to launch (default: python3).",
    )
    p.add_argument(
        "--only", default=None,
        help="Comma-separated notebook basenames (with or without .ipynb) to limit the run.",
    )
    args = p.parse_args()

    out_dir = Path(args.out_dir).resolve()
    executed_dir = out_dir / "executed"
    log_dir = out_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    executed_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    nbs = _discover()
    if args.only:
        wanted = {s.strip().removesuffix(".ipynb") for s in args.only.split(",") if s.strip()}
        nbs = [nb for nb in nbs if nb.stem in wanted]

    if not nbs:
        print("no tutorial notebooks found", file=sys.stderr)
        return 2

    print(f"running {len(nbs)} notebook(s):", flush=True)
    for nb in nbs:
        print(f"  - {nb.relative_to(REPO_ROOT)}", flush=True)
    print(flush=True)

    results: List[NotebookResult] = []
    for nb in nbs:
        r = _run_one(
            nb, executed_dir, log_dir,
            timeout_per_cell=args.cell_timeout,
            timeout_per_notebook=args.notebook_timeout,
            kernel_name=args.kernel_name,
        )
        print(f"[{r.status.upper()}] {r.notebook} ({r.duration_s:.1f}s)" +
              (f" — cell {r.errored_cell} {r.error_name}: {r.error_message}"
               if r.status != "pass" else ""),
              flush=True)
        results.append(r)

    _write_summary(results, out_dir / "summary.json")
    _write_junit(results, out_dir / "junit.xml")

    # Exit non-zero so the workflow fails on the first regression.
    return 0 if all(r.status == "pass" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
