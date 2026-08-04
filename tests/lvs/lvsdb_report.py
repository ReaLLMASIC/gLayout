"""Extract the *actual* mismatches from a klayout ``.lvsdb``.

The gf180mcu deck's stdout only ever says "Netlists don't match". Every
detail lives in the LVS database, in two places:

1. Per-circuit ``log()`` blocks inside the ``xref()`` section, holding the
   exact human-readable messages the KLayout netlist browser displays
   ("Net X is not matching any net from reference netlist", "Net X may be
   shorting nets A and B from reference netlist"). These are *written* to
   the file but are NOT reachable through klayout's Python binding --
   ``LayoutVsSchematic.each_log_entry()`` only returns top-level extraction
   entries, and neither ``Circuit`` nor ``NetlistCrossReference`` exposes a
   per-circuit-pair log accessor. So we text-parse them.

2. The cross-reference pair lists (net/device/pin/subcircuit pairings with
   status), which ARE reachable via the binding and give us structured
   names plus device parameter diffs.

We read both, plus a direct top-level port comparison between the
extracted ``.cir`` and the staged ``.spice`` -- with ``--top_lvl_pins`` a
single extra label in the layout becomes an extra pin and fails the
compare, which is invisible in the net-level output.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

BAD_STATUS = {"Mismatch", "NoMatch", "Skipped", "mismatch", "nomatch", "skipped"}


# --------------------------------------------------------------------------
# 1. Text parse of the per-circuit log() blocks (no klayout dependency)
# --------------------------------------------------------------------------

_ENTRY_RE = re.compile(
    r"entry\(\s*(?P<sev>\w+)\s+description\('(?P<msg>(?:[^'\\]|\\.)*)'\)",
    re.DOTALL,
)


def _find_section(text: str, name: str) -> Optional[str]:
    """Return the body of a top-level ``name( ... )`` section."""
    start = text.find(f"\n{name}(")
    if start < 0:
        if text.startswith(f"{name}("):
            start = 0
        else:
            return None
    open_paren = text.find("(", start)
    depth, i, n = 0, open_paren, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                in_str = False
        elif ch == "'":
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : i]
        i += 1
    return None


def _iter_blocks(body: str, name: str):
    """Yield (header_line, block_body) for each ``name( ... )`` in body."""
    needle = f"{name}("
    idx = 0
    while True:
        pos = body.find(needle, idx)
        if pos < 0:
            return
        # must be at a token boundary
        if pos > 0 and (body[pos - 1].isalnum() or body[pos - 1] == "_"):
            idx = pos + len(needle)
            continue
        open_paren = pos + len(needle) - 1
        depth, i, n, in_str = 0, open_paren, len(body), False
        while i < n:
            ch = body[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == "'":
                    in_str = False
            elif ch == "'":
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = body[open_paren + 1 : i]
        header = block.split("\n", 1)[0].strip()
        yield header, block
        idx = i + 1


def parse_lvsdb_messages(path: str | Path) -> List[Dict[str, Any]]:
    """Per-circuit-pair messages, exactly as the netlist browser shows them."""
    text = Path(path).read_text(errors="ignore")
    xref_body = _find_section(text, "xref")
    if xref_body is None:
        return []

    circuits: List[Dict[str, Any]] = []
    for header, block in _iter_blocks(xref_body, "circuit"):
        toks = header.split()
        layout_name = toks[0] if toks else None
        sch_name = toks[1] if len(toks) > 1 else None
        status = toks[2] if len(toks) > 2 else "unknown"
        entry = {
            "layout": None if layout_name == "()" else layout_name,
            "schematic": None if sch_name == "()" else sch_name,
            "status": status,
            "errors": [],
            "warnings": [],
            "infos": [],
        }
        log_body = None
        for _h, lb in _iter_blocks(block, "log"):
            log_body = lb
            break
        if log_body:
            for m in _ENTRY_RE.finditer(log_body):
                sev = m.group("sev").lower()
                msg = m.group("msg").replace("\\'", "'")
                bucket = {"error": "errors", "warning": "warnings"}.get(sev, "infos")
                entry[bucket].append(msg)
        circuits.append(entry)
    return circuits


# --------------------------------------------------------------------------
# 2. Structured cross-reference via the klayout binding (optional)
# --------------------------------------------------------------------------

def _call(obj, *names):
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            return v() if callable(v) else v
    return None


def _name_of(obj):
    if obj is None:
        return None
    for n in ("expanded_name", "name"):
        if hasattr(obj, n):
            v = getattr(obj, n)
            v = v() if callable(v) else v
            if v:
                return str(v)
    return str(obj)


def _param_diff(a, b, ignore=("AS", "AD", "PS", "PD", "NRD", "NRS")):
    out = []
    dc = _call(a, "device_class") or _call(b, "device_class")
    if dc is None:
        return out
    try:
        defs = dc.parameter_definitions()
    except Exception:
        return out
    for pd in defs:
        pname = _call(pd, "name")
        if pname in ignore:
            continue
        try:
            va, vb = float(a.parameter(pname)), float(b.parameter(pname))
        except Exception:
            continue
        if abs(va - vb) > 1e-9 * max(1.0, abs(va)):
            out.append({"param": pname, "layout": va, "schematic": vb})
    return out


def parse_lvsdb_xref(path: str | Path) -> Dict[str, Any]:
    """Structured pair data. Returns {'available': False, ...} if klayout is absent."""
    try:
        import klayout.db as kdb
    except ImportError as exc:
        return {"available": False, "reason": f"klayout module not importable: {exc}", "circuits": []}

    try:
        db = kdb.LayoutVsSchematic()
        db.read(str(path))
        xref = db.xref()
    except Exception as exc:
        return {"available": False, "reason": f"could not read lvsdb: {exc}", "circuits": []}

    result = {"available": True, "reason": None, "extraction_log": [], "circuits": []}
    try:
        for e in db.each_log_entry():
            result["extraction_log"].append(
                {"severity": str(_call(e, "severity")), "message": str(_call(e, "message"))}
            )
    except Exception:
        pass

    for cp in xref.each_circuit_pair():
        lay, sch = _call(cp, "first"), _call(cp, "second")
        c: Dict[str, Any] = {
            "layout": _name_of(lay),
            "schematic": _name_of(sch),
            "status": str(_call(cp, "status")),
            "nets_only_in_layout": [],
            "nets_only_in_schematic": [],
            "nets_mismatched": [],
            "devices_only_in_layout": [],
            "devices_only_in_schematic": [],
            "devices_mismatched": [],
            "pins_mismatched": [],
            "subcircuits_mismatched": [],
        }
        for np_ in xref.each_net_pair(cp):
            if str(_call(np_, "status")) not in BAD_STATUS:
                continue
            a, b = _name_of(_call(np_, "first")), _name_of(_call(np_, "second"))
            if a and not b:
                c["nets_only_in_layout"].append(a)
            elif b and not a:
                c["nets_only_in_schematic"].append(b)
            else:
                c["nets_mismatched"].append({"layout": a, "schematic": b})
        for dp in xref.each_device_pair(cp):
            if str(_call(dp, "status")) not in BAD_STATUS:
                continue
            da, dbv = _call(dp, "first"), _call(dp, "second")
            a, b = _name_of(da), _name_of(dbv)
            cls = _name_of(_call(da, "device_class") or _call(dbv, "device_class"))
            if a and not b:
                c["devices_only_in_layout"].append({"name": a, "class": cls})
            elif b and not a:
                c["devices_only_in_schematic"].append({"name": b, "class": cls})
            else:
                c["devices_mismatched"].append(
                    {"layout": a, "schematic": b, "class": cls, "param_diff": _param_diff(da, dbv)}
                )
        for pp in xref.each_pin_pair(cp):
            if str(_call(pp, "status")) in BAD_STATUS:
                c["pins_mismatched"].append(
                    {"layout": _name_of(_call(pp, "first")), "schematic": _name_of(_call(pp, "second"))}
                )
        for sp in xref.each_subcircuit_pair(cp):
            if str(_call(sp, "status")) in BAD_STATUS:
                c["subcircuits_mismatched"].append(
                    {"layout": _name_of(_call(sp, "first")), "schematic": _name_of(_call(sp, "second"))}
                )
        result["circuits"].append(c)
    return result


# --------------------------------------------------------------------------
# 3. Top-level port comparison (catches extra pins under --top_lvl_pins)
# --------------------------------------------------------------------------

_SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(\S+)\s*(.*)$", re.IGNORECASE | re.MULTILINE)


def _ports_of(path: Path, top: str) -> Optional[List[str]]:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return None
    # join SPICE continuation lines
    text = re.sub(r"\n\+\s*", " ", text)
    for m in _SUBCKT_RE.finditer(text):
        if m.group(1).lower() == top.lower():
            return [t for t in m.group(2).split() if "=" not in t]
    return None


def port_diff(cir_path: str | Path, spice_path: str | Path, top: str) -> Dict[str, Any]:
    """Compare extracted vs reference top-level ports.

    With ``--top_lvl_pins`` every pin label in the layout becomes a
    top-level port. A label for a net the reference netlist treats as
    internal shows up here as an extra port and fails pin matching, with
    nothing in the net-level output pointing at it.
    """
    extracted = _ports_of(Path(cir_path), top)
    reference = _ports_of(Path(spice_path), top)
    if extracted is None or reference is None:
        return {
            "available": False,
            "reason": f"could not find .subckt {top} in "
                      f"{'extracted' if extracted is None else 'reference'} netlist",
        }
    e_set, r_set = set(extracted), set(reference)
    return {
        "available": True,
        "reason": None,
        "extracted": extracted,
        "reference": reference,
        "only_in_layout": sorted(e_set - r_set),
        "only_in_schematic": sorted(r_set - e_set),
        "count_match": len(extracted) == len(reference),
    }


# --------------------------------------------------------------------------
# Combine + render
# --------------------------------------------------------------------------

def analyze(lvsdb: Optional[str | Path],
            cir: Optional[str | Path] = None,
            spice: Optional[str | Path] = None,
            top: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "messages": [],
        "xref": {"available": False, "reason": "no lvsdb", "circuits": []},
        "ports": {"available": False, "reason": "not checked"},
        "first_cause": None,
        "error_count": 0,
        "failing_circuits": [],
    }
    if lvsdb and Path(lvsdb).is_file():
        out["messages"] = parse_lvsdb_messages(lvsdb)
        out["xref"] = parse_lvsdb_xref(lvsdb)
    if cir and spice and top:
        out["ports"] = port_diff(cir, spice, top)

    out["error_count"] = sum(len(c["errors"]) for c in out["messages"])
    out["failing_circuits"] = [
        c["layout"] or c["schematic"]
        for c in out["messages"]
        if c["status"].lower() not in ("match", "matchwithwarning")
    ]

    # ---- pick the single most actionable line ----------------------------
    # Port-count problems come first: they are a whole-cell failure that makes
    # every net look unmatched. After that, prefer the per-circuit log()
    # messages, then fall back to the structured cross-reference. That last
    # fallback matters: when a compare fails at the device or subcircuit level
    # klayout may emit NO per-net log entries at all, so a messages-only
    # heuristic reports "(0 mismatches)" with no cause while the xref section
    # holds the answer.
    ports = out["ports"]

    def _same_name_net_split():
        """A net unmatched on BOTH sides under the SAME name is the strongest
        available signal: the name pairs up but the terminal sets differ, i.e.
        a real connectivity difference on that net. Devices touching it then
        cascade, so this must outrank device mismatches -- otherwise the
        reported cause is a symptom (e.g. "device mismatch $2 <-> MAIN1")
        rather than the bulk/rail net that actually differs."""
        for c in out["xref"].get("circuits", []):
            where = c["layout"] or c["schematic"] or "?"
            lay = set(c["nets_only_in_layout"])
            sch = set(c["nets_only_in_schematic"])
            both = sorted(lay & sch)
            if both:
                orphans = sorted(lay - sch)
                extra = (f"; layout-only net(s) {', '.join(orphans)} suggest a "
                         f"terminal that should join {both[0]} sits on its own net"
                         if orphans else "")
                return (f"{where}: net {', '.join(both)} present on both sides "
                        f"but unmatched - terminal sets differ{extra}")
        return None

    def _first_xref_cause():
        for c in out["xref"].get("circuits", []):
            where = c["layout"] or c["schematic"] or "?"
            if c["subcircuits_mismatched"]:
                s = c["subcircuits_mismatched"][0]
                return (f"{where}: unresolved/unmatched subcircuit "
                        f"{s['schematic'] or s['layout']} "
                        f"({len(c['subcircuits_mismatched'])} total) - a device "
                        f"model emitted as an X-instance with no .subckt body "
                        f"will look like this")
            if c["devices_only_in_schematic"]:
                d = c["devices_only_in_schematic"][0]
                return (f"{where}: {len(c['devices_only_in_schematic'])} "
                        f"schematic device(s) missing from layout, first "
                        f"{d['name']} [{d['class']}]")
            if c["devices_only_in_layout"]:
                d = c["devices_only_in_layout"][0]
                return (f"{where}: {len(c['devices_only_in_layout'])} layout "
                        f"device(s) not in schematic, first {d['name']} "
                        f"[{d['class']}]")
            if c["devices_mismatched"]:
                d = c["devices_mismatched"][0]
                pd = d["param_diff"]
                detail = (", ".join(f"{x['param']} layout={x['layout']:g} "
                                    f"schematic={x['schematic']:g}" for x in pd)
                          if pd else "topology differs, parameters agree")
                return (f"{where}: device mismatch {d['layout']} <-> "
                        f"{d['schematic']} ({detail})")
            if c["pins_mismatched"]:
                x = c["pins_mismatched"][0]
                return (f"{where}: pin mismatch {x['layout']} <-> "
                        f"{x['schematic']}")
            if c["nets_only_in_schematic"] or c["nets_only_in_layout"]:
                return (f"{where}: {len(c['nets_only_in_layout'])} layout / "
                        f"{len(c['nets_only_in_schematic'])} schematic net(s) "
                        f"unmatched")
            if c["status"] not in ("Match", "MatchWithWarning"):
                return f"{where}: circuit pair status {c['status']}"
        return None

    def _first_message_cause():
        for c in out["messages"]:
            if c["status"].lower() in ("match", "matchwithwarning"):
                continue
            where = c["layout"] or c["schematic"]
            if c["infos"]:
                return f"{where}: {c['infos'][0]}"
            if c["errors"]:
                return f"{where}: {c['errors'][0]}"
        return None

    if ports.get("available") and ports.get("only_in_layout"):
        out["first_cause"] = (
            "extra top-level pin(s) in layout: "
            + ", ".join(ports["only_in_layout"])
            + " (label present in GDS but net is internal in the reference netlist)"
        )
    elif ports.get("available") and ports.get("only_in_schematic"):
        out["first_cause"] = (
            "missing top-level pin(s) in layout: "
            + ", ".join(ports["only_in_schematic"])
        )
    else:
        out["first_cause"] = (_same_name_net_split()
                              or _first_message_cause()
                              or _first_xref_cause())

    # Count every issue, not just net-level log entries.
    out["issue_count"] = out["error_count"] + sum(
        len(c[k])
        for c in out["xref"].get("circuits", [])
        for k in ("nets_only_in_layout", "nets_only_in_schematic",
                  "nets_mismatched", "devices_only_in_layout",
                  "devices_only_in_schematic", "devices_mismatched",
                  "pins_mismatched", "subcircuits_mismatched")
    )
    if not out["failing_circuits"]:
        out["failing_circuits"] = [
            (c["layout"] or c["schematic"])
            for c in out["xref"].get("circuits", [])
            if c["status"] not in ("Match", "MatchWithWarning")
        ]
    return out


def render(report: Dict[str, Any], max_items: int = 25) -> str:
    L: List[str] = []
    p = L.append

    p("=" * 72)
    p("LVS MISMATCH DETAIL")
    p("=" * 72)

    if report["first_cause"]:
        p("")
        p("LIKELY ROOT CAUSE")
        p(f"  {report['first_cause']}")
    p("")
    p(f"TOTAL ISSUES: {report.get('issue_count', 0)}")

    ports = report["ports"]
    p("")
    p("TOP-LEVEL PORTS (--top_lvl_pins is active, so labels become pins)")
    if not ports.get("available"):
        p(f"  not checked: {ports.get('reason')}")
    else:
        p(f"  extracted ({len(ports['extracted'])}): {' '.join(ports['extracted'])}")
        p(f"  reference ({len(ports['reference'])}): {' '.join(ports['reference'])}")
        if ports["only_in_layout"]:
            p(f"  EXTRA in layout    : {' '.join(ports['only_in_layout'])}")
        if ports["only_in_schematic"]:
            p(f"  MISSING from layout: {' '.join(ports['only_in_schematic'])}")
        if not ports["only_in_layout"] and not ports["only_in_schematic"]:
            p("  ports agree")

    xr = report["xref"]
    if xr.get("extraction_log"):
        p("")
        p("EXTRACTION LOG")
        for e in xr["extraction_log"]:
            p(f"  [{e['severity']}] {e['message']}")

    p("")
    p("PER-CIRCUIT MESSAGES (innermost circuits first -- fix those; parents inherit)")
    if not report["messages"]:
        p("  none found in lvsdb")
    for c in report["messages"]:
        label = c["layout"] or "(none)"
        sch = c["schematic"] or "(none)"
        st = c["status"]
        if st.lower() in ("match", "matchwithwarning"):
            p(f"  [ok]   {label} <-> {sch}")
            continue
        p(f"  [FAIL] {label} <-> {sch}  ({st})")
        for msg in c["infos"]:
            p(f"           HINT  {msg}")
        shown = c["errors"][:max_items]
        for msg in shown:
            p(f"           error {msg}")
        if len(c["errors"]) > max_items:
            p(f"           ... and {len(c['errors']) - max_items} more errors")
        for msg in c["warnings"][:max_items]:
            p(f"           warn  {msg}")

    if xr.get("available"):
        p("")
        p("CROSS-REFERENCE DETAIL")
        for c in xr["circuits"]:
            buckets = [
                ("devices in layout only", c["devices_only_in_layout"],
                 lambda d: f"{d['name']} [{d['class']}]"),
                ("devices in schematic only", c["devices_only_in_schematic"],
                 lambda d: f"{d['name']} [{d['class']}]"),
                ("device mismatches", c["devices_mismatched"], _fmt_devmm),
                ("nets in layout only", c["nets_only_in_layout"], str),
                ("nets in schematic only", c["nets_only_in_schematic"], str),
                ("pin mismatches", c["pins_mismatched"],
                 lambda x: f"{x['layout']} <-> {x['schematic']}"),
                ("subcircuit mismatches", c["subcircuits_mismatched"],
                 lambda x: f"{x['layout']} <-> {x['schematic']}"),
            ]
            if not any(items for _t, items, _f in buckets):
                continue
            p(f"  circuit {c['layout']} <-> {c['schematic']} ({c['status']})")
            for title, items, fmt in buckets:
                if not items:
                    continue
                p(f"    {title} ({len(items)}):")
                for it in items[:max_items]:
                    p(f"      - {fmt(it)}")
                if len(items) > max_items:
                    p(f"      ... and {len(items) - max_items} more")
    elif xr.get("reason"):
        p("")
        p(f"CROSS-REFERENCE DETAIL unavailable: {xr['reason']}")

    p("")
    p("=" * 72)
    return "\n".join(L)


def _fmt_devmm(d):
    s = f"{d['layout']} <-> {d['schematic']} [{d['class']}]"
    if d["param_diff"]:
        s += "  param diff: " + ", ".join(
            f"{x['param']} layout={x['layout']:g} schematic={x['schematic']:g}"
            for x in d["param_diff"]
        )
    else:
        s += "  (topology differs, parameters agree)"
    return s


def main(argv=None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("lvsdb")
    ap.add_argument("--cir", help="extracted netlist, for the port comparison")
    ap.add_argument("--spice", help="reference netlist, for the port comparison")
    ap.add_argument("--top", help="top cell name")
    ap.add_argument("--json", help="write the structured report here")
    ap.add_argument("--max", type=int, default=25)
    a = ap.parse_args(argv)

    rep = analyze(a.lvsdb, a.cir, a.spice, a.top)
    print(render(rep, a.max))
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2))
    return 1 if rep["failing_circuits"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
