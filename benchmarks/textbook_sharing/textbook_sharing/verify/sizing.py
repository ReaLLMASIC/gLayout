"""Independent sizing check: compare the extracted layout netlist with the logical target.

For every logical MOS (name, d, g, s, b, w_total, l, model) the extracted devices with the same
(model, connectivity signature) are collected; their widths are summed and compared with w_total,
their lengths must all equal l.  This does not rely on LVS tolerance settings.
Extracted netlists come from magic (X-instances, w/l in um) or the gf180 KLayout deck (M-instances, W/L with U suffix).
Net names in the extracted netlist are the layout labels for ports; internal nets are matched through the
port-connected signature (ports only) plus device counts per internal-net class.
"""
from __future__ import annotations
import re
from collections import defaultdict


def _num(v):
    v = v.strip().lower()
    m = re.match(r"([-+]?[\d.]+(?:e[-+]?\d+)?)([a-z]*)", v)
    if not m: return None
    x = float(m.group(1)); s = m.group(2)
    mult = {"u": 1.0, "": 1.0, "n": 1e-3, "m": 1e3, "p": 1e-6}.get(s, 1.0)
    return x * mult


def parse_mos(text: str, models: set):
    devs = []
    for line in text.splitlines():
        t = line.strip()
        if not t or t[0] in "*+.": continue
        parts = t.split()
        if parts[0][0].upper() not in "XM" or len(parts) < 6: continue
        # find model token (first token that is a known model, case-insensitive)
        idx = None
        for i, p in enumerate(parts[1:], 1):
            if p.lower() in models: idx = i; break
        if idx is None or idx < 5: continue
        d, g, s, b = parts[1:5]
        params = {}
        for p in parts[idx + 1:]:
            if "=" in p:
                k, v = p.split("=", 1); params[k.lower()] = _num(v)
        devs.append({"name": parts[0], "model": parts[idx].lower(), "d": d, "g": g, "s": s, "b": b, "w": params.get("w"), "l": params.get("l"), "m": params.get("m", 1.0) or 1.0, "nf": params.get("nf") or params.get("ng") or 1})
    return devs


def canon_nets(devs, ports):
    """Rename internal nets consistently: nets that are ports keep their names; others become int<k> by sorted signature."""
    sig = defaultdict(set)
    for d in devs:
        for t in ("d", "g", "s", "b"):
            sig[d[t]].add((d["model"], "sd" if t in ("d", "s") else t))
    ren = {}
    for n in sorted(sig, key=lambda n: (n in ports, n)):
        if n in ports: ren[n] = n
        else: ren[n] = "int:" + ",".join(sorted(f"{m}.{t}" for m, t in sig[n]))
    return ren


def sizing_check(target_devices, extracted_text, models_map, ports, tol_rel=0.02, tol_abs_um=0.01):
    """target_devices: [{name, model(kind), d,g,s,b, w, l, nf}]; models_map: kind->model name."""
    models = {v.lower() for v in models_map.values()}
    ex = parse_mos(extracted_text, models)
    ren = canon_nets(ex, set(ports))
    # group extracted by (model, canonical nets (unordered s/d))
    groups = defaultdict(list)
    for d in ex:
        key = (d["model"], ren[d["g"]], ren[d["b"]], tuple(sorted((ren[d["d"]], ren[d["s"]]))))
        groups[key].append(d)
    # target canonical signature using the same renaming rule on the target netlist
    tsig = defaultdict(set)
    for t in target_devices:
        for k in ("d", "g", "s", "b"):
            tsig[t[k]].add((models_map[t["model"]].lower(), "sd" if k in ("d", "s") else k))
    tren = {n: (n if n in ports else "int:" + ",".join(sorted(f"{m}.{k}" for m, k in s))) for n, s in tsig.items()}
    tgroups = defaultdict(list)
    for t in target_devices:
        key = (models_map[t["model"]].lower(), tren[t["g"]], tren[t["b"]], tuple(sorted((tren[t["d"]], tren[t["s"]]))))
        tgroups[key].append(t)
    report = {"ok": True, "per_group": [], "extracted_devices": len(ex), "target_devices": len(target_devices)}
    for key, tl in tgroups.items():
        w_target = sum(float(t["w"]) for t in tl); l_target = {round(float(t["l"]), 4) for t in tl}
        el = groups.get(key, [])
        w_ex = sum((d["w"] or 0.0) * (d["m"] or 1.0) for d in el)
        # klayout combined devices report W as total; magic per-finger devices report unit W: both sum correctly
        l_ex = {round(d["l"], 4) for d in el if d["l"] is not None}
        ok_w = abs(w_ex - w_target) <= max(tol_abs_um, tol_rel * w_target)
        ok_l = l_ex == l_target
        ok_n = len(el) > 0
        report["per_group"].append({"key": [k if isinstance(k, str) else list(k) for k in key], "targets": [t["name"] for t in tl], "w_target": w_target, "w_extracted": round(w_ex, 4),
                                    "l_target": sorted(l_target), "l_extracted": sorted(l_ex), "n_extracted": len(el), "ok": ok_w and ok_l and ok_n})
        if not (ok_w and ok_l and ok_n): report["ok"] = False
    extra = [k for k in groups if k not in tgroups]
    if extra:
        report["ok"] = False; report["extra_extracted_groups"] = [[str(x) for x in k] for k in extra]
    report["status"] = "passed" if report["ok"] else "constraints_failed"
    return report
