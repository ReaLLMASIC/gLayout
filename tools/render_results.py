#!/usr/bin/env python3
"""Render verification tables into marker-delimited blocks in Markdown files.

The Sphinx site generates its tables directly from the runners' ``summary.json``
via ``sphinx/_ext/glayout_results.py``. Plain Markdown files such as
``README.md`` cannot run directives, so this script writes Markdown tables into
comment-delimited blocks instead:

    <!-- BEGIN: VERIFICATION_MATRIX (auto-generated - do not edit by hand) -->
    ...
    <!-- END: VERIFICATION_MATRIX -->

Only the text between a matching pair is replaced, so surrounding prose is
never touched.

Reads the same layout the docs do, relative to --results-root:

    drc_results/<pdk>/summary.json
    lvs_results/<pdk>/summary.json
    sim_results/<pdk>/summary.json

Usage
-----
    python tools/render_results.py --results-root . --target README.md

    # verify a target is current without writing (exit 1 if stale)
    python tools/render_results.py --results-root . --target README.md --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

STAGES = ("drc", "lvs", "sim")
STAGE_LABELS = {"drc": "DRC", "lvs": "LVS", "sim": "ngspice"}

STATUS_MAP: dict[str, str] = {
    "pass": "\u2705 Pass",
    "fail": "\u274c Fail",
    "error": "\U0001f4a5 Error",
    "skip": "\u23ed\ufe0f Skipped",
    "missing": "\u2014 Not run",
}

VERDICT_MAP: dict[str, str] = {
    "PASS": "\u2705",
    "FAIL": "\u274c",
    "MISSING": "\u26a0\ufe0f",
    "n/a": "\u2014",
}


def fmt_eng(x: Any) -> str:
    """Engineering notation, matching run_cell_sim.py's _fmt_eng."""
    if x is None:
        return "\u2014"
    if not isinstance(x, (int, float)):
        return str(x)
    if x == 0:
        return "0"
    ax = abs(x)
    for suffix, scale in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0),
                          ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if ax >= scale:
            return f"{x / scale:.4g}{suffix}"
    return f"{x:.4g}"


def fmt_band(row: dict) -> str:
    lo, hi = row.get("min"), row.get("max")
    if lo is None and hi is None:
        return "\u2014"
    return f"{fmt_eng(lo)} \u2026 {fmt_eng(hi)}"


def load(root: Path, pdks: list[str]) -> dict[tuple[str, str], dict]:
    store: dict[tuple[str, str], dict] = {}
    for stage in STAGES:
        for pdk in pdks:
            path = root / f"{stage}_results" / pdk / "summary.json"
            if not path.exists():
                continue
            try:
                store[(stage, pdk)] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"warning: {path}: {exc}", file=sys.stderr)
    return store


def cells_in(store: dict) -> list[str]:
    seen: set[str] = set()
    for data in store.values():
        for record in data.get("results") or []:
            if record.get("cell"):
                seen.add(record["cell"])
    return sorted(seen)


