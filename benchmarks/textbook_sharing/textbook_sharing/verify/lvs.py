"""Independent LVS runners (inside the container).
 - sky130, ihp130: magic extraction (ext2spice lvs) + netgen with the PDK setup file
 - gf180: official gf180mcu KLayout LVS deck (upstream notes magic/netgen mis-extracts the gf180 substrate)
Each runner returns a dict with status, counts and report paths; nothing is swallowed."""
from __future__ import annotations
import os, re, subprocess, hashlib
from pathlib import Path

PDK_ROOT = os.environ.get("PDK_ROOT", "/foss/pdks")
MAGICRC = {"sky130": f"{PDK_ROOT}/sky130A/libs.tech/magic/sky130A.magicrc", "gf180": f"{PDK_ROOT}/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc",
           "ihp130": f"{PDK_ROOT}/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.magicrc"}
NETGEN_SETUP = {"sky130": f"{PDK_ROOT}/sky130A/libs.tech/netgen/sky130A_setup.tcl", "gf180": f"{PDK_ROOT}/gf180mcuD/libs.tech/netgen/gf180mcuD_setup.tcl",
                "ihp130": f"{PDK_ROOT}/ihp-sg13g2/libs.tech/netgen/ihp-sg13g2_setup.tcl"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(cmd, cwd, log, timeout=1800, env=None):
    with open(log, "w") as f:
        f.write("$ " + (cmd if isinstance(cmd, str) else " ".join(cmd)) + "\n")
        f.flush()
        try:
            r = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
            return r.returncode
        except subprocess.TimeoutExpired:
            f.write("\nTIMEOUT\n"); return -999


def magic_extract(pdk, gds, top, out_dir, mode="lvs", timeout=None, extresist_tolerance=10, with_resist=True):
    """mode 'lvs': device netlist only. mode 'pex': parasitic C (and R via extresist)."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    for stale in set(list(out_dir.glob('*.ext')) + list(out_dir.glob('*.spice')) + list(out_dir.glob('*.sim')) + list(out_dir.glob('*.nodes'))):
        stale.unlink(missing_ok=True)
    spice = out_dir / f"{top}_{mode}.spice"
    extra = ""
    if mode == "pex":
        if with_resist:
            extra = f"extract do local\nextract all\next2sim labels on\next2sim\nextresist tolerance {extresist_tolerance}\nextresist\next2spice lvs\next2spice cthresh 0\next2spice rthresh 0\next2spice extresist on\n"
        else:
            extra = "extract do local\nextract all\next2spice lvs\next2spice cthresh 0\next2spice rthresh 0\n"
    else:
        extra = "extract all\next2spice lvs\n"
    # on gf180mcuD, 'port makeall' followed by extresist never terminates; top-level pins are taken from the labels
    # there instead (checked: identical pin list)
    portcmd = "" if (pdk == "gf180" and mode == "pex" and with_resist) else "port makeall"
    tcl = f"""drc off
gds flatglob *\\$\\$*
gds read {gds}
load {top}
select top cell
{portcmd}
{extra}ext2spice subcircuit top on
ext2spice -o {spice}
quit -noprompt
"""
    (out_dir / f"magic_{mode}.tcl").write_text(tcl)
    to = timeout or (900 if mode == "pex" else 300)
    rc = run(f"magic -rcfile {MAGICRC[pdk]} -noconsole -dnull {out_dir}/magic_{mode}.tcl", str(out_dir), out_dir / f"magic_{mode}.log", timeout=to)
    ok = rc == 0 and spice.exists() and spice.stat().st_size > 0
    return {"tool": "magic", "rc": rc, "ok": ok, "timeout": rc == -999, "spice": str(spice) if ok else None, "log": str(out_dir / f"magic_{mode}.log"), "with_resist": with_resist if mode == "pex" else None, "extresist_tolerance": extresist_tolerance if (mode == "pex" and with_resist) else None}


def parse_netgen(report_text: str) -> dict:
    out = {"match": False, "unmatched_nets": 0, "unmatched_instances": 0, "pin_mismatch": False, "property_errors": 0}
    if "Circuits match uniquely" in report_text or "Netlists match uniquely" in report_text:
        out["match"] = True
    if "Netlists do not match" in report_text or "do not match" in report_text:
        out["match"] = False
    out["unmatched_nets"] = len(re.findall(r"\(no matching net\)", report_text))
    out["unmatched_instances"] = len(re.findall(r"\(no matching instance\)", report_text))
    out["pin_mismatch"] = "failed pin matching" in report_text
    out["property_errors"] = len(re.findall(r"property .* mismatch|Property errors were found", report_text, re.I))
    m = re.search(r"Final result: (.*)", report_text)
    out["final"] = m.group(1).strip() if m else None
    if out["final"] and "match" in out["final"].lower() and "not" not in out["final"].lower() and "fail" not in out["final"].lower():
        out["match"] = out["match"] or ("uniquely" in out["final"].lower() or "match" in out["final"].lower())
    if out["pin_mismatch"] or out["unmatched_nets"] or out["unmatched_instances"]:
        out["match"] = False
    return out


def lvs_magic_netgen(pdk, gds, top, schematic, out_dir):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    ex = magic_extract(pdk, gds, top, out_dir, "lvs")
    res = {"method": "magic+netgen", "pdk": pdk, "gds_sha256": sha(gds), "schematic_sha256": sha(schematic), "extract": ex}
    if not ex["ok"]:
        res.update({"status": "lvs_failed", "reason": "extraction failed"}); return res
    rpt = out_dir / "netgen_lvs.rpt"
    rc = run(f'netgen -batch lvs "{ex["spice"]} {top}" "{schematic} {top}" {NETGEN_SETUP[pdk]} {rpt}', str(out_dir), out_dir / "netgen.log")
    txt = rpt.read_text() if rpt.exists() else ""
    p = parse_netgen(txt)
    res.update({"netgen_rc": rc, "report": str(rpt), "parsed": p, "status": "passed" if (rc == 0 and p["match"]) else "lvs_failed"})
    return res


def lvs_klayout_gf180(gds, top, schematic, out_dir, sub_net="VSS"):
    # no --combine: KLayout's device combining merges series resistors through a net that has no other device,
    # which deletes a port net such as VDD on a resistor-load pair (observed on C16/C17 gf180); fingers are per-finger on both sides.
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    deck = f"{PDK_ROOT}/gf180mcuD/libs.tech/klayout/tech/lvs/run_lvs.py"
    run_dir = out_dir / "klayout_lvs"
    rc = run(f"python {deck} --layout={gds} --netlist={schematic} --variant=D --run_dir={run_dir} --thr=4 --topcell={top} --schematic_simplify --lvs_sub={sub_net}", str(out_dir), out_dir / "klayout_lvs.log")
    log = (out_dir / "klayout_lvs.log").read_text(errors="replace")
    logs = list(run_dir.glob("lvs_run_*.log")) if run_dir.exists() else []
    ltxt = logs[-1].read_text(errors="replace") if logs else ""
    match = ("Congratulations! Netlists matched" in log + ltxt) or ("Netlists matched" in log + ltxt) or ("Netlists match" in log + ltxt)
    nomatch = "Netlists don't match" in log + ltxt or "do not match" in log + ltxt
    # authoritative verdict: the cross-reference stored in the LVS database (requires every circuit pair to be 'Match')
    lvsdb = next(run_dir.glob("*.lvsdb"), None) if run_dir.exists() else None
    xref = lvsdb_verdict(str(lvsdb)) if lvsdb else {"ok": False, "error": "no lvsdb"}
    match = bool(xref.get("ok")); nomatch = not match
    res = {"method": "klayout_gf180mcu_lvs", "pdk": "gf180", "gds_sha256": sha(gds), "schematic_sha256": sha(schematic), "rc": rc, "log": str(out_dir / "klayout_lvs.log"),
           "deck_log": str(logs[-1]) if logs else None, "lvsdb": str(next(run_dir.glob("*.lvsdb"), "")) if run_dir.exists() else None,
           "status": "passed" if (rc == 0 and match and not nomatch) else "lvs_failed", "matched": match, "xref": xref}
    return res


def lvs(pdk, gds, top, schematic, out_dir, sub_net="VSS"):
    if pdk == "gf180":
        return lvs_klayout_gf180(gds, top, schematic, out_dir, sub_net)
    return lvs_magic_netgen(pdk, gds, top, schematic, out_dir)


def lvsdb_verdict(path: str) -> dict:
    """Read a KLayout LVS database and return {ok, pairs:[{layout, ref, status}], mismatched_nets, mismatched_devices}."""
    try:
        import klayout.db as kdb
        l = kdb.LayoutVsSchematic(); l.read(path)
        x = l.xref()
        if x is None:
            return {"ok": False, "error": "no xref in lvsdb"}
        pairs = []; bad_nets = []; bad_devs = []; ok = True
        for cp in x.each_circuit_pair():
            st = str(cp.status()); a = cp.first(); b = cp.second()
            pairs.append({"layout": a.name if a else None, "ref": b.name if b else None, "status": st})
            if st != "Match": ok = False
            for np_ in x.each_net_pair(cp):
                if str(np_.status()) not in ("Match",):
                    f, g = np_.first(), np_.second()
                    bad_nets.append({"layout": f.expanded_name() if f else None, "ref": g.expanded_name() if g else None, "status": str(np_.status())}); ok = False
            for dp in x.each_device_pair(cp):
                if str(dp.status()) not in ("Match",):
                    f, g = dp.first(), dp.second()
                    bad_devs.append({"layout": f.expanded_name() if f else None, "ref": g.expanded_name() if g else None, "status": str(dp.status())}); ok = False
        return {"ok": ok, "pairs": pairs, "mismatched_nets": bad_nets[:50], "mismatched_devices": bad_devs[:50]}
    except Exception as e:
        return {"ok": False, "error": repr(e)}
