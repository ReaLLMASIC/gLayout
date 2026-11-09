"""Terminal process tables for the floorplanning framework.

Every significant call in the framework (finger-sequence search, row build,
block extraction, DRR padding, annealing, verification) records its stages in
a ``ProcessTable`` and prints it when the call finishes, so a run leaves a
readable trace of what was decided and why.

    with ProcessTable("Finger-sequence search") as pt:
        with pt.stage("Diffusion graph") as st:
            ...
            st.detail(f"{n} nets, lower bound {lb} breaks")
        pt.result("best", "AABBBBAA")

Data tables (e.g. a candidate ranking) go through ``print_table``.

Set ``GLAYOUT_TABLES=0`` to silence all tables, or ``GLAYOUT_TABLES_DEPTH=N``
to print only tables nested at most N calls deep (1 = top-level calls only;
a floorplan run nests block -> cell -> row -> search). Rendering uses ``rich``
when it is importable (it ships with gdsfactory) and falls back to ASCII.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Sequence

_STATUS_STYLE = {"ok": "green", "pass": "green", "warn": "yellow", "skip": "dim",
                 "fail": "red", "error": "bold red"}


_depth = 0   # how many ProcessTables are open around the current call


def tables_enabled(depth: int | None = None) -> bool:
    if os.environ.get("GLAYOUT_TABLES", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    limit = os.environ.get("GLAYOUT_TABLES_DEPTH", "").strip()
    depth = (_depth + 1) if depth is None else depth
    return not limit.isdigit() or depth <= int(limit)


def _console_width() -> int:
    if os.environ.get("COLUMNS", "").isdigit():
        return int(os.environ["COLUMNS"])
    # docker exec without -t is not a tty; rich would wrap at 80 columns
    return shutil.get_terminal_size((120, 24)).columns if sys.stdout.isatty() else 120


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def print_table(title: str, columns: Sequence[str], rows: Sequence[Sequence[Any]],
                caption: Optional[str] = None) -> None:
    """Print a plain data table (no stage timing)."""
    if not tables_enabled():
        return
    rows = [[_fmt(v) for v in row] for row in rows]
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        _print_ascii(title, list(columns), rows, caption)
        return
    table = Table(title=title, caption=caption, title_justify="left", caption_justify="left")
    for col in columns:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(*row)
    Console(width=_console_width(), highlight=False).print(table)


def _print_ascii(title: str, columns: list[str], rows: list[list[str]], caption: Optional[str]) -> None:
    widths = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c) for i, c in enumerate(columns)]
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [title, line, "| " + " | ".join(c.ljust(w) for c, w in zip(columns, widths)) + " |", line]
    out += ["| " + " | ".join(v.ljust(w) for v, w in zip(row, widths)) + " |" for row in rows]
    out.append(line)
    if caption:
        out.append(caption)
    print("\n".join(out), flush=True)


@dataclass
class _Stage:
    name: str
    status: str = "ok"
    seconds: float = 0.0
    text: str = ""

    def detail(self, text: str) -> None:
        self.text = text if not self.text else f"{self.text}; {text}"

    def warn(self, text: str) -> None:
        self.status = "warn"
        self.detail(text)

    def fail(self, text: str) -> None:
        self.status = "fail"
        self.detail(text)


class ProcessTable:
    """Collects the stages of one call and prints them as a table.

    Use as a context manager: the table prints on exit, including when the
    call raises, so a failure still shows which stage it died in.
    """

    def __init__(self, title: str, subtitle: str = ""):
        self.title = title
        self.subtitle = subtitle
        self.stages: list[_Stage] = []
        self.results: list[tuple[str, str]] = []
        self._t0 = time.perf_counter()
        self._printed = False
        self._level = _depth + 1

    @contextmanager
    def stage(self, name: str) -> Iterator[_Stage]:
        st = _Stage(name)
        self.stages.append(st)
        t = time.perf_counter()
        try:
            yield st
        except Exception as exc:
            st.status = "error"
            st.detail(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            st.seconds = time.perf_counter() - t

    def add(self, name: str, detail: str = "", status: str = "ok", seconds: float = 0.0) -> None:
        self.stages.append(_Stage(name, status, seconds, detail))

    def result(self, key: str, value: Any) -> None:
        self.results.append((key, _fmt(value)))

    @property
    def ok(self) -> bool:
        return all(s.status in ("ok", "pass", "skip", "warn") for s in self.stages)

    def print(self) -> None:
        if self._printed or not tables_enabled(self._level):
            return
        self._printed = True
        total = time.perf_counter() - self._t0
        title = f"{self.title} — {self.subtitle}" if self.subtitle else self.title
        rows = [(str(i + 1), s.name, s.status, f"{s.seconds * 1e3:.1f}", s.text)
                for i, s in enumerate(self.stages)]
        caption = "  ".join(f"{k}={v}" for k, v in self.results) or None
        try:
            from rich.console import Console
            from rich.table import Table
        except ImportError:
            _print_ascii(f"{title}  ({total:.2f}s)", ["#", "stage", "status", "ms", "detail"],
                         [list(r) for r in rows], caption)
            return
        table = Table(title=f"{title}  [dim]({total:.2f}s)[/dim]", title_justify="left",
                      caption=caption, caption_justify="left")
        table.add_column("#", justify="right", style="dim")
        table.add_column("stage", no_wrap=True)
        table.add_column("status", no_wrap=True)
        table.add_column("ms", justify="right")
        table.add_column("detail", overflow="fold")
        for idx, name, status, ms, text in rows:
            style = _STATUS_STYLE.get(status, "")
            table.add_row(idx, name, f"[{style}]{status}[/{style}]" if style else status, ms, text)
        Console(width=_console_width(), highlight=False).print(table)

    def __enter__(self) -> "ProcessTable":
        global _depth
        _depth += 1
        self._level = _depth
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        global _depth
        _depth -= 1
        self.print()
