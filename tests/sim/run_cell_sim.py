"""Runs ngspice on every cell using the reference netlist emitted by
``tests/drc/run_cell_drc.py`` plus a per-cell testbench.

The sim CI workflow pulls the DRC artifact (``drc_results/<pdk>/``), which
contains:

  drc_results/<pdk>/
    gds/<cell>.gds
    netlists/<cell>.spice          <-- DUT subckt, written by run_cell_drc.py
    reports/<cell>.lyrdb
    summary.json

A cell is simulated when it has BOTH that reference netlist AND a testbench at:

  tests/sim/testbenches/<cell>.spice

The testbench is the stimulus + analysis + `.measure` cards only. It must NOT
declare the model `.lib` or `.include` the DUT netlist — this runner injects
both so the same testbench works across corners/PDKs. Instantiate the DUT with
a subckt call whose name matches the `.subckt <cell>` in the reference netlist,
e.g.:

    Vdd vdd 0 1.8
    Vin in 0 PULSE(0 1.8 1n 10p 10p 5n 10n)
    X1 in out vdd 0 <cell>
    .tran 10p 50n
    .measure tran tphl TRIG v(in) VAL=0.9 RISE=1 TARG v(out) VAL=0.9 FALL=1

Optionally, a sidecar ``tests/sim/testbenches/<cell>.checks.json`` gives pass
bands for measurements; without it a cell passes when ngspice finishes with no
fatal error and no failed `.measure`:

    { "tphl": {"max": 2e-9}, "tplh": {"max": 2e-9} }

This mirrors the LVS runner's shape so the same workflow plumbing (artifact
upload, JUnit publication) works unchanged.

By default this simulates the *reference* netlist (pre-layout / functional
check). Post-layout (PEX) sim is a documented extension point in
``_assemble_deck`` — it's left off the default path because per-cell magic
extraction in CI is slow and, for gf180, mis-extracts the substrate (same
reason the LVS runner drives the klayout deck for gf180).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]

# Per-PDK ngspice model library + default corner section. Resolved straight
# from PDK_ROOT rather than via a glayout pdk attribute, so this doesn't depend
# on an API the LVS path doesn't already use. Override per run with
# --model-lib / --corner if your install differs.
_DEFAULT_CORNER = {"sky130": "tt", "gf180": "typical"}


def _model_lib(
    pdk_name: str,
    path_override: Optional[str] = None,
    corner_override: Optional[str] = None,
) -> Tuple[Path, str]:
    corner = corner_override or _DEFAULT_CORNER[pdk_name]
    if path_override:
        return Path(path_override), corner
    root = Path(os.environ.get("PDK_ROOT", "/foss/pdks"))
    if pdk_name == "sky130":
        return root / "sky130A/libs.tech/ngspice/sky130.lib.spice", corner
    # gf180: ciel keeps the active version behind a `current` pointer (same
    # pattern lvs.yml uses to locate the klayout deck).
    ver = (root / "ciel/gf180mcu/current").read_text().strip()
    base = root / "ciel/gf180mcu/versions" / ver / "gf180mcuD/libs.tech/ngspice"
    cand = base / "design.ngspice"
    if not cand.exists():
        libs = (
            sorted(base.glob("*.ngspice"))
            + sorted(base.glob("*.lib.spice"))
            + sorted(base.glob("*.spice"))
        )
        if libs:
            cand = libs[0]
    return cand, corner


def _parse_sim_log(text: str, checks: Optional[Dict[str, dict]]) -> Dict[str, Any]:
    """Lightweight parse of an ngspice batch log.

    Surfaces the common environment failures explicitly (mirroring the LVS
    parser) so a broken container reads as e.g. "ngspice not on PATH" rather
    than the catch-all "sim inconclusive". Then extracts `.measure` results and
    decides pass/fail: clean finish + no failed measure + (if a checks sidecar
    is given) every measurement inside its band.
    """
    summary: Dict[str, Any] = {
        "is_pass": False,
        "conclusion": "sim inconclusive",
        "measures": {},
        "failed_measures": [],
        "check_violations": [],
        "raw_tail": text[-1500:] if text else "",
    }
    if not text:
        return summary

    if "ngspice: command not found" in text or "ngspice: not found" in text:
        summary["conclusion"] = "ngspice binary not on PATH"
        return summary
    if "could not find include file" in text or "can't open file" in text.lower():
        summary["conclusion"] = "missing include / model lib"
        return summary
    # Model card not found / unresolved subckt — almost always a corner-section
    # mismatch or a DUT subckt name that doesn't match the .subckt in the
    # reference netlist.
    if re.search(r"unable to find definition of model|could not find a model|unknown subckt|unknown subcircuit", text, re.I):
        summary["conclusion"] = "missing model / unresolved subckt"
        return summary

    fatal = re.search(r"\bfatal\b|singular matrix|Timestep too small|simulation (?:aborted|interrupted)|iteration limit reached", text, re.I)

    # Capture `name = 1.23e-9` style measurement echoes, and any that failed.
    for m in re.finditer(r"^\s*([A-Za-z_]\w*)\s*=\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\b", text, re.M):
        summary["measures"][m.group(1)] = float(m.group(2))
    for m in re.finditer(r"(?:measure(?:ment)?\s+)?([A-Za-z_]\w*)\s*(?:=\s*failed|\bfailed\b)", text, re.I):
        if m.group(1).lower() not in ("the", "measurement"):
            summary["failed_measures"].append(m.group(1))

    if fatal:
        summary["conclusion"] = f"ngspice error: {fatal.group(0).strip()}"
        return summary
    if summary["failed_measures"]:
        summary["conclusion"] = "measurement failed"
        return summary

    if checks:
        for name, band in checks.items():
            if name not in summary["measures"]:
                summary["check_violations"].append(f"{name}: not measured")
                continue
            val = summary["measures"][name]
            lo, hi = band.get("min"), band.get("max")
            if lo is not None and val < lo:
                summary["check_violations"].append(f"{name}={val:g} < min {lo:g}")
            if hi is not None and val > hi:
                summary["check_violations"].append(f"{name}={val:g} > max {hi:g}")
        if summary["check_violations"]:
            summary["conclusion"] = "out-of-spec measurement"
            return summary

    summary["is_pass"] = True
    summary["conclusion"] = "sim passed"
    return summary


def _write_junit(results: List[dict], pdk: str, out: Path) -> None:
    suite = ET.Element(
        "testsuite",
        attrib={
            "name": f"glayout-sim-{pdk}",
            "tests": str(len(results)),
            "failures": str(sum(1 for r in results if r["status"] == "fail")),
            "errors": str(sum(1 for r in results if r["status"] == "error")),
            "skipped": str(sum(1 for r in results if r["status"] == "skip")),
        },
    )
    for r in results:
        case = ET.SubElement(
            suite, "testcase",
            attrib={"classname": f"sim.{pdk}", "name": r["cell"]},
        )
        if r["status"] == "fail":
            ET.SubElement(case, "failure", attrib={"message": r.get("message", "sim failed")}).text = json.dumps(r, indent=2)
        elif r["status"] == "error":
            ET.SubElement(case, "error", attrib={"message": r.get("message", "sim error")}).text = json.dumps(r, indent=2)
        elif r["status"] == "skip":
            ET.SubElement(case, "skipped", attrib={"message": r.get("message", "skipped")})
    ET.ElementTree(suite).write(out, encoding="utf-8", xml_declaration=True)


def _enumerate_cells(inputs_dir: Path, tb_dir: Path) -> Tuple[List[str], int]:
    """Cells that have BOTH a reference netlist and a testbench.

    Returns (simulatable_cells, total_netlists) so main() can tell the
    difference between "broken artifact" (no netlists at all) and "nothing
    wired up yet" (netlists exist but no testbenches).
    """
    nets = {p.stem for p in (inputs_dir / "netlists").glob("*.spice")} if (inputs_dir / "netlists").is_dir() else set()
    tbs = {p.stem for p in tb_dir.glob("*.spice")} if tb_dir.is_dir() else set()
    return sorted(nets & tbs), len(nets)


def _assemble_deck(name: str, netlist_path: Path, testbench_path: Path,
                   model_lib: Path, corner: str, deck_path: Path) -> None:
    """Write a self-contained ngspice deck: model lib + DUT netlist + testbench.

    POST-LAYOUT (PEX) EXTENSION: to simulate parasitics instead of the
    reference netlist, extract a `<cell>.pex.spice` from gds/<cell>.gds via a
    magic batch step (extract all; ext2spice cthresh 0; extresist all;
    ext2spice extresist on) and point `.include` at that file instead of
    `netlist_path`. Gate it behind a --pex flag and skip gf180 (substrate
    mis-extraction, as in the LVS runner).
    """
    body = testbench_path.read_text()
    # Drop a trailing `.end` from the testbench so ours is the only one.
    body = re.sub(r"^\s*\.end\s*$", "", body, flags=re.M | re.I).rstrip()
    deck = (
        f"* auto-assembled deck for {name} ({corner})\n"
        f'.lib "{model_lib}" {corner}\n'
        f'.include "{netlist_path}"\n'
        f"{body}\n"
        f".end\n"
    )
    deck_path.write_text(deck)


def _run_one_sim(item: dict) -> dict:
    """Simulate one cell. Designed for ProcessPoolExecutor."""
    name = item["name"]
    pdk_name = item["pdk"]
    out_dir = Path(item["out_dir"])
    cell_dir = Path(item["rpt_dir"]) / "sim" / name
    cell_dir.mkdir(parents=True, exist_ok=True)
    deck_path = cell_dir / f"{name}.deck.spice"
    log_path = cell_dir / f"{name}.log"
    result: Dict[str, Any] = {"cell": name, "pdk": pdk_name, "status": "skip"}

    try:
        print(f"[SIM]  {name}", flush=True)
        checks: Optional[Dict[str, dict]] = None
        checks_path = Path(item["testbench_path"]).with_suffix(".checks.json")
        if checks_path.exists():
            checks = json.loads(checks_path.read_text())

        _assemble_deck(
            name,
            Path(item["netlist_path"]),
            Path(item["testbench_path"]),
            Path(item["model_lib"]),
            item["corner"],
            deck_path,
        )

        # Batch mode with NO `.control` block: avoids the well-known
        # double-execution when `-b` is combined with `.control ... run`.
        proc = subprocess.run(
            ["ngspice", "-b", "-o", str(log_path), str(deck_path)],
            capture_output=True, text=True, timeout=item["timeout"],
        )
        captured = (proc.stdout or "") + "\n" + (proc.stderr or "")
        log_text = (log_path.read_text() if log_path.exists() else "") + "\n" + captured
    except subprocess.TimeoutExpired:
        result.update({"status": "error", "message": f"sim timed out after {item['timeout']}s"})
        print(f"[ERROR] {name}: timed out", flush=True)
        return result
    except Exception as exc:
        result.update({"status": "error", "message": f"sim failed: {exc}", "trace": traceback.format_exc()})
        print(f"[ERROR] {name}: {exc}", flush=True)
        return result

    parsed = _parse_sim_log(log_text, checks)
    result.update({
        "summary": parsed,
        "returncode": proc.returncode,
        "deck": str(deck_path.relative_to(out_dir)),
        "log": str(log_path.relative_to(out_dir)) if log_path.exists() else None,
    })
    if parsed["is_pass"] and proc.returncode == 0:
        result["status"] = "pass"
        result["message"] = "sim passed"
    elif parsed["check_violations"]:
        result["status"] = "fail"
        result["message"] = "; ".join(parsed["check_violations"])[:300]
    else:
        result["status"] = "fail"
        result["message"] = parsed["conclusion"]
    print(f"[{result['status'].upper()}] {name}: {result.get('message','')}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdk", required=True, choices=["sky130", "gf180"])
    parser.add_argument(
        "--inputs-dir", required=True,
        help="Directory containing netlists/<cell>.spice (DRC artifact root for the PDK).",
    )
    parser.add_argument("--out-dir", default="sim_results")
    parser.add_argument(
        "--testbench-dir", default=str(REPO_ROOT / "tests" / "sim" / "testbenches"),
        help="Directory of <cell>.spice testbenches (and optional <cell>.checks.json).",
    )
    parser.add_argument("--model-lib", default=None, help="Override ngspice model library path.")
    parser.add_argument("--corner", default=None, help="Override corner section (default: sky130=tt, gf180=typical).")
    parser.add_argument(
        "--cells", default=None,
        help="Comma-separated cell names; default runs every cell with both netlist+testbench.",
    )
    parser.add_argument(
        "--skip-cells", default="",
        help="Comma-separated cell names to skip when --cells is not specified.",
    )
    parser.add_argument("--timeout", type=int, default=600, help="Per-cell ngspice timeout in seconds.")
    parser.add_argument(
        "--jobs", "-j", type=int, default=max(1, (os.cpu_count() or 2) - 1),
        help="Worker processes for parallel sims (default: cpu_count-1).",
    )
    args = parser.parse_args()

    inputs_dir = Path(args.inputs_dir).resolve()
    tb_dir = Path(args.testbench_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    rpt_dir = out_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    rpt_dir.mkdir(parents=True, exist_ok=True)

    cells, total_nets = _enumerate_cells(inputs_dir, tb_dir)
    if total_nets == 0:
        print(f"no netlists found under {inputs_dir}/netlists (broken DRC artifact?)", file=sys.stderr)
        return 2
    if not cells:
        # Netlists exist but nothing has a testbench yet. Treat as a no-op pass
        # (write summary.json, no junit.xml) so adding this workflow doesn't red
        # the build before testbenches are authored — the publish step is gated
        # on junit.xml existing, so it just skips.
        msg = f"no testbenches in {tb_dir} matching the {total_nets} available netlist(s); nothing to simulate"
        print(msg)
        (out_dir / "summary.json").write_text(json.dumps(
            {"pdk": args.pdk, "total": 0, "note": msg}, indent=2))
        return 0

    model_lib, corner = _model_lib(args.pdk, args.model_lib, args.corner)
    print(f"model lib: {model_lib} (corner {corner})")

    if args.cells:
        wanted = {c.strip() for c in args.cells.split(",") if c.strip()}
        missing = wanted - set(cells)
        if missing:
            print(f"warning: cells without netlist+testbench: {sorted(missing)}", file=sys.stderr)
        cells = [c for c in cells if c in wanted]
    elif args.skip_cells:
        skip = {c.strip() for c in args.skip_cells.split(",") if c.strip()}
        for s in [c for c in cells if c in skip]:
            print(f"skipping cell on the --skip-cells list: {s}")
        cells = [c for c in cells if c not in skip]

    work_items = [
        {
            "name": name,
            "pdk": args.pdk,
            "netlist_path": str(inputs_dir / "netlists" / f"{name}.spice"),
            "testbench_path": str(tb_dir / f"{name}.spice"),
            "model_lib": str(model_lib),
            "corner": corner,
            "out_dir": str(out_dir),
            "rpt_dir": str(rpt_dir),
            "timeout": args.timeout,
        }
        for name in cells
    ]
    jobs = max(1, min(args.jobs, len(work_items)))
    print(f"running {len(work_items)} cells with {jobs} worker(s)")
    from concurrent.futures import ProcessPoolExecutor, as_completed
    results: List[dict] = []
    if jobs == 1:
        for item in work_items:
            results.append(_run_one_sim(item))
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_run_one_sim, item): item["name"] for item in work_items}
            for fut in as_completed(futures):
                results.append(fut.result())
    name_order = {n: i for i, n in enumerate(cells)}
    results.sort(key=lambda r: name_order.get(r["cell"], len(name_order)))

    summary = {
        "pdk": args.pdk,
        "total": len(results),
        "pass": sum(1 for r in results if r["status"] == "pass"),
        "fail": sum(1 for r in results if r["status"] == "fail"),
        "error": sum(1 for r in results if r["status"] == "error"),
        "skip": sum(1 for r in results if r["status"] == "skip"),
        "results": results,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    _write_junit(results, args.pdk, out_dir / "junit.xml")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    return 0 if summary["fail"] == 0 and summary["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
