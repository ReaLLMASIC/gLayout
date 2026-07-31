"""Runs Klayout DRC on every glayout cell for a chosen PDK.

Used by the GitHub Actions CI workflow at ``.github/workflows/drc.yml``.

The script:
  * builds each registered cell with a small, deterministic parameter set,
  * writes a GDS to a per-cell output directory,
  * invokes ``klayout -b -r <drc-deck>`` with ``input``/``report`` runtime
    variables, mirroring ``MappedPDK.drc`` for klayout <= 0.29,
  * parses the resulting ``lyrdb`` to count violations,
  * emits a JSON summary, a JUnit report, and exits non-zero if any cell has
    DRC errors or fails to build.

gf180 notes
-----------
The bundled ``gf180mcu.drc`` reads its configuration from global Ruby
variables ($metal_top, $metal_level, $mim_option, $run_mode, $thr, $offgrid).
Every one of them has an internal fallback, so the deck *runs* without them --
but the fallbacks are 9K / 6LM / "Nan" MIM, which do not match this PDK's
5-metal layer map and silently skip ALL MIM capacitor checks. We therefore
pass them explicitly via ``-rd`` for variant D (5LM / 11K / MIM-B), matching
the ``--variant=D`` used by the klayout LVS deck in tests/lvs/klayout_gf180.py.

Do NOT point this runner at ``gf180mcu_drc_wrapper.drc``: that wrapper exists
for ``MappedPDK.drc`` (which uses in_gds/report_file naming) and presets the
variant-A metal stack (30K / 3LM / MIM-A), which would drop every metal4 and
metal5 BEOL rule.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLED_DECKS = {
    "sky130": REPO_ROOT / "src" / "glayout" / "pdk" / "sky130_mapped" / "sky130.lydrc",
    "gf180":  REPO_ROOT / "src" / "glayout" / "pdk" / "gf180_mapped" / "gf180mcu.drc",
}
DEFAULT_PARAM_DIR = REPO_ROOT / "tests" / "parameters"

# gf180mcu metal-stack variants: variant -> (metal_top, metal_level, mim_option).
# Mirrors the mapping in the PDK's own run_drc_main klayout macro.
GF180_VARIANTS = {
    "A": ("30K", "3LM", "A"),
    "B": ("11K", "4LM", "B"),
    "C": ("9K",  "5LM", "B"),
    "D": ("11K", "5LM", "B"),
}


@dataclass
class CellSpec:
    name: str
    builder: Callable[..., Any]
    kwargs: Dict[str, Any] = field(default_factory=dict)


# Cell-name -> import path for the builder. Builders are imported lazily so
# that an import error in one cell doesn't kill the whole runner.
_CELL_BUILDERS: Dict[str, str] = {
    "current_mirror_nfet":                    "glayout.cells.elementary:current_mirror",
    "current_mirror_pfet":                    "glayout.cells.elementary:current_mirror",
    "diff_pair":                              "glayout.cells.elementary:diff_pair",
    "flipped_voltage_follower":               "glayout.cells.elementary:flipped_voltage_follower",
    "transmission_gate":                      "glayout.cells.elementary:transmission_gate",
    "differential_to_single_ended_converter": "glayout.cells.composite:differential_to_single_ended_converter",
    "diff_pair_ibias":                        "glayout.cells.composite:diff_pair_ibias",
    "low_voltage_cmirror":                    "glayout.cells.composite:low_voltage_cmirror",
    "opamp":                                  "glayout.cells.composite:opamp",
}


def _resolve_builder(import_path: str) -> Callable[..., Any]:
    module_name, attr = import_path.split(":", 1)
    module = __import__(module_name, fromlist=[attr])
    return getattr(module, attr)


def _coerce_tuples(value: Any) -> Any:
    """JSON has no tuples — recursively convert lists back to tuples for builders
    that pydantic-validate ``tuple[...]``. Keeps dicts/scalars untouched."""
    if isinstance(value, list):
        return tuple(_coerce_tuples(v) for v in value)
    if isinstance(value, dict):
        return {k: _coerce_tuples(v) for k, v in value.items()}
    return value


def _load_param_csv(path: Path) -> Dict[str, Dict[str, Any]]:
    """Read ``cell,params_json`` rows into a {cell: kwargs} mapping."""
    if not path.exists():
        raise FileNotFoundError(f"parameter file not found: {path}")
    out: Dict[str, Dict[str, Any]] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "cell" not in reader.fieldnames or "params_json" not in reader.fieldnames:
            raise ValueError(f"{path} must have header 'cell,params_json'")
        for row in reader:
            name = (row.get("cell") or "").strip()
            if not name or name.startswith("#"):
                continue
            raw = (row.get("params_json") or "").strip()
            try:
                kwargs = json.loads(raw) if raw else {}
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: row '{name}' has invalid JSON: {exc}") from exc
            if not isinstance(kwargs, dict):
                raise ValueError(f"{path}: row '{name}' params_json must be a JSON object")
            out[name] = {k: _coerce_tuples(v) for k, v in kwargs.items()}
    return out


def _load_cell_specs(pdk: str, param_csv: Optional[Path]) -> Dict[str, CellSpec]:
    """Load a {cell_name: CellSpec} for the given PDK from the CSV.

    Cells listed in the CSV but unknown to ``_CELL_BUILDERS`` raise an error.
    Cells defined in ``_CELL_BUILDERS`` but missing from the CSV are silently
    skipped — the CSV is the source of truth for what runs in CI.
    """
    csv_path = param_csv or DEFAULT_PARAM_DIR / f"ci_drc_{pdk}.csv"
    rows = _load_param_csv(csv_path)
    unknown = sorted(set(rows) - set(_CELL_BUILDERS))
    if unknown:
        raise ValueError(f"{csv_path}: unknown cell(s) {unknown}; add a builder mapping in run_cell_drc.py")
    specs: Dict[str, CellSpec] = {}
    for name, kwargs in rows.items():
        specs[name] = CellSpec(
            name=name,
            builder=_resolve_builder(_CELL_BUILDERS[name]),
            kwargs=kwargs,
        )
    return specs


def _resolve_pdk(pdk_name: str):
    if pdk_name == "sky130":
        from glayout import sky130
        if sky130 is None:
            raise RuntimeError("sky130 PDK could not be imported")
        return sky130
    if pdk_name == "gf180":
        from glayout import gf180
        if gf180 is None:
            raise RuntimeError("gf180 PDK could not be imported")
        return gf180
    raise ValueError(f"Unsupported PDK: {pdk_name}")


def _drc_deck_for(pdk_name: str, override: Optional[str] = None) -> Path:
    if override:
        return Path(override).resolve()
    if pdk_name not in BUNDLED_DECKS:
        raise ValueError(f"Unsupported PDK: {pdk_name}")
    return BUNDLED_DECKS[pdk_name]


# ---------------------------------------------------------------------------
# Rules that are not functional defects for a standalone cell.
# Match by category name OR description (case-insensitive).
# ---------------------------------------------------------------------------
_IGNORE_PATTERNS = [
    re.compile(r"density", re.IGNORECASE),

    # Minimum-area rules. The phrasing differs per engine/PDK:
    #   magic (sky130):  "Metal1 minimum area < 0.083um^2"
    #   klayout sky130:  m1.4 / m2.4 / ... (matched by name below)
    #   klayout gf180:   "Minimum Metal1 area : 0.1444um^2"   <- M1.3 .. M5.3
    #                    "Min. COMP area (um2)"               <- DF.9
    # A single pattern anchored on min...area (with anything in between up to
    # the ':' separator) covers all of them. The earlier
    # r"min[._\s-]*\w*\s*area" form did NOT match "Minimum Metal1 area",
    # because \w* consumed "imum" and then "area" had to match "Metal1".
    re.compile(r"\bmin(?:imum)?\b[^:]*\barea\b", re.IGNORECASE),

    # sky130 metal min-area rules, matched by rule name.
    re.compile(r"^m\d+\.4$", re.IGNORECASE),

    # gf180 DF.13 / DF.14: max distance from a well tap / substrate tap to the
    # nearest transistor of the opposite type. Both are chip-level latch-up
    # constraints -- a single cell containing only NMOS (or only PMOS) cannot
    # satisfy them in isolation, and glayout cells are placed into a larger
    # design that provides the taps.
    re.compile(r"^DF\.13", re.IGNORECASE),
    re.compile(r"^DF\.14", re.IGNORECASE),
]

# Rules the gf180 deck emits as explicit *recommendations* / guidelines rather
# than hard defects (their own descriptions say "It is recommended" /
# "Guideline"). They fire on isolated cells that have no surrounding guard
# ring. Enable with --ignore-guidelines once you have confirmed they are the
# only remaining failures; left off by default so nothing is hidden silently.
_GUIDELINE_PATTERNS = [
    re.compile(r"^MDN\.17", re.IGNORECASE),
    re.compile(r"^MDP\.3$", re.IGNORECASE),
    re.compile(r"^MDP\.17a", re.IGNORECASE),
    re.compile(r"recommend", re.IGNORECASE),
    re.compile(r"guideline", re.IGNORECASE),
]


def _is_ignored_rule(name: str, desc: str, extra_patterns: Optional[List[Any]] = None) -> bool:
    """True if this rule is not a functional defect for a standalone cell.

    Patterns are tested against the rule NAME on its own and against
    "<name>  <desc>". Testing the name separately matters for anchored
    patterns: r"^m\\d+\\.4$" can never match the concatenated string, so in the
    original implementation the sky130 metal min-area names were silently
    never ignored.
    """
    name = (name or "").strip()
    text = f"{name}  {desc or ''}"
    patterns = list(_IGNORE_PATTERNS)
    if extra_patterns:
        patterns.extend(extra_patterns)
    return any(p.search(name) or p.search(text) for p in patterns)


def _count_lyrdb_violations(report: Path, extra_ignores: Optional[List[Any]] = None) -> dict:
    """Count DRC violations in a klayout lyrdb. Returns a dict with:
        total, effective (excluding density/min-area), ignored, by_rule, ignored_by_rule.
    On failure to read or parse the report returns {'total': -1, ...} plus a
    'parse_error' key, so a truncated/garbled lyrdb reads as an error rather
    than as a clean pass.
    """
    empty = {"total": -1, "effective": -1, "ignored": 0, "by_rule": {}, "ignored_by_rule": {}}
    if not report.exists():
        return dict(empty)
    try:
        tree = ET.parse(report)
    except ET.ParseError as exc:
        out = dict(empty)
        out["parse_error"] = f"{exc}"
        return out
    root = tree.getroot()
    cats: dict[str, str] = {}
    items = None
    for child in root:
        tag = child.tag.split("}")[-1]
        if tag == "items":
            items = child
        elif tag == "categories":
            for cat in child:
                cname = cdesc = ""
                for sub in cat:
                    stag = sub.tag.split("}")[-1]
                    if stag == "name":
                        cname = (sub.text or "").strip()
                    elif stag == "description":
                        cdesc = (sub.text or "").strip()
                if cname:
                    cats[cname] = cdesc
    by_rule: dict[str, int] = {}
    ignored_by_rule: dict[str, int] = {}
    if items is not None:
        for item in items:
            cat = ""
            for sub in item:
                if sub.tag.split("}")[-1] == "category":
                    cat = (sub.text or "").strip().strip("'")
                    break
            desc = cats.get(cat, "")
            if _is_ignored_rule(cat, desc, extra_ignores):
                ignored_by_rule[cat] = ignored_by_rule.get(cat, 0) + 1
            else:
                by_rule[cat] = by_rule.get(cat, 0) + 1
    total = sum(by_rule.values()) + sum(ignored_by_rule.values())
    return {
        "total": total,
        "effective": sum(by_rule.values()),
        "ignored": sum(ignored_by_rule.values()),
        "by_rule": by_rule,
        "ignored_by_rule": ignored_by_rule,
    }


def _run_klayout(
    deck: Path,
    gds: Path,
    report: Path,
    pdk_name: str = "sky130",
    variant: str = "D",
    topcell: Optional[str] = None,
    threads: int = 2,
    offgrid: bool = True,
    timeout: int = 1800,
) -> subprocess.CompletedProcess:
    """Invoke the klayout DRC deck in batch mode.

    For gf180 we must supply the metal-stack globals explicitly: the deck's
    own fallbacks are 9K / 6LM / MIM "Nan", which skip every MIM capacitor
    rule and select a via5/metaltop stack this PDK's layer map does not use.

    ``threads`` defaults to 2 rather than the deck's internal 16: the caller
    already runs cells in parallel via ProcessPoolExecutor, and 16 threads per
    cell oversubscribes a 2-4 core CI runner badly enough to trip the OOM
    killer (which surfaces as "report file not produced").
    """
    cmd = [
        "klayout",
        "-b",
        "-r", str(deck),
        "-rd", f"input={gds}",
        "-rd", f"report={report}",
    ]
    if pdk_name == "gf180":
        metal_top, metal_level, mim_option = GF180_VARIANTS[variant]
        cmd += [
            "-rd", f"metal_top={metal_top}",
            "-rd", f"metal_level={metal_level}",
            "-rd", f"mim_option={mim_option}",
            "-rd", "run_mode=flat",
            "-rd", f"thr={threads}",
            "-rd", f"offgrid={'true' if offgrid else 'false'}",
        ]
        if topcell:
            # Without this the deck calls source($input) and lets klayout guess
            # the top cell.
            cmd += ["-rd", f"topcell={topcell}"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


_MAGIC_RULE_RE = re.compile(r"^[A-Za-z]")
_MAGIC_COORD_RE = re.compile(r"^[0-9-]")


def _count_magic_violations(report: Path, extra_ignores: Optional[List[Any]] = None) -> dict:
    """Parse a magic DRC report (the format ``custom_drc_save_report`` writes
    in ``pdk.drc_magic``). Returns the same shape as ``_count_lyrdb_violations``
    so JUnit/summary code can stay agnostic.
    """
    if not report.exists():
        return {"total": -1, "effective": -1, "ignored": 0, "by_rule": {}, "ignored_by_rule": {}}
    text = report.read_text()
    by_rule: dict[str, int] = {}
    ignored_by_rule: dict[str, int] = {}
    current_rule = ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("---"):
            continue
        # Header line like "{cell} count: N" — ignore.
        if "count:" in s and ":" in s.split("count:", 1)[0]:
            continue
        if _MAGIC_RULE_RE.match(s):
            current_rule = s
            continue
        if _MAGIC_COORD_RE.match(s) and current_rule:
            if _is_ignored_rule(current_rule, current_rule, extra_ignores):
                ignored_by_rule[current_rule] = ignored_by_rule.get(current_rule, 0) + 1
            else:
                by_rule[current_rule] = by_rule.get(current_rule, 0) + 1
    return {
        "total": sum(by_rule.values()) + sum(ignored_by_rule.values()),
        "effective": sum(by_rule.values()),
        "ignored": sum(ignored_by_rule.values()),
        "by_rule": by_rule,
        "ignored_by_rule": ignored_by_rule,
    }


def _run_magic_drc(item: dict, pdk, comp_name: str, gds_path: Path, magic_dir: Path) -> dict:
    """Invoke ``pdk.drc_magic`` on the GDS produced by the build phase. Returns
    a result dict with the same shape as the klayout per-cell result.
    """
    name = item["name"]
    pdk_name = item["pdk"]
    out_dir = Path(item["out_dir"])
    extra_ignores = _GUIDELINE_PATTERNS if item.get("ignore_guidelines") else None
    res: Dict[str, Any] = {"cell": name, "pdk": pdk_name, "engine": "magic", "status": "skip"}
    rpt_dir = magic_dir / "drc" / comp_name
    rpt_path = rpt_dir / f"{comp_name}.rpt"
    try:
        print(f"[MAGIC]{name}", flush=True)
        pdk.drc_magic(
            layout=str(gds_path),
            design_name=comp_name,
            output_file=str(magic_dir),
        )
    except Exception as exc:
        res.update({"status": "error", "message": f"magic drc failed: {exc}", "trace": traceback.format_exc()})
        print(f"[ERROR] {name}: magic drc failed: {exc}", flush=True)
        return res
    viols = _count_magic_violations(rpt_path, extra_ignores)
    effective = viols["effective"]
    res.update({
        "violations": viols,
        "report": str(rpt_path.relative_to(out_dir)) if rpt_path.exists() else None,
    })
    if effective < 0:
        res["status"] = "error"
        res["message"] = "magic report not produced"
    elif effective == 0:
        res["status"] = "pass"
        if viols["ignored"]:
            res["message"] = f"clean (ignored {viols['ignored']} density/area)"
    else:
        res["status"] = "fail"
        top = ", ".join(f"{r}:{n}" for r, n in sorted(viols["by_rule"].items(), key=lambda kv: -kv[1])[:3])
        res["message"] = f"{effective} magic violation(s) [{top}]"
    print(f"[MAGIC:{res['status'].upper()}] {name}: {res.get('message', 'clean')}", flush=True)
    return res


def _run_one_cell(item: dict) -> dict:
    """Build a single cell, write GDS+netlist, run klayout DRC and (optionally)
    magic DRC. Designed to be invoked via ProcessPoolExecutor so each cell
    runs on its own core.

    item keys: name, pdk, deck, kwargs, gds_path, rpt_path, netlist_path,
               out_dir, engines (list[str]), magic_dir (str|None),
               variant, threads, offgrid, ignore_guidelines
    """
    name = item["name"]
    pdk_name = item["pdk"]
    deck = Path(item["deck"])
    out_dir = Path(item["out_dir"])
    gds_path = Path(item["gds_path"])
    rpt_path = Path(item["rpt_path"])
    netlist_path = Path(item["netlist_path"])
    extra_ignores = _GUIDELINE_PATTERNS if item.get("ignore_guidelines") else None
    result: Dict[str, Any] = {"cell": name, "pdk": pdk_name, "status": "skip"}
    try:
        print(f"[BUILD] {name}", flush=True)
        pdk = _resolve_pdk(pdk_name)
        builder = _resolve_builder(_CELL_BUILDERS[name])
        comp = builder(pdk, **item["kwargs"])
        if not hasattr(comp, "write_gds"):
            from gdsfactory.component import Component as _Component
            wrapper = _Component(name)
            wrapper.add(comp)
            wrapper.add_ports(comp.get_ports_list())
            if hasattr(comp, "parent") and "netlist" in getattr(comp.parent, "info", {}):
                wrapper.info["netlist"] = comp.parent.info["netlist"]
            comp = wrapper
        comp.name = name
        comp.write_gds(str(gds_path))
        netlist_info = comp.info.get("netlist") if hasattr(comp, "info") else None
        if netlist_info is not None:
            if hasattr(netlist_info, "generate_netlist"):
                netlist_text = netlist_info.generate_netlist()
            else:
                netlist_text = str(netlist_info)
            netlist_path.write_text(netlist_text)
    except Exception as exc:
        result.update({"status": "error", "message": f"build failed: {exc}", "trace": traceback.format_exc()})
        print(f"[ERROR] {name}: build failed\n{result['trace']}", flush=True)
        return result

    engines = item.get("engines") or ["klayout"]
    engine_results: Dict[str, Dict[str, Any]] = {}

    if "klayout" in engines:
        try:
            print(f"[DRC]  {name}", flush=True)
            proc = _run_klayout(
                deck, gds_path, rpt_path,
                pdk_name=pdk_name,
                variant=item.get("variant", "D"),
                topcell=name,
                threads=item.get("threads", 2),
                offgrid=item.get("offgrid", True),
            )
            viols = _count_lyrdb_violations(rpt_path, extra_ignores)
            effective = viols["effective"]
            klayout_res: Dict[str, Any] = {
                "engine": "klayout",
                "violations": viols,
                "report": str(rpt_path.relative_to(out_dir)),
                "klayout_returncode": proc.returncode,
                "klayout_stderr_tail": (proc.stderr or "")[-400:],
                # The gf180 deck logs its resolved switches (METAL_TOP,
                # METAL_STACK, MIM Option, Offgrid) on stdout -- keep the tail
                # so a config mismatch is visible in the artifact.
                "klayout_stdout_tail": (proc.stdout or "")[-800:],
            }
            if proc.returncode != 0:
                klayout_res["status"] = "error"
                klayout_res["message"] = f"klayout exited {proc.returncode}"
            elif viols.get("parse_error"):
                klayout_res["status"] = "error"
                klayout_res["message"] = f"lyrdb parse error: {viols['parse_error']}"
            elif effective < 0:
                klayout_res["status"] = "error"
                klayout_res["message"] = "report file not produced"
            elif effective == 0:
                klayout_res["status"] = "pass"
                if viols["ignored"]:
                    klayout_res["message"] = f"clean (ignored {viols['ignored']} density/area/latch-up)"
            else:
                klayout_res["status"] = "fail"
                top = ", ".join(f"{r}:{n}" for r, n in sorted(viols["by_rule"].items(), key=lambda kv: -kv[1])[:3])
                klayout_res["message"] = f"{effective} DRC violation(s) [{top}]"
        except subprocess.TimeoutExpired:
            klayout_res = {"engine": "klayout", "status": "error", "message": "klayout timeout"}
        engine_results["klayout"] = klayout_res
        print(f"[KLAYOUT:{klayout_res['status'].upper()}] {name}: {klayout_res.get('message', 'clean')}", flush=True)

    if "magic" in engines:
        magic_dir = Path(item["magic_dir"]) if item.get("magic_dir") else (out_dir / "magic")
        magic_dir.mkdir(parents=True, exist_ok=True)
        pdk_obj = _resolve_pdk(pdk_name)
        engine_results["magic"] = _run_magic_drc(item, pdk_obj, name, gds_path, magic_dir)

    # Merge into the cell-level result. Cell is "pass" iff every engine passes;
    # if any engine errors, the cell is "error"; otherwise "fail".
    statuses = [er["status"] for er in engine_results.values()]
    if "error" in statuses:
        result["status"] = "error"
    elif "fail" in statuses:
        result["status"] = "fail"
    else:
        result["status"] = "pass"
    result["engines"] = engine_results
    result["gds"] = str(gds_path.relative_to(out_dir))
    # Pick the most informative engine message (failing engine first, then passing).
    msg_engine = next((e for e, er in engine_results.items() if er["status"] in ("fail", "error")), None) \
        or next((e for e, er in engine_results.items() if er["status"] == "pass"), None)
    if msg_engine:
        result["message"] = f"{msg_engine}: {engine_results[msg_engine].get('message', engine_results[msg_engine]['status'])}"
    print(f"[{result['status'].upper()}] {name}: {result.get('message', 'clean')}", flush=True)
    return result


def _write_junit(results: List[dict], pdk: str, out: Path) -> None:
    suite = ET.Element(
        "testsuite",
        attrib={
            "name": f"glayout-drc-{pdk}",
            "tests": str(len(results)),
            "failures": str(sum(1 for r in results if r["status"] == "fail")),
            "errors": str(sum(1 for r in results if r["status"] == "error")),
            "skipped": str(sum(1 for r in results if r["status"] == "skip")),
        },
    )
    for r in results:
        case = ET.SubElement(
            suite, "testcase",
            attrib={"classname": f"drc.{pdk}", "name": r["cell"]},
        )
        if r["status"] == "fail":
            ET.SubElement(case, "failure", attrib={"message": r.get("message", "DRC violations")}).text = json.dumps(r, indent=2)
        elif r["status"] == "error":
            ET.SubElement(case, "error", attrib={"message": r.get("message", "build/DRC error")}).text = json.dumps(r, indent=2)
        elif r["status"] == "skip":
            ET.SubElement(case, "skipped", attrib={"message": r.get("message", "skipped")})
    tree = ET.ElementTree(suite)
    tree.write(out, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdk", required=True, choices=["sky130", "gf180"])
    parser.add_argument("--out-dir", default="drc_results")
    parser.add_argument(
        "--cells",
        default=None,
        help="Comma-separated cell names; default runs every registered cell.",
    )
    parser.add_argument(
        "--deck",
        default=None,
        help="Path to a klayout DRC deck overriding the bundled one (e.g. a PDK-installed deck).",
    )
    parser.add_argument(
        "--params",
        default=None,
        help=f"Path to the cell parameter CSV (default: {DEFAULT_PARAM_DIR}/ci_drc_<pdk>.csv).",
    )
    parser.add_argument(
        "--jobs", "-j", type=int, default=max(1, (os.cpu_count() or 2) - 1),
        help="Worker processes for parallel build+DRC (default: cpu_count-1).",
    )
    parser.add_argument(
        "--engine",
        choices=["klayout", "magic", "both"],
        default="klayout",
        help="DRC engine(s) to run per cell. 'both' runs klayout and magic in sequence per worker.",
    )
    parser.add_argument(
        "--variant", default="D", choices=sorted(GF180_VARIANTS),
        help="gf180mcu metal-stack variant (ignored for sky130). D = 5LM/11K/MIM-B, "
             "matching --variant=D in tests/lvs/klayout_gf180.py.",
    )
    parser.add_argument(
        "--threads", type=int, default=2,
        help="Threads per klayout process for gf180 ($thr). Kept low because "
             "cells already run in parallel; the deck's own default is 16.",
    )
    parser.add_argument(
        "--no-offgrid", action="store_true",
        help="Disable the gf180 deck's OFFGRID/ACUTE geometry section ($offgrid=false). "
             "Useful while triaging; leave enabled in CI.",
    )
    parser.add_argument(
        "--ignore-guidelines", action="store_true",
        help="Also ignore rules the deck flags as recommendations/guidelines "
             "(MDN.17, MDP.3, MDP.17a, ...) which cannot be satisfied by a "
             "standalone cell with no surrounding guard ring.",
    )
    args = parser.parse_args()
    engines = ["klayout", "magic"] if args.engine == "both" else [args.engine]

    out_dir = Path(args.out_dir).resolve()
    gds_dir = out_dir / "gds"
    rpt_dir = out_dir / "reports"
    netlist_dir = out_dir / "netlists"
    magic_dir = out_dir / "magic" if "magic" in engines else None
    out_dir.mkdir(parents=True, exist_ok=True)
    gds_dir.mkdir(parents=True, exist_ok=True)
    rpt_dir.mkdir(parents=True, exist_ok=True)
    netlist_dir.mkdir(parents=True, exist_ok=True)
    if magic_dir is not None:
        magic_dir.mkdir(parents=True, exist_ok=True)

    deck = _drc_deck_for(args.pdk, args.deck)
    if not deck.exists():
        print(f"DRC deck missing: {deck}", file=sys.stderr)
        return 2

    pdk = _resolve_pdk(args.pdk)
    specs = _load_cell_specs(args.pdk, Path(args.params).resolve() if args.params else None)
    if args.cells:
        wanted = {c.strip() for c in args.cells.split(",") if c.strip()}
        missing = wanted - set(specs)
        if missing:
            print(f"warning: cells not in CSV: {sorted(missing)}", file=sys.stderr)
        specs = {n: s for n, s in specs.items() if n in wanted}

    if args.pdk == "gf180":
        mt, ml, mim = GF180_VARIANTS[args.variant]
        print(f"gf180 variant {args.variant}: metal_top={mt} metal_level={ml} "
              f"mim_option={mim} thr={args.threads} offgrid={not args.no_offgrid}")

    # Hand cell work to a process pool so build+klayout for different cells
    # run on different cores. Each worker imports glayout fresh; we pass the
    # cell name + kwargs over the wire and resolve the builder by name in the
    # worker (gdsfactory PDK state is per-process).
    from concurrent.futures import ProcessPoolExecutor, as_completed

    work_items = [
        {
            "name": name,
            "pdk": args.pdk,
            "deck": str(deck),
            "kwargs": spec.kwargs,
            "gds_path": str(gds_dir / f"{name}.gds"),
            "rpt_path": str(rpt_dir / f"{name}.lyrdb"),
            "netlist_path": str(netlist_dir / f"{name}.spice"),
            "out_dir": str(out_dir),
            "engines": engines,
            "magic_dir": str(magic_dir) if magic_dir else None,
            "variant": args.variant,
            "threads": args.threads,
            "offgrid": not args.no_offgrid,
            "ignore_guidelines": args.ignore_guidelines,
        }
        for name, spec in specs.items()
    ]
    jobs = max(1, min(args.jobs, len(work_items)))
    print(f"running {len(work_items)} cells with {jobs} worker(s)")
    results: List[dict] = []
    if jobs == 1:
        for item in work_items:
            results.append(_run_one_cell(item))
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_run_one_cell, item): item["name"] for item in work_items}
            for fut in as_completed(futures):
                results.append(fut.result())
    # Stable order so summary/junit are deterministic regardless of completion order.
    name_order = {n: i for i, n in enumerate(specs.keys())}
    results.sort(key=lambda r: name_order.get(r["cell"], len(name_order)))

    summary = {
        "pdk": args.pdk,
        "variant": args.variant if args.pdk == "gf180" else None,
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

    # Aggregate rule histogram: the single most useful thing when triaging a
    # red run, and cheap to print.
    agg: Dict[str, int] = {}
    for r in results:
        for er in (r.get("engines") or {}).values():
            for rule, n in (er.get("violations", {}).get("by_rule") or {}).items():
                agg[rule] = agg.get(rule, 0) + n
    if agg:
        print("\nviolations by rule:")
        for rule, n in sorted(agg.items(), key=lambda kv: -kv[1]):
            print(f"  {rule:<24} {n}")

    return 0 if summary["fail"] == 0 and summary["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
