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
 
  tests/sim/testbenches/<pdk>/<cell>.spice
 
Testbenches are per-PDK because rails, probe points, stimulus levels and pass
bands all differ between sky130's 1.8 V and gf180's 3.3 V devices. If the
per-PDK directory does not exist, the runner falls back to the flat
``tests/sim/testbenches/`` layout for backward compatibility.
 
The testbench is the stimulus + analysis + `.measure` cards only. It must NOT
declare the model `.lib`/`.include` lines or `.include` the DUT netlist — this
runner injects both so the same testbench works across corners. Instantiate
the DUT with a subckt call whose name matches the `.subckt <cell>` in the
reference netlist, e.g.:
 
    Vdd vdd 0 1.8
    Vin in 0 PULSE(0 1.8 1n 10p 10p 5n 10n)
    X1 in out vdd 0 <cell>
    .tran 10p 50n
    .measure tran tphl TRIG v(in) VAL=0.9 RISE=1 TARG v(out) VAL=0.9 FALL=1
 
Optionally, a sidecar ``.../testbenches/<pdk>/<cell>.checks.json`` gives pass
bands for measurements; without it a cell passes when ngspice finishes with no
fatal error and no failed `.measure`:
 
    { "tphl": {"max": 2e-9}, "tplh": {"max": 2e-9} }
 
This mirrors the LVS runner's shape so the same workflow plumbing (artifact
upload, JUnit publication) works unchanged.
 
MODEL HANDLING IS PER-PDK (see ``_model_deck_lines``). sky130 is a single
``.lib sky130.lib.spice <corner>``. gf180 is NOT: ``typical`` is not a
section of ``design.ngspice``, and the device models live in
``sm141064.ngspice`` split across several sections, so the deck needs
 
    .include design.ngspice
    .lib sm141064.ngspice typical          (MOS corner section)
    .lib sm141064.ngspice cap_mim
    .lib sm141064.ngspice res_typical
    .lib sm141064.ngspice moscap_typical
    .lib sm141064.ngspice mimcap_typical
 
which is what this runner assembles for --pdk gf180.
 
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
 
# Default corner per PDK: names the sky130.lib.spice section for sky130 and
# the sm141064.ngspice MOS section for gf180. Resolved straight from PDK_ROOT
# rather than via a glayout pdk attribute, so this doesn't depend on an API
# the LVS path doesn't already use. Override per run with --model-lib /
# --corner if your install differs.
_DEFAULT_CORNER = {"sky130": "tt", "gf180": "typical"}
 
# gf180 passive-device sections injected alongside the MOS corner section.
# These stay at their typical variants even when --corner overrides the MOS
# section (there is no res_fs etc.); skewed passives would need a custom deck.
_GF180_FIXED_SECTIONS = ("cap_mim", "res_typical", "moscap_typical", "mimcap_typical")
 
# Per-PDK geometry scale injected into the deck (`.option scale=<value>`).
# glayout reference netlists carry BARE MICRON w/l values (w=3 l=0.28). The
# sky130 model libs set `.option scale=1e-6` internally, so those netlists
# just work; the gf180 libs expect METERS and set no scale, so without this
# every MOS lands outside its model bins and ngspice dies with "could not
# find a valid modelname". Override per run with --scale.
_DEFAULT_SCALE = {"sky130": None, "gf180": "1e-6"}
 
 
def _deck_option_lines(pdk_name: str, scale_override: Optional[str] = None) -> List[str]:
    """Deck-global `.option` lines injected ahead of the model preamble."""
    scale = _DEFAULT_SCALE[pdk_name] if scale_override is None else scale_override
    if scale is None or str(scale).lower() in ("none", "off", ""):
        return []
    return [
        "* glayout netlists use micron-unit w/l; map them onto the meter-unit",
        "* model bins (sky130's lib sets this internally, gf180's does not).",
        f".option scale={scale}",
    ]
 
 
