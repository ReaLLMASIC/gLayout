"""PEX (magic) and ngspice simulation runners.

PEX: magic 'extract' with parasitic capacitance (cthresh 0) and resistance via extresist (rthresh 0),
    writes <top>_pex.spice (subckt with the DUT ports as pins, port names from the layout labels).
SIM: a testbench template is rendered with the DUT include file and run with ngspice -b; measurements are
    written by the testbench with wrdata/print into files that the measurement parser reads.
"""
from __future__ import annotations
import os, re
from pathlib import Path
from .lvs import magic_extract, run, sha

PDK_ROOT = os.environ.get("PDK_ROOT", "/foss/pdks")
MODEL_INCLUDE = {
    "sky130": ".lib {root}/sky130A/libs.tech/ngspice/sky130.lib.spice {corner}",
    "gf180": ".include {root}/gf180mcuD/libs.tech/ngspice/design.ngspice\n.lib {root}/gf180mcuD/libs.tech/ngspice/sm141064.ngspice {corner}\n.lib {root}/gf180mcuD/libs.tech/ngspice/sm141064.ngspice res_typical\n.lib {root}/gf180mcuD/libs.tech/ngspice/sm141064.ngspice mimcap_typical\n.lib {root}/gf180mcuD/libs.tech/ngspice/sm141064.ngspice cap_mim",   # mimcap_typical only sets corner params and includes sm141064_mim.ngspice by a cwd-relative path (which also fails to parse in ngspice 44); the legacy cap_mim section defines cap_mim_2f0fF
    "ihp130": ".lib {root}/ihp-sg13g2/libs.tech/ngspice/models/cornerMOSlv.lib {corner}\n.lib {root}/ihp-sg13g2/libs.tech/ngspice/models/cornerRES.lib res_typ\n.lib {root}/ihp-sg13g2/libs.tech/ngspice/models/cornerCAP.lib cap_typ",
}
CORNER = {"sky130": {"tt": "tt", "ss": "ss", "ff": "ff"}, "gf180": {"tt": "typical", "ss": "ss", "ff": "ff"}, "ihp130": {"tt": "mos_tt", "ss": "mos_ss", "ff": "mos_ff"}}
OSDI = {"ihp130": f"{PDK_ROOT}/ihp-sg13g2/libs.tech/ngspice/osdi/psp103_nqs.osdi"}


def model_header(pdk: str, corner: str = "tt") -> str:
    c = CORNER[pdk][corner]
    return MODEL_INCLUDE[pdk].format(root=PDK_ROOT, corner=c) + "\n"


PEX_POLICY = {
    "sky130": {"with_resist": True, "extresist_tolerance": 10, "note": "magic extract + extresist (R and C)"},
    "ihp130": {"with_resist": True, "extresist_tolerance": 10, "note": "magic extract + extresist (R and C)"},
    "gf180": {"with_resist": True, "extresist_tolerance": 10, "note": "magic extract + extresist (R and C); top-level pins from labels, without 'port makeall' (with it, extresist does not terminate on gf180mcuD)"},
}


