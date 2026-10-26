"""Readers for the actual retained Magic/Netgen reports and literal RC netlists."""
import math
import re


def duplicate_subcircuits(text):
    """SPICE subcircuit identifiers share one case-insensitive namespace."""
    seen=set();duplicates=set()
    for line in text.splitlines():
        fields=line.split()
        if len(fields)>1 and fields[0].lower()==".subckt":
            name=fields[1].lower()
            if name in seen:duplicates.add(name)
            seen.add(name)
    return sorted(duplicates)


def magic_drc_report(text):
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    header=re.fullmatch(r"(\S+) count:\s*(.*)",lines[0]) if lines else None
    if not header or len(lines)<2 or lines[1]!="----------------------------------------":
        return {"is_clean":False,"error_count":None,"reason":"unrecognized_or_incomplete_report"}
    body=[s for s in lines[2:] if s!="----------------------------------------"]
    boxes=sum(bool(re.fullmatch(r"(?:[-+]?\d+(?:\.\d+)?um\s*){4}",s)) for s in body)
    counter=header[2]
    numeric_count=int(counter) if counter.isdigit() else None
    clean=not body and counter=="0"
    return {"is_clean":clean,"error_count":numeric_count if numeric_count is not None else (boxes or None),
            "coordinate_boxes":boxes,
            "reason":None if clean else "violations_or_unrecognized_report_body"}


def netgen_lvs_report(text):
    matched=bool(re.search(r"Final result:\s*Circuits match uniquely\.",text))
    disconnected=sorted(set(re.findall(r"disconnected node:\s*(\S+)",text,re.I)))
    properties="Property errors were found." in text
    mismatch=bool(re.search(r"Top level cell failed pin matching|Netlists do not match",text))
    return {"is_clean":matched and not properties and not mismatch and not disconnected,
            "matched_uniquely":matched,"property_errors":properties,
            "disconnected_nodes":disconnected,"topology_mismatch":mismatch}


def spice_literal(value):
    match=re.fullmatch(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)([a-zA-Z]*)",value)
    if not match:
        raise ValueError("Not a literal SPICE number: "+value)
    suffix=match[2].lower()
    scales={"":1,"t":1e12,"g":1e9,"meg":1e6,"k":1e3,"m":1e-3,"u":1e-6,"n":1e-9,"p":1e-12,"f":1e-15}
    if suffix not in scales:
        raise ValueError("Unsupported extracted element suffix: "+suffix)
    result=float(match[1])*scales[suffix]
    if not math.isfinite(result):
        raise ValueError("Nonfinite extracted element")
    return result


def rc_netlist_inventory(text, top_cell, expected_ports):
    counts={k:0 for k in ["R","C","X","M"]}
    positive={k:0 for k in ["R","C"]}
    invalid=[];ports=None
    for line in text.splitlines():
        fields=line.split()
        if not fields or fields[0].startswith(("*",";")):
            continue
        if fields[0].lower()==".subckt" and fields[1].lower()==top_cell.lower():
            ports=fields[2:]
        kind=fields[0][0].upper()
        if kind not in counts:
            continue
        counts[kind]+=1
        if kind in positive:
            try:
                value=spice_literal(fields[3])
                if value<0:
                    invalid.append(fields[0])
                positive[kind]+=value>0
            except (IndexError,ValueError):
                invalid.append(fields[0])
    interface_valid=(ports is not None and len(ports)==len(expected_ports)
                     and {p.upper() for p in ports}=={p.upper() for p in expected_ports})
    duplicates=duplicate_subcircuits(text)
    return {"top_cell":top_cell,"ports":ports,"counts":counts,"positive_elements":positive,
            "duplicate_subcircuits":duplicates,
            "invalid_elements":invalid,"interface_valid":interface_valid,
            "has_real_RC":interface_valid and not invalid and not duplicates and all(positive[k]>0 for k in positive)}