def _model_deck_lines(
    pdk_name: str,
    path_override: Optional[str] = None,
    corner_override: Optional[str] = None,
) -> Tuple[List[str], str, Path]:
    """Per-PDK model preamble for the assembled deck.
 
    Returns ``(deck_lines, corner, primary_model_path)``; the path is only
    used for logging and an early existence warning.
 
    sky130:  .lib "<...>/sky130.lib.spice" <corner>
    gf180:   .include "<...>/design.ngspice"            (params/options)
             .lib "<...>/sm141064.ngspice" <corner>     (MOS devices)
             .lib "<...>/sm141064.ngspice" cap_mim
             .lib "<...>/sm141064.ngspice" res_typical
             .lib "<...>/sm141064.ngspice" moscap_typical
             .lib "<...>/sm141064.ngspice" mimcap_typical
 
    Paths resolve from PDK_ROOT (gf180 via ciel's ``current`` pointer, the
    same pattern lvs.yml uses to locate the klayout deck). --model-lib
    overrides them: for sky130 pass the .lib file itself; for gf180 pass the
    ngspice models *directory* (the one holding design.ngspice and
    sm141064.ngspice) — pointing at either file inside it also works.
    """
    corner = corner_override or _DEFAULT_CORNER[pdk_name]
    root = Path(os.environ.get("PDK_ROOT", "/foss/pdks"))
 
    if pdk_name == "sky130":
        lib = Path(path_override) if path_override else (
            root / "sky130A/libs.tech/ngspice/sky130.lib.spice")
        return [f'.lib "{lib}" {corner}'], corner, lib
 
    # gf180: ciel keeps the active version behind a `current` pointer.
    if path_override:
        base = Path(path_override)
        if base.is_file():
            base = base.parent
    else:
        ver = (root / "ciel/gf180mcu/current").read_text().strip()
        base = root / "ciel/gf180mcu/versions" / ver / "gf180mcuD/libs.tech/ngspice"
    design = base / "design.ngspice"
    sm = base / "sm141064.ngspice"
    lines = [f'.include "{design}"', f'.lib "{sm}" {corner}']
    lines += [f'.lib "{sm}" {sec}' for sec in _GF180_FIXED_SECTIONS]
    return lines, corner, sm
 
 
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
        "rows": [],
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
    # Binned-model resolution failure: the model libs loaded, but the device's
    # W/L matched no bin. With glayout's micron-unit netlists this is almost
    # always a missing/wrong `.option scale` (see _DEFAULT_SCALE).
    if "could not find a valid modelname" in text.lower():
        summary["conclusion"] = ("no model bin for device W/L "
                                 "(units / .option scale mismatch?)")
        return summary
    # Model card not found / unresolved subckt — almost always a corner-section
    # mismatch or a DUT subckt name that doesn't match the .subckt in the
    # reference netlist.
    if re.search(r"unable to find definition of model|could not find a model|unknown subckt|unknown subcircuit", text, re.I):
        summary["conclusion"] = "missing model / unresolved subckt"
        return summary
 
    fatal = re.search(r"\bfatal\b|singular matrix|Timestep too small|simulation (?:aborted|interrupted)|iteration limit reached", text, re.I)
 
    # Capture `name = 1.23e-9` style measurement echoes, and any that failed.
    # ngspice prints `.measure` results under a "Measurements for <...> Analysis"
    # header; its end-of-run resource report (e.g. "Stack = 0 bytes.") also looks
    # like a bare `name = value`, so scope extraction to the measurement block(s)
    # and stop at the blank line that closes each. Fall back to a global scan
    # when no header is present, preserving prior behaviour.
    meas_re = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\b")
    headers = list(re.finditer(r"Measurements for .*?Analysis.*$", text, re.I | re.M))
    if headers:
        for h in headers:
            started = False
            for line in text[h.end():].splitlines():
                mm = meas_re.match(line)
                if mm:
                    summary["measures"][mm.group(1)] = float(mm.group(2))
                    started = True
                elif started and not line.strip():
                    break  # blank line closes the measurement block
    else:
        for mm in meas_re.finditer(text):
            summary["measures"][mm.group(1)] = float(mm.group(2))
    for m in re.finditer(r"(?:measure(?:ment)?\s+)?([A-Za-z_]\w*)\s*(?:=\s*failed|\bfailed\b)", text, re.I):
        if m.group(1).lower() not in ("the", "measurement"):
            summary["failed_measures"].append(m.group(1))
 
    if fatal:
        # Attach the log lines around the error so summary.json shows the
        # actual message (raw_tail often only catches the ngspice banner,
        # which is printed after the error).
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if fatal.group(0) in ln:
                summary["error_context"] = "\n".join(lines[max(0, i - 6): i + 7])
                break
        summary["conclusion"] = f"ngspice error: {fatal.group(0).strip()}"
        return summary
    if summary["failed_measures"]:
        summary["conclusion"] = "measurement failed"
        return summary
 
    # Build a per-measurement table: every measured value, annotated with its
    # band + verdict when a checks sidecar covers it. Built unconditionally so
    # the report can render a table whether the cell passes or fails, and so
    # the pass/fail verdict and the displayed table can never disagree.
    checked = checks or {}
    for name, val in summary["measures"].items():
        band = checked.get(name)
        lo = band.get("min") if band else None
        hi = band.get("max") if band else None
        if band is None:
            verdict = "n/a"
        elif (lo is not None and val < lo) or (hi is not None and val > hi):
            verdict = "FAIL"
            lo_s = "-inf" if lo is None else format(lo, "g")
            hi_s = "inf" if hi is None else format(hi, "g")
            summary["check_violations"].append(f"{name}={val:g} outside [{lo_s}, {hi_s}]")
        else:
            verdict = "PASS"
        summary["rows"].append(
            {"name": name, "value": val, "min": lo, "max": hi, "verdict": verdict}
        )
    # Bands declared in the sidecar with no matching measurement in the log.
    for name, band in checked.items():
        if name not in summary["measures"]:
            summary["check_violations"].append(f"{name}: not measured")
            summary["rows"].append(
                {"name": name, "value": None,
                 "min": band.get("min"), "max": band.get("max"), "verdict": "MISSING"}
            )
 
    if summary["check_violations"]:
        summary["conclusion"] = "out-of-spec measurement"
        return summary
 
    summary["is_pass"] = True
    summary["conclusion"] = "sim passed"
    return summary
 
 