def render_matrix(store: dict, pdks: list[str]) -> str:
    columns = [(s, p) for p in pdks for s in STAGES if (s, p) in store]
    if not columns:
        return "_No runner output available._"

    lookup = {
        key: {r.get("cell"): r for r in (store[key].get("results") or [])}
        for key in columns
    }

    header = "| Cell | " + " | ".join(
        f"{STAGE_LABELS[s]}<br/>{p}" for s, p in columns
    ) + " |"
    sep = "|------|" + "|".join([":---:"] * len(columns)) + "|"

    lines = [header, sep]
    for cell in cells_in(store):
        row = [f"`{cell}`"]
        for key in columns:
            record = lookup[key].get(cell)
            row.append(STATUS_MAP.get(
                record.get("status", "missing") if record else "missing",
                STATUS_MAP["missing"],
            ))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_detail(store: dict, pdk: str) -> str:
    data = store.get(("sim", pdk))
    if not data:
        return f"_No ngspice run recorded for {pdk}._"

    lines = [
        "| Cell | Measurement | Value | Limits | Result |",
        "|------|-------------|-------|--------|--------|",
    ]
    for record in data.get("results") or []:
        cell = record.get("cell", "\u2014")
        rows = (record.get("summary") or {}).get("rows") or []
        if not rows:
            if record.get("status") in ("fail", "error"):
                message = (record.get("message") or "")[:70]
                lines.append(
                    f"| `{cell}` | \u2014 | \u2014 | \u2014 | "
                    f"{STATUS_MAP.get(record['status'], '')} {message} |"
                )
            continue
        for measurement in rows:
            lines.append(
                f"| `{cell}` | `{measurement.get('name', '')}` | "
                f"{fmt_eng(measurement.get('value'))} | {fmt_band(measurement)} | "
                f"{VERDICT_MAP.get(measurement.get('verdict', 'n/a'), '')} "
                f"{measurement.get('verdict', '')} |"
            )
    if len(lines) == 2:
        return "_No measurements captured._"
    return "\n".join(lines)


def render_summary(store: dict, pdks: list[str]) -> str:
    lines = ["| Stage | " + " | ".join(pdks) + " |",
             "|-------|" + "|".join(["---"] * len(pdks)) + "|"]
    any_row = False
    for stage in STAGES:
        if not any((stage, p) in store for p in pdks):
            continue
        any_row = True
        row = [STAGE_LABELS[stage]]
        for pdk in pdks:
            data = store.get((stage, pdk))
            if not data:
                row.append(STATUS_MAP["missing"])
                continue
            total = data.get("total", 0)
            if not total:
                row.append("\u2014 nothing to run")
                continue
            failed = data.get("fail", 0) + data.get("error", 0)
            symbol = "\u274c" if failed else "\u2705"
            row.append(f"{symbol} {data.get('pass', 0)}/{total}")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) if any_row else "_No runner output available._"


def replace_block(text: str, name: str, body: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"(<!--\s*BEGIN:\s*{re.escape(name)}\b.*?-->)(.*?)"
        rf"(<!--\s*END:\s*{re.escape(name)}\s*-->)",
        re.DOTALL,
    )
    if not pattern.search(text):
        return text, False
    return pattern.sub(lambda m: f"{m.group(1)}\n\n{body}\n\n{m.group(3)}", text), True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--results-root", type=Path, default=Path("."),
                        help="directory containing <stage>_results/<pdk>/summary.json")
    parser.add_argument("--pdks", default="sky130,gf180")
    parser.add_argument("--sim-pdk", default="sky130",
                        help="PDK whose measurements fill the detail table")
    parser.add_argument("--target", required=True, action="append", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if any target is stale")
    args = parser.parse_args(argv)

    pdks = [p.strip() for p in args.pdks.split(",") if p.strip()]
    store = load(args.results_root, pdks)
    if not store:
        print(f"error: no summary.json under {args.results_root}", file=sys.stderr)
        return 2

    renderers = {
        "VERIFICATION_MATRIX": lambda: render_matrix(store, pdks),
        "NGSPICE_RESULTS": lambda: render_detail(store, args.sim_pdk),
        "CI_SUMMARY": lambda: render_summary(store, pdks),
    }

    stale = False
    for target in args.target:
        if not target.exists():
            print(f"error: target not found: {target}", file=sys.stderr)
            return 2

        original = target.read_text(encoding="utf-8")
        updated = original
        found: list[str] = []
        for name, render in renderers.items():
            updated, ok = replace_block(updated, name, render())
            if ok:
                found.append(name)

        if not found:
            print(f"warning: no marker blocks in {target}", file=sys.stderr)
            continue
        if updated == original:
            print(f"{target}: up to date ({', '.join(found)})")
        elif args.check:
            print(f"{target}: STALE ({', '.join(found)})", file=sys.stderr)
            stale = True
        else:
            target.write_text(updated, encoding="utf-8")
            print(f"{target}: updated ({', '.join(found)})")

    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
