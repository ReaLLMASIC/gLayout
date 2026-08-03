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
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


# Reference SPICE bundled with gf180_mapped — included in the staged netlist
# so klayout can resolve any standard-cell sub-circuits referenced in tests.
_REF_SPICE = (
    Path(__file__).resolve().parents[2]
    / "src" / "glayout" / "pdk" / "gf180_mapped" / "gf180mcu_osu_sc_9T.spice"
)


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


def _detect_substrate_name(spice_path: Path, top_cell: str) -> str:
    """Pick the schematic's bulk port name to pass as klayout's --lvs_sub.

    klayout's gf180mcu deck names the implicit substrate "gf180mcu_gnd" by
    default. The schematic's bulk port (B / VBULK / VSUB / GND / VSS) needs
    to use the SAME name or LVS reports every net as unmatched. We pick the
    first port matching common bulk conventions; VSS comes last because it
    is usually the source rail (e.g. CMIRROR's `VREF VOUT VSS B` should
    pick B). Falls back to the last positional port, then to the deck
    default.
    """
    try:
        text = spice_path.read_text(errors="ignore")
    except OSError:
        return "gf180mcu_gnd"
    pat = re.compile(r"^\.subckt\s+" + re.escape(top_cell) + r"\s+(.+)$", re.MULTILINE | re.IGNORECASE)
    m = pat.search(text)
    if not m:
        return "gf180mcu_gnd"
    tokens = [t for t in m.group(1).split() if "=" not in t]
    for cand in ("B", "VBULK", "VSUB", "GND", "VSS"):
        if cand in tokens:
            return cand
    return tokens[-1] if tokens else "gf180mcu_gnd"


_GF180_PRIMITIVE_FETS = ("nfet_03v3", "pfet_03v3")


def _rewrite_x_to_m_for_primitives(cdl_text: str) -> str:
    """Rewrite X-prefix instances of gf180 primitive MOSFETs to M-prefix.

    glayout's netlist generators emit X-prefix everywhere (sky130's
    magic+netgen tech setup expects X-instances of `sky130_fd_pr__nfet_01v8`
    and matches them via the netgen tech file). klayout's gf180mcu deck
    classifies primitive MOSFETs by SPICE prefix instead — only M-prefix
    instances of `nfet_03v3`/`pfet_03v3` get auto-promoted to MOS4 device
    classes; X-prefix instances are treated as unknown subckts (no
    `.subckt` body anywhere) and the schematic side ends up with 0
    transistors, every layout fet then becomes an unmatched device.

    Match instance lines whose model token (everything after the four
    terminal nets) is one of the primitive fet models, and rewrite the
    leading ``X`` to ``M``. Lines that hit subckt wrappers (NMOS, PMOS,
    DIFF_PAIR, ...) are left as X — those are real subckt references.
    """
    fet_alt = "|".join(re.escape(m) for m in _GF180_PRIMITIVE_FETS)
    pat = re.compile(
        rf"^X(\S+)(\s+\S+\s+\S+\s+\S+\s+\S+\s+(?:{fet_alt})\b)",
        re.MULTILINE,
    )
    return pat.sub(r"M\1\2", cdl_text)


def _stage_inputs(workdir: Path, cell: str, gds_src: Path, netlist_src: Path) -> Path:
    """Copy GDS + reference netlist into the temp dir, normalize, and return
    the staged spice path. Normalizations (mirror `.run_ci_lvs_v2.sh`):

    * Rename the schematic's top subckt to match the layout cell name.
    * Add explicit `u` unit suffix to bare `w=`/`l=` numeric values
      (gf180mcu deck rejects unitless geometry params).
    * Rewrite X-prefix instances of primitive `nfet_03v3`/`pfet_03v3`
      to M-prefix so klayout's deck classifies them as MOS4. The
      generator code stays PDK-agnostic and emits X-prefix everywhere.
    * Prepend `.include` of the bundled reference spice so any std-cell
      subckt the test netlist references can be resolved.
    """
    layout_dst = workdir / f"{cell}.gds"
    cdl_dst = workdir / f"{cell}.cdl"
    spice_dst = workdir / f"{cell}.spice"
    shutil.copy(gds_src, layout_dst)
    shutil.copy(netlist_src, cdl_dst)

    cdl_text = cdl_dst.read_text()
    sch_top_match = re.findall(r"^\.subckt\s+(\S+)", cdl_text, re.MULTILINE)
    if sch_top_match and sch_top_match[-1] != cell:
        sch_top = sch_top_match[-1]
        cdl_text = re.sub(rf"\b{re.escape(sch_top)}\b", cell, cdl_text)

    # Tag bare w=/l= values with `u` so klayout's parser accepts them.
    cdl_text = re.sub(r"(\bw=)([0-9.]+)(?=\s|$)", r"\1\2u", cdl_text, flags=re.MULTILINE)
    cdl_text = re.sub(r"(\bl=)([0-9.]+)(?=\s|$)", r"\1\2u", cdl_text, flags=re.MULTILINE)

    # Rewrite X-prefix primitive fet instances to M-prefix.
    cdl_text = _rewrite_x_to_m_for_primitives(cdl_text)

    parts = []
    if _REF_SPICE.is_file():
        parts.append(f".include {_REF_SPICE}\n")
    parts.append(cdl_text)
    spice_dst.write_text("".join(parts))
    return spice_dst