def _fmt_eng(x: Optional[float]) -> str:
    """Compact engineering formatting for report tables (10.0u, 1.8m, -4.43e-13)."""
    if x is None:
        return "—"
    if x == 0:
        return "0"
    ax = abs(x)
    for suffix, scale in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0),
                          ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if ax >= scale:
            return f"{x / scale:.4g}{suffix}"
    return f"{x:.4g}"  # sub-pico: leave in scientific form
 
 
def _table_rows(rows: List[dict]) -> List[List[str]]:
    """Normalise measurement rows to string cells for the tables below."""
    def band(r: dict) -> str:
        lo, hi = r.get("min"), r.get("max")
        if lo is None and hi is None:
            return "—"
        return f"{_fmt_eng(lo)} … {_fmt_eng(hi)}"
    return [[r["name"], _fmt_eng(r["value"]), band(r), r["verdict"]] for r in rows]
 
 
def _ascii_table(rows: List[dict]) -> str:
    """Fixed-width table for the console log / JUnit system-out."""
    if not rows:
        return "    (no measurements captured)"
    header = ["measurement", "value", "limits", "result"]
    data = _table_rows(rows)
    widths = [max(len(header[i]), *(len(row[i]) for row in data)) for i in range(4)]
    line = lambda cells: "  " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells))
    sep = "  " + "-+-".join("-" * w for w in widths)
    return "\n".join([line(header), sep, *(line(r) for r in data)])
 
 
def _markdown_table(rows: List[dict]) -> str:
    """GitHub-flavoured Markdown table for the Actions step summary."""
    if not rows:
        return "_(no measurements captured)_"
    out = ["| measurement | value | limits | result |", "|---|---|---|---|"]
    for name, value, limits, verdict in _table_rows(rows):
        badge = {"PASS": "✅ PASS", "FAIL": "❌ FAIL",
                 "MISSING": "⚠️ MISSING", "n/a": "—"}.get(verdict, verdict)
        out.append(f"| `{name}` | {value} | {limits} | {badge} |")
    return "\n".join(out)
 
 