def pex(pdk, gds, top, out_dir):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    pol = PEX_POLICY[pdk]
    ex = magic_extract(pdk, gds, top, out_dir, "pex", with_resist=pol["with_resist"], extresist_tolerance=pol["extresist_tolerance"] or 10)
    res = {"method": "magic_extresist" if pol["with_resist"] else "magic_cap_only", "policy": pol, "pdk": pdk, "gds_sha256": sha(gds), "extract": ex}
    if not ex["ok"]:
        res["status"] = "pex_failed"; return res
    txt = Path(ex["spice"]).read_text()
    m = re.search(r"^\.subckt\s+(\S+)\s+(.*)$", txt, re.M | re.I)
    ports = m.group(2).split() if m else []
    # Floating conductors (magic marks their capacitors with '**FLOATING'; e.g. the poly body of an IHP rppd resistor
    # that magic's tech file extracts as a separate 'pres' node) have no DC path and make the ngspice matrix singular.
    # They are kept (their parasitic capacitances stay in the netlist) and tied to the DUT ground port by a 1 TOhm
    # shunt, so the simulation remains solvable without hiding the extraction.  The nodes are recorded.
    floating = []
    for line in txt.splitlines():
        if "**FLOATING" in line and line[:1].upper() == "C":
            toks = line.split()
            for n in toks[1:3]:
                if n not in ports and n not in floating: floating.append(n)
    if floating:
        gnd = "VSS" if "VSS" in ports else (ports[-1] if ports else "0")
        shunts = "".join(f"Rflt{i} {n} {gnd} 1e12  $ floating-conductor shunt\n" for i, n in enumerate(floating))
        txt = re.sub(r"^\.ends", shunts + ".ends", txt, count=1, flags=re.M | re.I)
        Path(ex["spice"]).write_text(txt)
    nR = len(re.findall(r"^R\S+\s", txt, re.M)); nC = len(re.findall(r"^C\S+\s", txt, re.M)); nM = len(re.findall(r"^[XM]\S+\s", txt, re.M))
    res.update({"status": "passed", "spice": ex["spice"], "spice_sha256": sha(ex["spice"]), "n_res": nR, "n_cap": nC, "n_devices": nM, "ports": ports,
                "floating_nodes": floating, "floating_shunt_ohm": 1e12 if floating else None})
    return res


def simulate(pdk, testbench_text, out_dir, name="tb", corner="tt", timeout=900, extra_env=None):
    """testbench_text must be a complete ngspice deck except the model header (prepended here) and may use .control."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    deck = out_dir / f"{name}.spice"
    hdr = f"* {name} ({pdk}, corner {corner})\n" + model_header(pdk, corner)
    if pdk in OSDI:
        hdr += f".control\npre_osdi {OSDI[pdk]}\n.endc\n"
    deck.write_text(hdr + testbench_text)
    log = out_dir / f"{name}.log"
    rc = run(f"ngspice -b {deck} -o {out_dir}/{name}.out", str(out_dir), log, timeout=timeout)
    outtxt = (out_dir / f"{name}.out").read_text(errors="replace") if (out_dir / f"{name}.out").exists() else ""
    logtxt = log.read_text(errors="replace")
    errors = [l for l in (outtxt + logtxt).splitlines() if re.search(r"^Error|error:|singular matrix|timestep too small|no convergence|doAnalyses: ", l, re.I)
              and not re.search(r"^Error: measure\s", l)]   # a .meas that finds no crossing yields a missing measure -> spec check, not a simulator failure
    measure_errors = [l for l in (outtxt + logtxt).splitlines() if re.search(r"^Error: measure\s", l)]
    return {"rc": rc, "deck": str(deck), "deck_sha256": sha(deck), "out": str(out_dir / f"{name}.out"), "log": str(log), "errors": errors[:20], "measure_errors": measure_errors[:20],
            "status": "passed" if (rc == 0 and not errors) else ("simulation_failed" if rc != -999 else "simulation_timeout")}


def read_wrdata(path):
    """Parse an ngspice wrdata file: columns alternate x,y per vector -> dict of lists (first x kept)."""
    rows = [l.split() for l in Path(path).read_text().splitlines() if l.strip() and not l.startswith("*")]
    cols = list(zip(*[[float(v) for v in r] for r in rows])) if rows else []
    return cols


def read_measures(out_text: str) -> dict:
    """Collect 'name = value' lines printed by .meas / print in ngspice batch output."""
    res = {}
    for m in re.finditer(r"^\s*([a-zA-Z_][\w]*)\s*=\s*([-+]?[\d.]+(?:e[-+]?\d+)?)", out_text, re.M):
        try: res[m.group(1).lower()] = float(m.group(2))
        except ValueError: pass
    m = re.search(r"THD:\s*([-+]?[\d.]+(?:e[-+]?\d+)?)\s*%", out_text)
    if m: res["thd_pct"] = float(m.group(1))
    return res