def _classify_log(log: str) -> Dict[str, Any]:
    """Map the klayout deck's stdout banner to a netgen-style summary so the
    existing ``_parse_lvs_report`` happily reports pass/fail."""
    # Surface the most common environment failure modes explicitly so the
    # report file makes the root cause obvious instead of getting binned as
    # generic "LVS inconclusive". `docopt` is imported at the top of the
    # gf180mcu deck's `run_lvs.py`; if it's missing the whole script aborts
    # before any LVS work happens and the report would otherwise be silent.
    if "ModuleNotFoundError: No module named 'docopt'" in log:
        return {"is_pass": False, "conclusion": "missing dep: docopt (pip install docopt in the LVS venv)"}
    if "ModuleNotFoundError: No module named 'klayout'" in log:
        return {"is_pass": False, "conclusion": "missing dep: klayout (pip install klayout in the LVS venv)"}
    if "klayout: command not found" in log or "klayout: not found" in log:
        return {"is_pass": False, "conclusion": "klayout binary not on PATH"}
    if re.search(r"Congratulations!\s*Netlists\s*match", log) or "INFO : Congratulations" in log:
        return {"is_pass": True, "conclusion": "Netlists match"}
    if re.search(r"ERROR\s*:\s*Netlists\s*don.t\s*match", log) or "Netlists do not match" in log:
        return {"is_pass": False, "conclusion": "Netlists do not match"}
    return {"is_pass": False, "conclusion": "LVS inconclusive"}


def run_lvs_klayout_gf180(
    layout: str,
    design_name: str,
    netlist: str,
    output_file_path: str,
    pdk_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Run gf180mcu klayout LVS for one cell.

    Mirrors `MappedPDK.lvs_netgen`'s signature: writes its primary report to
    ``<output_file_path>/lvs/<cell>/<cell>_lvs.rpt`` (klayout log dumped
    verbatim — `_parse_lvs_report` recognises the "Netlists match" /
    "Netlists do not match" lines), and stashes the extracted .cir, .lvsdb,
    and lvs_run_*.log alongside it for inspection.
    """
    layout_path = Path(layout)
    netlist_path = Path(netlist)
    out_root = Path(output_file_path)
    rpt_dir = out_root / "lvs" / design_name
    rpt_dir.mkdir(parents=True, exist_ok=True)

    pdk_root = pdk_root or os.environ.get("PDK_ROOT", "/foss/pdks")
    deck_dir = _resolve_deck_dir(pdk_root)
    run_lvs = deck_dir / "run_lvs.py"

    with tempfile.TemporaryDirectory(prefix=f"klvs_{design_name}_") as tmp:
        tmpdir = Path(tmp)
        spice_staged = _stage_inputs(tmpdir, design_name, layout_path, netlist_path)
        sub_name = _detect_substrate_name(spice_staged, design_name)

        cmd = [
            "python3", str(run_lvs),
            f"--layout={layout_path}",
            f"--netlist={spice_staged}",
            "--variant=D",
            f"--topcell={design_name}",
            "--run_mode=flat",
            "--combine",
            "--schematic_simplify",
            "--top_lvl_pins",
            f"--lvs_sub={sub_name}",
            f"--run_dir={tmpdir}",
        ]
        proc = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True)

        # Even on klayout-exit-nonzero we want the log preserved for triage.
        log_text = (proc.stdout or "") + (proc.stderr or "")
        rpt_file = rpt_dir / f"{design_name}_lvs.rpt"
        rpt_file.write_text(log_text)

        # Stash the extracted netlist + lvsdb + per-run log if produced.
        for fname in (f"{design_name}.cir", f"{design_name}.lvsdb"):
            src = tmpdir / fname
            if src.is_file():
                shutil.copy(src, rpt_dir / fname)
        for src in tmpdir.glob("lvs_run_*.log"):
            shutil.copy(src, rpt_dir / src.name)

        summary = _classify_log(log_text)
        return {
            "subproc_code": proc.returncode,
            "report_path": str(rpt_file),
            "is_pass": summary["is_pass"],
            "conclusion": summary["conclusion"],
        }