def _write_step_summary(results: List[dict], pdk: str, counts: Dict[str, int]) -> None:
    """Append a per-cell measurement table to $GITHUB_STEP_SUMMARY.
 
    No-op when the env var is unset (i.e. running locally), so this stays
    invisible outside CI. In CI it renders as real tables on the run's Summary
    page, alongside the JUnit check the publish step already posts.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        f"## ngspice checks — {pdk}",
        "",
        f"**{counts['pass']} passed · {counts['fail']} failed · "
        f"{counts['error']} error · {counts['skip']} skipped**",
        "",
    ]
    badge = {"pass": "✅", "fail": "❌", "error": "💥", "skip": "⏭️"}
    for r in results:
        rows = r.get("summary", {}).get("rows", [])
        lines.append(f"### {badge.get(r['status'], '')} `{r['cell']}` — {r['status'].upper()}")
        if r.get("message") and r["status"] != "pass":
            lines.append(f"> {r['message']}")
        lines.append("")
        lines.append(_markdown_table(rows))
        lines.append("")
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass
 
 
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
        # Attach the measurement table to every case so it shows in the JUnit
        # report body regardless of pass/fail.
        rows = r.get("summary", {}).get("rows", [])
        if rows:
            ET.SubElement(case, "system-out").text = "\n" + _ascii_table(rows) + "\n"
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
                   prelude_lines: List[str], corner: str, deck_path: Path) -> None:
    """Write a self-contained ngspice deck: prelude + DUT netlist + testbench.
 
    ``prelude_lines`` is the per-PDK deck prelude: the `.option` lines from
    ``_deck_option_lines()`` (e.g. the gf180 micron scale) followed by the
    model preamble from ``_model_deck_lines()`` — a single ``.lib <file>
    <corner>`` for sky130, or the design.ngspice include plus the
    sm141064.ngspice section set for gf180.
 
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
        + "\n".join(prelude_lines) + "\n"
        + f'.include "{netlist_path}"\n'
        + f"{body}\n"
        + ".end\n"
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
        # Pass bands come from the single consolidated checks file, loaded once
        # in main() and handed to each cell here. A per-cell <cell>.checks.json
        # sidecar still works as a legacy fallback for cells not listed in it.
        checks: Optional[Dict[str, dict]] = item.get("checks")
        if checks is None:
            sidecar = Path(item["testbench_path"]).with_suffix(".checks.json")
            if sidecar.exists():
                checks = json.loads(sidecar.read_text())
 
        _assemble_deck(
            name,
            Path(item["netlist_path"]),
            Path(item["testbench_path"]),
            item["prelude_lines"],
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
    rows = parsed.get("rows", [])
    if rows:
        print(_ascii_table(rows), flush=True)
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
        "--testbench-dir", default=None,
        help="Directory of <cell>.spice testbenches (and optional checks.json / "
             "<cell>.checks.json). Default: tests/sim/testbenches/<pdk>, falling "
             "back to the flat tests/sim/testbenches/ if the per-PDK directory "
             "is absent.",
    )
    parser.add_argument(
        "--model-lib", default=None,
        help="Override model location: for sky130 the .lib file itself; for "
             "gf180 the ngspice models directory holding design.ngspice and "
             "sm141064.ngspice.",
    )
    parser.add_argument(
        "--checks-file", default=None,
        help="Single JSON file of pass bands keyed by cell name "
             "(default: <testbench-dir>/checks.json). A per-cell "
             "<cell>.checks.json sidecar is used as a fallback for any cell "
             "not listed in this file.")
    parser.add_argument(
        "--scale", default=None,
        help="Override the injected `.option scale` (default: gf180=1e-6, "
             "sky130=none since its lib sets the scale itself). Pass 'none' "
             "to disable.",
    )
    parser.add_argument(
        "--corner", default=None,
        help="Override corner section (default: sky130=tt, gf180=typical). For "
             "gf180 this swaps only the sm141064 MOS section; passive sections "
             "stay at their typical variants.",
    )
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
    if args.testbench_dir:
        tb_dir = Path(args.testbench_dir).resolve()
    else:
        # Per-PDK layout first (rails/probe points/bands differ per PDK),
        # flat legacy layout as fallback.
        tb_dir = REPO_ROOT / "tests" / "sim" / "testbenches" / args.pdk
        if not tb_dir.is_dir():
            tb_dir = REPO_ROOT / "tests" / "sim" / "testbenches"
        tb_dir = tb_dir.resolve()
    out_dir = Path(args.out_dir).resolve()
    rpt_dir = out_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    rpt_dir.mkdir(parents=True, exist_ok=True)
    print(f"testbench dir: {tb_dir}")
 
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
 
    model_lines, corner, model_path = _model_deck_lines(args.pdk, args.model_lib, args.corner)
    if not model_path.exists():
        print(f"warning: model library not found at {model_path} "
              f"(PDK_ROOT={os.environ.get('PDK_ROOT', '/foss/pdks')})", file=sys.stderr)
    prelude_lines = _deck_option_lines(args.pdk, args.scale) + model_lines
    print(f"deck prelude (corner {corner}):\n  " + "\n  ".join(prelude_lines))
 
    # Load the single consolidated checks file once: { "<cell>": {band...} }.
    checks_file = Path(args.checks_file) if args.checks_file else (tb_dir / "checks.json")
    all_checks: Dict[str, dict] = {}
    if checks_file.exists():
        try:
            all_checks = json.loads(checks_file.read_text())
            print(f"checks file: {checks_file} ({len(all_checks)} cells with bands)")
        except json.JSONDecodeError as exc:
            print(f"warning: could not parse {checks_file}: {exc}", file=sys.stderr)
    else:
        print(f"no consolidated checks file at {checks_file} "
              f"(cells run as smoke tests unless a sidecar exists)")
 
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
            "checks": all_checks.get(name),
            "prelude_lines": prelude_lines,
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
    _write_step_summary(results, args.pdk, summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    return 0 if summary["fail"] == 0 and summary["error"] == 0 else 1
 
 
if __name__ == "__main__":
    sys.exit(main())
 
