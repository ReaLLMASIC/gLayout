"""Sphinx directives that render verification results from the runners' output.

The tables in this documentation are generated, not hand-written. They read the
``summary.json`` files that ``tests/drc/run_cell_drc.py``,
``tests/lvs/run_cell_lvs.py`` and ``tests/sim/run_cell_sim.py`` already emit, so
the docs cannot drift from the run that produced them and the runners need no
changes to feed them.

Expected layout, relative to ``glayout_results_root``::

    drc_results/<pdk>/summary.json
    lvs_results/<pdk>/summary.json
    sim_results/<pdk>/summary.json

Schema, as written by the runners::

    {
      "pdk": "sky130",
      "total": 9, "pass": 8, "fail": 1, "error": 0, "skip": 0,
      "results": [
        {
          "cell": "diff_pair",
          "status": "pass",              # pass | fail | error | skip
          "message": "sim passed",
          "summary": {                   # sim only
            "conclusion": "sim passed",
            "measures": {"tphl": 1.2e-9},
            "rows": [
              {"name": "tphl", "value": 1.2e-9,
               "min": null, "max": 2e-9, "verdict": "PASS"}
            ]
          }
        }
      ]
    }

A no-op run writes ``{"pdk": ..., "total": 0, "note": ...}`` with no ``results``
key; that is rendered as "nothing to run" rather than treated as an error.

Directives
----------
``.. verification-matrix::``   one row per cell, one column per stage per PDK
``.. ngspice-detail::``        one row per measurement (``:pdk:`` option)
``.. ci-summary::``            per-stage pass/fail counts
``.. results-provenance::``    where the data came from and how old it is
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.parsers.rst import Directive, directives
from sphinx.errors import ExtensionError
from sphinx.util import logging

logger = logging.getLogger(__name__)

__version__ = "2.0.0"

STAGES = ("drc", "lvs", "sim")
STAGE_LABELS = {"drc": "DRC", "lvs": "LVS", "sim": "ngspice"}

# Runner status token -> (symbol, label, CSS class)
STATUS_MAP: dict[str, tuple[str, str, str]] = {
    "pass": ("\u2705", "Pass", "gl-pass"),
    "fail": ("\u274c", "Fail", "gl-fail"),
    "error": ("\U0001f4a5", "Error", "gl-fail"),
    "skip": ("\u23ed\ufe0f", "Skipped", "gl-skip"),
    "missing": ("\u2014", "Not run", "gl-skip"),
}

# Per-measurement verdicts, as emitted by _parse_sim_log.
VERDICT_MAP: dict[str, tuple[str, str, str]] = {
    "PASS": ("\u2705", "PASS", "gl-pass"),
    "FAIL": ("\u274c", "FAIL", "gl-fail"),
    "MISSING": ("\u26a0\ufe0f", "MISSING", "gl-warn"),
    "n/a": ("\u2014", "no band", "gl-skip"),
}


def fmt_eng(x: Any) -> str:
    """Compact engineering notation, matching run_cell_sim.py's ``_fmt_eng``.

    Kept deliberately identical so a number shown in the docs reads the same as
    in the console log and the JUnit report.
    """
    if x is None:
        return "\u2014"
    if not isinstance(x, (int, float)):
        return str(x)
    if x == 0:
        return "0"
    ax = abs(x)
    for suffix, scale in (
        ("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0),
        ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12),
    ):
        if ax >= scale:
            return f"{x / scale:.4g}{suffix}"
    return f"{x:.4g}"


def fmt_band(row: dict) -> str:
    """Render a measurement's limits the way the runner's own report does."""
    lo, hi = row.get("min"), row.get("max")
    if lo is None and hi is None:
        return "\u2014"
    return f"{fmt_eng(lo)} \u2026 {fmt_eng(hi)}"


class ResultsStore:
    """Loads and caches the per-stage, per-PDK summary files."""

    def __init__(self, root: Path, pdks: list[str], strict: bool):
        self.root = root
        self.pdks = pdks
        self.strict = strict
        self.data: dict[tuple[str, str], dict] = {}
        self.paths: dict[tuple[str, str], Path] = {}
        self.newest: float | None = None
        self._load()

    def _load(self) -> None:
        found = 0
        for stage in STAGES:
            for pdk in self.pdks:
                path = self.root / f"{stage}_results" / pdk / "summary.json"
                if not path.exists():
                    continue
                try:
                    with path.open(encoding="utf-8") as handle:
                        self.data[(stage, pdk)] = json.load(handle)
                except (json.JSONDecodeError, OSError) as exc:
                    message = f"could not read {path}: {exc}"
                    if self.strict:
                        raise ExtensionError(message) from exc
                    logger.warning(message)
                    continue
                self.paths[(stage, pdk)] = path
                mtime = path.stat().st_mtime
                self.newest = mtime if self.newest is None else max(self.newest, mtime)
                found += 1

        if found == 0:
            message = (
                f"no <stage>_results/<pdk>/summary.json found under {self.root}; "
                "run the DRC/LVS/sim workflows, or point glayout_results_root at "
                "a directory of downloaded artifacts"
            )
            if self.strict:
                raise ExtensionError(f"{message} (glayout_results_strict is enabled)")
            logger.warning(message)

    @property
    def empty(self) -> bool:
        return not self.data

    def results(self, stage: str, pdk: str) -> list[dict]:
        """Per-cell records for one stage and PDK; empty when nothing ran."""
        return (self.data.get((stage, pdk)) or {}).get("results") or []

    def by_cell(self, stage: str, pdk: str) -> dict[str, dict]:
        return {r.get("cell"): r for r in self.results(stage, pdk) if r.get("cell")}

    def cells(self) -> list[str]:
        """Every cell name seen in any summary."""
        seen: set[str] = set()
        for stage in STAGES:
            for pdk in self.pdks:
                for record in self.results(stage, pdk):
                    name = record.get("cell")
                    if name:
                        seen.add(name)
        return sorted(seen)

    def ran(self, stage: str, pdk: str) -> bool:
        return (stage, pdk) in self.data

    def counts(self, stage: str, pdk: str) -> dict | None:
        return self.data.get((stage, pdk))


def get_store(env) -> ResultsStore:
    root = Path(env.config.glayout_results_root)
    if not root.is_absolute():
        root = (Path(env.srcdir) / root).resolve()
    key = (str(root), tuple(env.config.glayout_pdks),
           env.config.glayout_results_strict)
    if getattr(env, "_glayout_store_key", None) == key:
        return env._glayout_store
    store = ResultsStore(root, list(env.config.glayout_pdks),
                         env.config.glayout_results_strict)
    env._glayout_store = store
    env._glayout_store_key = key
    return store


def status_node(token: str) -> nodes.paragraph:
    symbol, label, css = STATUS_MAP.get(token, STATUS_MAP["missing"])
    para = nodes.paragraph()
    para += nodes.inline("", f"{symbol} {label}", classes=[css])
    return para


def text_cell(text: str, literal: bool = False) -> nodes.paragraph:
    para = nodes.paragraph()
    if literal:
        para += nodes.literal(text=text)
    else:
        para += nodes.Text(text)
    return para


def build_table(headers: list[str], rows: list[list[nodes.Node]],
                widths: list[int] | None = None,
                classes: list[str] | None = None) -> nodes.table:
    ncols = len(headers)
    widths = widths or [100 // ncols] * ncols

    table = nodes.table(classes=classes or [])
    table["align"] = "left"
    group = nodes.tgroup(cols=ncols)
    table += group
    for width in widths:
        group += nodes.colspec(colwidth=width)

    head = nodes.thead()
    group += head
    header_row = nodes.row()
    head += header_row
    for text in headers:
        entry = nodes.entry()
        entry += nodes.paragraph(text=text)
        header_row += entry

    body = nodes.tbody()
    group += body
    for cells in rows:
        row = nodes.row()
        body += row
        for cell in cells:
            entry = nodes.entry()
            entry += cell
            row += entry
    return table


def unavailable(what: str) -> list[nodes.Node]:
    admonition = nodes.admonition(classes=["warning"])
    admonition += nodes.title("", "Results unavailable")
    admonition += nodes.paragraph(
        text=(
            f"No runner output was available when these docs were built, so the "
            f"{what} could not be rendered. Run the verification flow locally, or "
            f"see the live dashboard for current numbers."
        )
    )
    return [admonition]


class ResultsDirective(Directive):
    has_content = False
    option_spec = {"class": directives.class_option}

    @property
    def env(self):
        return self.state.document.settings.env

    @property
    def store(self) -> ResultsStore:
        return get_store(self.env)


class VerificationMatrix(ResultsDirective):
    """Per-cell DRC / LVS / ngspice status across PDKs."""

    def run(self):
        store = self.store
        if store.empty:
            return unavailable("verification matrix")

        # Only show a column for a stage/PDK combination that actually ran, so
        # the matrix does not imply gf180 ngspice coverage that does not exist.
        columns = [
            (stage, pdk)
            for pdk in store.pdks
            for stage in STAGES
            if store.ran(stage, pdk)
        ]
        if not columns:
            return unavailable("verification matrix")

        headers = ["Cell"] + [f"{STAGE_LABELS[s]} {p}" for s, p in columns]
        lookup = {(s, p): store.by_cell(s, p) for s, p in columns}

        rows = []
        for cell in store.cells():
            row: list[nodes.Node] = [text_cell(cell, literal=True)]
            for stage, pdk in columns:
                record = lookup[(stage, pdk)].get(cell)
                row.append(
                    status_node(record.get("status", "missing") if record else "missing")
                )
            rows.append(row)

        widths = [26] + [74 // len(columns)] * len(columns)
        return [build_table(headers, rows, widths, classes=["gl-matrix"])]


class NgspiceDetail(ResultsDirective):
    """Per-measurement ngspice results for one PDK."""

    option_spec = {
        **ResultsDirective.option_spec,
        "pdk": directives.unchanged,
        "failures-only": directives.flag,
    }

    def run(self):
        store = self.store
        pdk = self.options.get("pdk") or (store.pdks[0] if store.pdks else "sky130")

        if not store.ran("sim", pdk):
            return [nodes.paragraph(
                text=f"ngspice regression has no recorded run for {pdk}."
            )]

        failures_only = "failures-only" in self.options
        headers = ["Cell", "Measurement", "Value", "Limits", "Result"]
        rows = []

        for record in store.results("sim", pdk):
            cell = record.get("cell", "\u2014")
            measurements = (record.get("summary") or {}).get("rows") or []

            if not measurements:
                # A cell that errored before ngspice produced any measurement
                # still gets a line, so this table and the matrix agree on scope.
                if record.get("status") in ("error", "fail"):
                    symbol, _, css = STATUS_MAP.get(record["status"],
                                                    STATUS_MAP["missing"])
                    note = nodes.paragraph()
                    note += nodes.inline(
                        "", f"{symbol} {record.get('message', '')}"[:80],
                        classes=[css],
                    )
                    rows.append([
                        text_cell(cell, literal=True), text_cell("\u2014"),
                        text_cell("\u2014"), text_cell("\u2014"), note,
                    ])
                continue

            for measurement in measurements:
                verdict = measurement.get("verdict", "n/a")
                if failures_only and verdict not in ("FAIL", "MISSING"):
                    continue
                symbol, label, css = VERDICT_MAP.get(verdict, VERDICT_MAP["n/a"])
                verdict_cell = nodes.paragraph()
                verdict_cell += nodes.inline("", f"{symbol} {label}", classes=[css])
                rows.append([
                    text_cell(cell, literal=True),
                    text_cell(measurement.get("name", "\u2014"), literal=True),
                    text_cell(fmt_eng(measurement.get("value"))),
                    text_cell(fmt_band(measurement)),
                    verdict_cell,
                ])

        if not rows:
            return [nodes.paragraph(
                text="No failing measurements." if failures_only
                else "No measurements were captured."
            )]

        return [build_table(headers, rows, [20, 22, 16, 24, 18],
                            classes=["gl-detail"])]


class CISummary(ResultsDirective):
    """Per-stage pass counts for each PDK."""

    def run(self):
        store = self.store
        if store.empty:
            return unavailable("run summary")

        headers = ["Stage"] + list(store.pdks)
        rows = []
        for stage in STAGES:
            if not any(store.ran(stage, pdk) for pdk in store.pdks):
                continue
            row: list[nodes.Node] = [text_cell(STAGE_LABELS[stage])]
            for pdk in store.pdks:
                counts = store.counts(stage, pdk)
                if counts is None:
                    row.append(status_node("missing"))
                    continue

                total = counts.get("total", 0)
                if total == 0:
                    # The runners write a no-op summary with a note rather than
                    # failing when nothing is wired up yet.
                    cell = nodes.paragraph()
                    cell += nodes.inline("", "\u2014 nothing to run",
                                         classes=["gl-skip"])
                    row.append(cell)
                    continue

                passed = counts.get("pass", 0)
                failed = counts.get("fail", 0) + counts.get("error", 0)
                css = "gl-fail" if failed else "gl-pass"
                symbol = "\u274c" if failed else "\u2705"
                cell = nodes.paragraph()
                cell += nodes.inline("", f"{symbol} {passed}/{total}", classes=[css])
                row.append(cell)
            rows.append(row)

        widths = [30] + [70 // max(1, len(store.pdks))] * len(store.pdks)
        return [build_table(headers, rows, widths, classes=["gl-summary"])]


class ResultsProvenance(ResultsDirective):
    """Where the displayed data came from, and how old it is."""

    def run(self):
        store = self.store
        if store.empty:
            return []

        parts: list[str] = []
        commit = os.environ.get("GLAYOUT_RUN_COMMIT")
        if commit:
            parts.append(f"commit {commit[:7]}")
        if store.newest:
            stamp = datetime.fromtimestamp(store.newest, tz=timezone.utc)
            parts.append(f"results written {stamp:%Y-%m-%d %H:%M UTC}")
        parts.append(
            "from " + ", ".join(sorted(
                f"{STAGE_LABELS[s]} {p}" for (s, p) in store.data
            ))
        )

        para = nodes.paragraph(classes=["gl-provenance"])
        run_url = os.environ.get("GLAYOUT_RUN_URL")
        text = " \u00b7 ".join(parts)
        if run_url:
            para += nodes.Text(text + " \u00b7 ")
            para += nodes.reference("", "workflow run", refuri=run_url)
        else:
            para += nodes.Text(text)
        return [para]


def setup(app):
    app.add_config_value("glayout_results_root", "data/sample", "env")
    app.add_config_value("glayout_pdks", ["sky130", "gf180"], "env")
    app.add_config_value("glayout_results_strict", False, "env")

    app.add_directive("verification-matrix", VerificationMatrix)
    app.add_directive("ngspice-detail", NgspiceDetail)
    app.add_directive("ci-summary", CISummary)
    app.add_directive("results-provenance", ResultsProvenance)

    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
