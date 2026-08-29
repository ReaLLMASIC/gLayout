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


def _strip_displays(nb: Path) -> Path:
    """Write a sibling copy of `nb` with display calls removed, for CI.

    The tutorials push multi-MB SVGs through iopub (display_component draws
    the whole opamp: ~2.7 MB per message). Measured on the runner itself,
    that is what stalls the kernel<->client transport: the same notebook run
    3x with displays stalled or died every time, and 3x without them ran
    clean in 12.5s. CI executes for regressions, not for pictures, so the
    displays go.

    Lines are dropped, not commented, matching the measured experiment. If
    dropping a line leaves a cell that no longer compiles (say, a display
    that was the only statement under a `with`), that cell keeps its
    original source: correctness over stripping.
    """
    import json
    doc = json.loads(nb.read_text(encoding="utf-8"))
    quitar = ("display_component(", "display_gds(", "display(")
    for cell in doc.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        original = cell["source"]
        kept = [l for l in original if not any(q in l for q in quitar)]
        if kept == original:
            continue
        try:
            compile("".join(kept), "<cell>", "exec")
        except SyntaxError:
            continue
        cell["source"] = kept
    out = nb.with_name(nb.stem + "__stripped.ipynb")
    out.write_text(json.dumps(doc), encoding="utf-8")
    return out


def _run_one(
    nb: Path,
    executed_dir: Path,
    log_dir: Path,
    timeout_per_cell: int,
    timeout_per_notebook: int,
    kernel_name: str,
    strip_displays: bool = False,
) -> NotebookResult:
    rel = str(nb.relative_to(REPO_ROOT))
    stem = nb.stem
    workdir = nb.parent
    a_ejecutar = _strip_displays(nb) if strip_displays else nb
    executed = executed_dir / f"{stem}.ipynb"
    log = log_dir / f"{stem}.log"
    executed.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "jupyter", "nbconvert", "--to", "notebook", "--execute",
        f"--ExecutePreprocessor.timeout={timeout_per_cell}",
        "--ExecutePreprocessor.allow_errors=True",
        f"--ExecutePreprocessor.kernel_name={kernel_name}",
        "--output", str(executed),
        a_ejecutar.name,
    ]
    print(f"[RUN]  {rel}", flush=True)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, capture_output=True, text=True,
            timeout=timeout_per_notebook,
        )
        rc = proc.returncode
        log.write_text((proc.stdout or "") + "\n" + (proc.stderr or ""))
    except subprocess.TimeoutExpired as exc:
        # nbconvert blew through the per-notebook timeout — treat as error,
        # not failure, so the matrix view differentiates "test broke" from
        # "test ran and a cell complained".
        elapsed = time.monotonic() - start
        log.write_text((exc.stdout or "") + "\n" + (exc.stderr or "") + f"\n[timeout after {timeout_per_notebook}s]\n")
        return NotebookResult(
            notebook=rel, status="error", duration_s=elapsed,
            error_name="NotebookTimeout",
            error_message=f"nbconvert exceeded {timeout_per_notebook}s",
            log_tail=(exc.stderr or "")[-800:],
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
        "--cell-timeout", type=int, default=180,
        help="Per-cell timeout passed to nbconvert (default: 180s).",
    )
    p.add_argument(
        "--notebook-timeout", type=int, default=900,
        help="Hard wall-clock cap per notebook (default: 900s).",
    )
    p.add_argument(
        "--kernel-name", default="python3",
        help="Jupyter kernel name to launch (default: python3).",
    )
    p.add_argument(
        "--strip-displays", action="store_true",
        help="Drop display calls before executing. The multi-MB SVGs they "
             "push through iopub are what stalls the kernel transport in CI "
             "(measured: 3/3 stalled with them, 3/3 clean at 12.5s without).",
    )
    p.add_argument(
        "--retries", type=int, default=0,
        help="Re-run a notebook that ends in 'error' (crash/timeout, not a "
             "cell failure) up to this many times. Transport races lose "
             "messages; a genuinely broken notebook still fails every try.",
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
        for intento in range(1 + max(0, args.retries)):
            r = _run_one(
                nb, executed_dir, log_dir,
                timeout_per_cell=args.cell_timeout,
                timeout_per_notebook=args.notebook_timeout,
                kernel_name=args.kernel_name,
                strip_displays=args.strip_displays,
            )
            # only "error" (nbconvert crash / timeout) is worth retrying:
            # that is the transport-race class. A "fail" is a real cell
            # exception and retrying it would only hide it.
            if r.status != "error" or intento == args.retries:
                break
            print(f"[RETRY] {r.notebook} ({r.duration_s:.1f}s) "
                  f"{r.error_name}: attempt {intento + 2}", flush=True)
        temporal = nb.with_name(nb.stem + "__stripped.ipynb")
        if temporal.exists():
            temporal.unlink()
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
