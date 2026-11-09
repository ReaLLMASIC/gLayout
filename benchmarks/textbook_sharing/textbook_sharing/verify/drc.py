"""DRC with the PDK-shipped official KLayout decks (primary) and magic (secondary).

Waivers (identical for every track and mode, declared here):
  ihp130: chip-level density / filler rules of the maximal deck (AFil.*, GFil.*, M[1-5]Fil.*, M[1-5].j/k, TM[12].c/d)
          are not meaningful for a DUT of a few hundred um^2 and are reported but not counted.
  gf180:  none.   sky130: none.
"""
from __future__ import annotations
import os, re, xml.etree.ElementTree as ET
from pathlib import Path
from .lvs import run, sha, MAGICRC

PDK_ROOT = os.environ.get("PDK_ROOT", "/foss/pdks")
DECK = {"sky130": f"{PDK_ROOT}/sky130A/libs.tech/klayout/drc/sky130A.lydrc",
        "gf180": f"{PDK_ROOT}/gf180mcuD/libs.tech/klayout/tech/drc/run_drc.py",
        "ihp130": f"{PDK_ROOT}/ihp-sg13g2/libs.tech/klayout/tech/drc/sg13g2_maximal.lydrc"}
WAIVED = {"ihp130": re.compile(r"^'?(AFil\.|GFil\.|M[1-5]Fil\.|M[1-5]\.j/k|TM[12]\.c/d)"), "sky130": None, "gf180": None}
DRC_VERSION = "drc-v1 (official decks; ihp density waivers)"


def parse_lyrdb(path):
    cats = {}; items = []
    try:
        root = ET.parse(path).getroot()
    except Exception as e:
        return {"error": repr(e), "categories": {}, "items": []}
    for it in root.iter("item"):
        c = it.find("category").text.strip("'")
        vals = [v.text for v in it.iter("value")]
        cats[c] = cats.get(c, 0) + 1
        if len(items) < 200: items.append({"category": c, "value": vals[0] if vals else None})
    return {"categories": cats, "items": items}


def drc_klayout(pdk, gds, out_dir, top=None):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    gds = str(Path(gds).resolve()); rpt = out_dir / "klayout_drc.lyrdb"; log = out_dir / "klayout_drc.log"
    if pdk == "sky130":
        rc = run(f"klayout -b -r {DECK[pdk]} -rd input={gds} -rd report={rpt}", str(out_dir), log)
    elif pdk == "ihp130":
        rc = run(f"klayout -b -r {DECK[pdk]} -rd in_gds={gds} -rd report_file={rpt}" + (f" -rd cell={top}" if top else ""), str(out_dir), log)
    else:
        rd = out_dir / "gf180_run"
        rc = run(f"python {DECK[pdk]} --path={gds} --variant=D --run_dir={rd} --thr=4" + (f" --topcell={top}" if top else ""), str(out_dir), log)
        src = next(rd.glob("*.lyrdb"), None) if rd.exists() else None
        if src: rpt.write_bytes(src.read_bytes())
    parsed = parse_lyrdb(rpt) if rpt.exists() else {"error": "no report", "categories": {}, "items": []}
    waived = {}; counted = {}
    for c, n in parsed["categories"].items():
        if WAIVED[pdk] and WAIVED[pdk].match(c): waived[c] = n
        else: counted[c] = n
    total = sum(counted.values())
    return {"tool": "klayout", "deck": DECK[pdk], "deck_sha256": sha(DECK[pdk]), "version": DRC_VERSION, "rc": rc, "report": str(rpt) if rpt.exists() else None,
            "log": str(log), "violations": total, "categories": counted, "waived_categories": waived, "items": parsed["items"][:50],
            "status": "passed" if (rpt.exists() and total == 0 and "error" not in parsed) else "drc_failed"}


def drc_magic(pdk, gds, top, out_dir):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    tcl = out_dir / "magic_drc.tcl"; rpt = out_dir / "magic_drc.rpt"
    tcl.write_text(f"""gds flatglob *\\$\\$*
gds read {gds}
load {top}
select top cell
drc euclidean on
drc style drc(full)
drc check
set fo [open {rpt} w]
foreach {{why coords}} [drc listall why] {{ puts $fo "$why"; foreach c $coords {{ puts $fo "  $c" }} }}
close $fo
quit -noprompt
""")
    rc = run(f"magic -rcfile {MAGICRC[pdk]} -noconsole -dnull {tcl}", str(out_dir), out_dir / "magic_drc.log")
    txt = rpt.read_text() if rpt.exists() else ""
    rules = {}
    cur = None
    for l in txt.splitlines():
        if l.startswith("  "): rules[cur] = rules.get(cur, 0) + 1
        elif l.strip(): cur = l.strip()
    return {"tool": "magic", "rc": rc, "report": str(rpt) if rpt.exists() else None, "violations": sum(rules.values()), "rules": rules,
            "status": "passed" if rpt.exists() and not rules else ("drc_failed" if rpt.exists() else "not_run")}
