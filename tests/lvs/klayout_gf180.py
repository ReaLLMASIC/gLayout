"""gf180 LVS via klayout's bundled gf180mcu deck.

magic+netgen on gf180 mis-extracts the substrate (NMOS bulks merge into
VDD via the n-well), so for gf180 we drive the official gf180mcu klayout
LVS deck instead. The deck lives inside the PDK install:

    $PDK_ROOT/ciel/gf180mcu/versions/<HASH>/gf180mcuD/libs.tech/klayout/tech/lvs/run_lvs.py

The version `<HASH>` is recorded in `$PDK_ROOT/ciel/gf180mcu/current`, so
we resolve the deck path through that pointer (no hard-coded version).

This module exposes one entry point, :func:`run_lvs_klayout_gf180`, that
mirrors `pdk.lvs_netgen`'s call signature so the CI harness in
`tests/lvs/run_cell_lvs.py` can dispatch by PDK without restructuring.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# Std-cell reference SPICE bundled with gf180_mapped. Included ONLY when the
# cell netlist actually references something defined in it -- see
# _needs_ref_spice for why an unconditional include is harmful.
_REF_SPICE = (
    Path(__file__).resolve().parents[2]
    / "src" / "glayout" / "pdk" / "gf180_mapped" / "gf180mcu_osu_sc_9T.spice"
)

# Device models klayout's gf180mcu deck classifies by SPICE prefix rather than
# by subckt lookup. Keep in sync with gf180_mapped_pdk.models.
_GF180_PRIMITIVE_FETS = ("nfet_03v3", "pfet_03v3")
_GF180_PRIMITIVE_CAPS = ("mimcap_1p0fF",)

# Numeric literal including scientific notation: 1, 1.5, .5, 1.5e-06.
_NUM = r"[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"

# Subckts defined in _REF_SPICE. If the cell netlist references none of them,
# including the file is pure risk rather than help:
#   * SLC defines X0 and X4 twice each -- malformed SPICE; klayout's reader
#     may abort, which takes the whole schematic netlist with it (0 devices on
#     the schematic side, every layout device unmatched).
#   * Every device in it is nmos_3p3 / pmos_3p3, which exist neither in this
#     PDK (nfet_03v3 / pfet_03v3) nor as subckts in the file, so it
#     contributes hundreds of unresolvable references.
#   * `.option scale=0.05u` appears ~40 times and is file-global in SPICE. If
#     klayout honours it, our own w=/l= values get rescaled by 20x and every
#     device fails on properties.
_REF_SPICE_SUBCKTS = re.compile(r"\b(gf180mcu_osu_sc_9T_\w+|dinv1|HEADER|SLC)\b")

# Instance-line prefixes worth scanning for a model token.
_INSTANCE_PREFIXES = "XxMmCcRrDdQqJjZz"


def _resolve_deck_dir(pdk_root: str) -> Path:
    """Resolve the gf180mcu klayout LVS deck directory from $PDK_ROOT.

    Reads `$PDK_ROOT/ciel/gf180mcu/current` to pick the version hash, then
    points at the variant-D (5LM, 11K top metal) klayout LVS folder.
    """
    pointer = Path(pdk_root) / "ciel" / "gf180mcu" / "current"
    if not pointer.is_file():
        raise FileNotFoundError(f"missing gf180mcu version pointer at {pointer}")
    version = pointer.read_text().strip()
    deck = (
        Path(pdk_root)
        / "ciel" / "gf180mcu" / "versions" / version
        / "gf180mcuD" / "libs.tech" / "klayout" / "tech" / "lvs"
    )
    if not (deck / "run_lvs.py").is_file():
        raise FileNotFoundError(f"missing run_lvs.py under {deck}")
    return deck


def _deck_python() -> str:
    """Interpreter to run the gf180mcu deck's run_lvs.py with.

    The caller runs inside glayout's CPython 3.10 venv, which has neither
    `docopt` nor the klayout Python bindings -- both imported at module scope
    in run_lvs.py, so a plain `python3` aborts before any LVS work happens.
    Prefer an explicit override, then the container interpreter.
    """
    for cand in (os.environ.get("LVS_DECK_PYTHON"), "/usr/bin/python3"):
        if cand and Path(cand).is_file():
            return cand
    return "python3"


def _deck_env() -> Dict[str, str]:
    """Environment for the deck subprocess.

    Drops VIRTUAL_ENV and the venv's bin from PATH so the image's own
    site-packages resolve. CI blanks PYTHONPATH (to keep the image's 3.12
    packages out of the 3.10 venv); IMAGE_PYTHONPATH carries the original
    value for exactly this purpose.
    """
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env["PYTHONPATH"] = os.environ.get("IMAGE_PYTHONPATH", "")
    venv_bin = str(Path(os.environ.get("GITHUB_WORKSPACE", "")) / ".venv" / "bin")
    env["PATH"] = ":".join(p for p in env.get("PATH", "").split(":") if p and p != venv_bin)
    return env


def _defined_subckts(text: str) -> Set[str]:
    return set(re.findall(r"^\.subckt\s+(\S+)", text, re.MULTILINE | re.IGNORECASE))


def _referenced_subckts(text: str, defined: Set[str]) -> Set[str]:
    """Names from `defined` that appear as a model token on an instance line."""
    referenced: Set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] not in _INSTANCE_PREFIXES:
            continue
        for tok in s.split()[1:]:
            if tok in defined:
                referenced.add(tok)
    return referenced


def _rename_top_subckt(cdl_text: str, cell: str) -> str:
    """Rename the schematic's top subckt to match the layout cell name.

    The top is the subckt that is never referenced as an instance model. Do
    NOT assume it is the last one defined: that silently renames a *leaf* if a
    generator ever emits top-down, after which --topcell=<cell> resolves to
    the wrong circuit and every net comes back unmatched.
    """
    defined = _defined_subckts(cdl_text)
    if not defined:
        return cdl_text
    referenced = _referenced_subckts(cdl_text, defined)
    tops = sorted(defined - referenced)
    if not tops:
        tops = sorted(defined)
        print(f"[LVS] {cell}: every subckt is referenced; falling back to {tops[-1]}", flush=True)
    elif len(tops) > 1:
        print(f"[LVS] {cell}: ambiguous top subckt {tops}; using {tops[-1]}", flush=True)
    sch_top = tops[-1]
    if sch_top != cell:
        cdl_text = re.sub(rf"\b{re.escape(sch_top)}\b", cell, cdl_text)
    return cdl_text


def _tag_geometry_units(cdl_text: str) -> str:
    """Append `u` to bare w=/l= values (the gf180mcu deck rejects unitless
    geometry parameters).

    Case-insensitive (glayout and the bundled reference spice disagree on
    case) and tolerant of scientific notation. Idempotent: the lookahead fails
    when a unit suffix is already present, so `w=1u` is left alone.
    """
    for key in ("w", "l"):
        cdl_text = re.sub(
            rf"(\b{key}=)({_NUM})(?=[\s,)]|$)",
            r"\1\2u",
            cdl_text,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    return cdl_text


def _rewrite_prefix_for_primitives(cdl_text: str) -> str:
    """Rewrite X-prefix instances of gf180 primitives to the prefix klayout's
    deck classifies on: M for the 4-terminal FETs, C for 2-terminal MIM caps.

    glayout's netlist generators emit X-prefix everywhere (sky130's
    magic+netgen tech setup expects X-instances of `sky130_fd_pr__nfet_01v8`
    and matches them via the netgen tech file). klayout's gf180mcu deck
    instead auto-promotes only M-prefix instances of nfet_03v3 / pfet_03v3 to
    MOS4 device classes; X-prefix instances have no `.subckt` body anywhere,
    so they are treated as unknown subckts, the schematic side ends up with 0
    transistors, and every layout fet becomes an unmatched device.

    `\\S*` before the model name tolerates a fully-qualified spelling
    (gf180mcu_fd_pr__nfet_03v3) as well as the bare one this PDK emits.
    Instances of real subckt wrappers (NMOS, PMOS, DIFF_PAIR, ...) are left as
    X -- those do have bodies.

    NOTE: the C-prefix rewrite for mimcap_1p0fF is inferred from the FET case.
    Verify it against the device-classification section of the PDK's .lvs
    files; if MIM caps are declared there as a subckt instead, set
    _GF180_PRIMITIVE_CAPS = () and make sure the cap body resolves some other
    way.
    """
    fet_alt = "|".join(re.escape(m) for m in _GF180_PRIMITIVE_FETS)
    cdl_text = re.sub(
        rf"^X(\S+)((?:\s+\S+){{4}}\s+\S*(?:{fet_alt})\b)",
        r"M\1\2",
        cdl_text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    cap_alt = "|".join(re.escape(m) for m in _GF180_PRIMITIVE_CAPS)
    if cap_alt:
        cdl_text = re.sub(
            rf"^X(\S+)((?:\s+\S+){{2}}\s+\S*(?:{cap_alt})\b)",
            r"C\1\2",
            cdl_text,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    return cdl_text


def _needs_ref_spice(cdl_text: str) -> bool:
    return _REF_SPICE_SUBCKTS.search(cdl_text) is not None


def _stage_inputs(workdir: Path, cell: str, netlist_src: Path) -> Path:
    """Normalize the reference netlist into `workdir`; return the staged path.

    Normalizations:
      * rename the schematic's top subckt to the layout cell name,
      * tag bare w=/l= values with a `u` unit suffix,
      * rewrite X-prefix primitive instances to M (fets) / C (mim caps),
      * prepend `.include` of the bundled std-cell spice ONLY if referenced.
    """
    cdl_dst = workdir / f"{cell}.cdl"
    spice_dst = workdir / f"{cell}.spice"
    shutil.copy(netlist_src, cdl_dst)

    cdl_text = cdl_dst.read_text()
    cdl_text = _rename_top_subckt(cdl_text, cell)
    cdl_text = _tag_geometry_units(cdl_text)
    cdl_text = _rewrite_prefix_for_primitives(cdl_text)

    parts: List[str] = []
    if _needs_ref_spice(cdl_text):
        if _REF_SPICE.is_file():
            parts.append(f".include {_REF_SPICE}\n")
        else:
            print(f"[LVS] {cell}: std-cell refs present but {_REF_SPICE} missing", flush=True)
    else:
        print(f"[LVS] {cell}: no std-cell refs; skipping {_REF_SPICE.name}", flush=True)
    parts.append(cdl_text)
    spice_dst.write_text("".join(parts))
    return spice_dst


def _detect_substrate_name(spice_path: Path, top_cell: str) -> str:
    """Pick the schematic's bulk port name to pass as klayout's --lvs_sub.

    klayout's gf180mcu deck names the implicit substrate "gf180mcu_gnd" by
    default; the schematic's bulk port must use the SAME name or LVS reports
    every net as unmatched. We look for the usual bulk conventions, with VSS
    last because it is normally the source rail (CMIRROR's
    `VREF VOUT VSS B` should pick B).

    When nothing bulk-like is present we return the deck default rather than
    guessing the last positional port: passing e.g. IBIAS as the substrate net
    unmatches the entire design and looks like a parser bug.
    """
    try:
        text = spice_path.read_text(errors="ignore")
    except OSError:
        return "gf180mcu_gnd"
    pat = re.compile(
        r"^\.subckt\s+" + re.escape(top_cell) + r"\s+(.+)$",
        re.MULTILINE | re.IGNORECASE,
    )
    m = pat.search(text)
    if not m:
        print(f"[LVS] {top_cell}: no .subckt line found; using deck default", flush=True)
        return "gf180mcu_gnd"
    tokens = [t for t in m.group(1).split() if "=" not in t]
    by_upper = {t.upper(): t for t in tokens}
    for cand in ("B", "VBULK", "VSUB", "GND", "VSS"):
        if cand in by_upper:
            return by_upper[cand]
    print(f"[LVS] {top_cell}: no bulk-like port in {tokens}; using deck default", flush=True)
    return "gf180mcu_gnd"


def _classify_log(log: str) -> Dict[str, Any]:
    """Map the klayout deck's stdout banner to a netgen-style summary.

    Environment failures are surfaced explicitly so the report reads as a root
    cause instead of the catch-all "LVS inconclusive": run_lvs.py imports
    docopt and klayout.db before doing any work, and a missing module leaves
    nothing in the log but a Python traceback.
    """
    if "ModuleNotFoundError: No module named 'docopt'" in log:
        return {"is_pass": False, "conclusion": "missing dep: docopt (install in the deck interpreter)"}
    if "ModuleNotFoundError: No module named 'klayout'" in log:
        return {"is_pass": False, "conclusion": "missing dep: klayout (install in the deck interpreter)"}
    if "klayout: command not found" in log or "klayout: not found" in log:
        return {"is_pass": False, "conclusion": "klayout binary not on PATH"}
    if "klayout LVS deck timed out" in log:
        return {"is_pass": False, "conclusion": "deck timed out"}
    if re.search(r"Congratulations!\s*Netlists\s*match", log) or "INFO : Congratulations" in log:
        return {"is_pass": True, "conclusion": "Netlists match"}
    # Covers "don't", "don\u2019t" and "do not", with or without an ERROR prefix.
    if re.search(r"Netlists\s+do\s*n.?t\s+match", log, re.IGNORECASE):
        return {"is_pass": False, "conclusion": "Netlists do not match"}
    return {"is_pass": False, "conclusion": "LVS inconclusive"}


def run_lvs_klayout_gf180(
    layout: str,
    design_name: str,
    netlist: str,
    output_file_path: str,
    pdk_root: Optional[str] = None,
    variant: str = "D",
    timeout: int = 1800,
) -> Dict[str, Any]:
    """Run gf180mcu klayout LVS for one cell.

    Mirrors `MappedPDK.lvs_netgen`'s signature: writes its primary report to
    ``<output_file_path>/lvs/<cell>/<cell>_lvs.rpt`` (klayout log dumped
    verbatim), and stashes the staged netlist, the extracted .cir, the .lvsdb
    and any lvs_run_*.log alongside it for inspection.
    """
    layout_path = Path(layout)
    netlist_path = Path(netlist)
    rpt_dir = Path(output_file_path) / "lvs" / design_name
    rpt_dir.mkdir(parents=True, exist_ok=True)

    pdk_root = pdk_root or os.environ.get("PDK_ROOT", "/foss/pdks")
    run_lvs = _resolve_deck_dir(pdk_root) / "run_lvs.py"

    with tempfile.TemporaryDirectory(prefix=f"klvs_{design_name}_") as tmp:
        tmpdir = Path(tmp)
        spice_staged = _stage_inputs(tmpdir, design_name, netlist_path)
        sub_name = _detect_substrate_name(spice_staged, design_name)

        # Copy the staged netlist out BEFORE the tempdir is torn down. It is
        # the actual deck input, so a misfiring rewrite is only diagnosable
        # from this file.
        shutil.copy(spice_staged, rpt_dir / f"{design_name}_staged.spice")

        cmd = [
            _deck_python(), str(run_lvs),
            f"--layout={layout_path}",
            f"--netlist={spice_staged}",
            f"--variant={variant}",
            f"--topcell={design_name}",
            "--run_mode=flat",
            "--combine",
            "--schematic_simplify",
            "--top_lvl_pins",
            f"--lvs_sub={sub_name}",
            f"--run_dir={tmpdir}",
        ]
        print(f"[LVS] {design_name}: lvs_sub={sub_name}", flush=True)
        print(f"[LVS] {design_name}: {shlex.join(cmd)}", flush=True)
        try:
            proc = subprocess.run(
                cmd, cwd=tmpdir, capture_output=True, text=True,
                env=_deck_env(), timeout=timeout,
            )
            log_text = (proc.stdout or "") + (proc.stderr or "")
            rc = proc.returncode
        except subprocess.TimeoutExpired as exc:
            partial = (exc.stdout or b"") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            partial_err = (exc.stderr or b"") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            if isinstance(partial, bytes):
                partial = partial.decode(errors="replace")
            if isinstance(partial_err, bytes):
                partial_err = partial_err.decode(errors="replace")
            log_text = f"{partial}{partial_err}\nERROR: klayout LVS deck timed out after {timeout}s\n"
            rc = -1

        # Even on a non-zero exit we want the log preserved for triage.
        rpt_file = rpt_dir / f"{design_name}_lvs.rpt"
        rpt_file.write_text(log_text)

        for fname in (f"{design_name}.cir", f"{design_name}.lvsdb"):
            src = tmpdir / fname
            if src.is_file():
                shutil.copy(src, rpt_dir / fname)
        # rglob, not glob: the deck writes its per-run log into a subdirectory
        # of run_dir, so a non-recursive glob silently matches nothing.
        for src in tmpdir.rglob("lvs_run_*.log"):
            shutil.copy(src, rpt_dir / src.name)

        summary = _classify_log(log_text)
        return {
            "subproc_code": rc,
            "report_path": str(rpt_file),
            "staged_netlist": str(rpt_dir / f"{design_name}_staged.spice"),
            "is_pass": summary["is_pass"],
            "conclusion": summary["conclusion"],
        }
