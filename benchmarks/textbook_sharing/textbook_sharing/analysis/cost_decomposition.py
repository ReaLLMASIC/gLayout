"""Physical cost of sharing on the main grid (measured geometry; every pair = one case, one sharing mode vs. the
independent reference of the same case, both built by the same assembler).
  A0 = W0*H0 (reference), A1 = W1*H1;  dW = W0 - W1 (width saved),  dH = H1 - H0 (height added)
  A1 = (W0 - dW)(H0 + dH)  ->  sharing reduces area  iff  H0*dW > (W0 - dW)*dH
dW is split into: group width change of the row that sets the DUT width (shared diffusion / fewer island gaps / pad
overhang) and the rest (row-dominance changes, x shifts).  dH is split into MOS row height change (strap bands, pad
levels) and routing-channel height change (tracks).  passive_dominated: the widest row is a passive row in both layouts
(so MOS width savings cannot reduce the DUT width).
Area terms (exact: they add up to A1 - A0), with S = the largest row span (cells + tap strips):
  wider_row        = (S1 - S0) * H1            the row that sets the width got wider (its cells are wider)
  stub_separation  = ((W1 - W0) - (S1 - S0)) * H1
                                               width added outside the rows: a row shifted sideways, or a net split into
                                               two trunks joined beyond the row ends, to keep the metal-2 stubs of two
                                               rows apart in a channel
  taller_mos_rows  = W0 * dH_mos_rows,  routing_tracks = W0 * dH_channels,  other_height = W0 * dH_other
For every area increase the positive terms are listed and the largest one is its primary mechanism.
Classes: positive (A1 < A0 by > 0.5 %), negative (A1 > A0 by > 0.5 %), neutral.  Only pairs where both layouts pass
every automatic stage are used for area statements; all pairs are listed.
usage: python -m textbook_sharing.analysis.cost_decomposition --out <results>/analysis/cost_decomposition.json"""
import json, glob, argparse, collections, statistics
from pathlib import Path
from textbook_sharing import paths
DEAD = 0.005
MODES = ("diffusion_only", "gate_only", "combined")


def span(row):
    return row["width"] + 2 * row["tap_extent"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
    rows = []
    for ind in sorted(glob.glob(str(paths.GRID_RUNS / "*/*/*/independent/result.json"))):
        b = json.load(open(ind)); cid, pdk, size = Path(ind).parts[-5:-2]
        if not b.get("assembly_stats"): continue
        sb = b["assembly_stats"]
        for m in MODES:
            f = Path(ind).parent.parent / m / "result.json"
            if not f.exists(): continue
            r = json.load(open(f))
            if r.get("primary_status") == "NA" or not r.get("assembly_stats"): continue
            s1 = r["assembly_stats"]
            W0, H0, W1, H1 = sb["width"], sb["height"], s1["width"], s1["height"]
            A0, A1 = W0 * H0, W1 * H1; dW, dH = W0 - W1, H1 - H0
            rd0, rd1 = sb["row_dims"], s1["row_dims"]
            w0i = max(range(len(rd0)), key=lambda i: span(rd0[i])); w1i = max(range(len(rd1)), key=lambda i: span(rd1[i]))
            mos_dh = sum(x["height"] - y["height"] for x, y in zip(rd1, rd0) if x["kind"] in ("n", "p"))
            ch_dh = sum(s1["channel_heights"]) - sum(sb["channel_heights"])
            mos_spans0 = {x["kind"]: span(x) for x in rd0 if x["kind"] in ("n", "p")}; mos_spans1 = {x["kind"]: span(x) for x in rd1 if x["kind"] in ("n", "p")}
            row_dw = {k: round(mos_spans0[k] - mos_spans1.get(k, mos_spans0[k]), 4) for k in mos_spans0}
            rel = A1 / A0 - 1
            cls = "positive" if rel < -DEAD else "negative" if rel > DEAD else "neutral"
            dS = round(max(map(span, rd1)) - max(map(span, rd0)), 4); r4 = lambda v: round(v, 4)   # lengths on the 0.1 nm scale
            terms = {"wider_row": dS * H1, "stub_separation": r4(W1 - W0 - dS) * H1, "taller_mos_rows": W0 * r4(mos_dh),
                     "routing_tracks": W0 * r4(ch_dh), "other_height": W0 * r4(dH - mos_dh - ch_dh)}
            rows.append({"case": f"{cid}_{pdk}_{size}", "topology": cid, "pdk": pdk, "size": size, "mode": m,
                         "both_auto_passed": b.get("primary_status") == "auto_passed" and r.get("primary_status") == "auto_passed",
                         "status_ref": b.get("primary_status"), "status_mode": r.get("primary_status"),
                         "A0": round(A0, 3), "A1": round(A1, 3), "rel": round(rel, 5), "class": cls, "W0": W0, "H0": H0, "W1": W1, "H1": H1,
                         "dW": round(dW, 4), "dH": round(dH, 4), "condition_lhs_H0dW": round(H0 * dW, 4), "condition_rhs_W1dH": round((W0 - dW) * dH, 4),
                         "dH_mos_rows": round(mos_dh, 4), "dH_channels": round(ch_dh, 4), "dH_other": round(dH - mos_dh - ch_dh, 4),
                         "row_span_saving": row_dw, "max_mos_row_span_saving": max(row_dw.values()) if row_dw else 0.0,
                         "widest_row_ref": rd0[w0i]["kind"], "widest_row_mode": rd1[w1i]["kind"],
                         "passive_dominated": rd0[w0i]["kind"] == "passive" and rd1[w1i]["kind"] == "passive",
                         "area_terms": {k: round(v, 3) for k, v in terms.items()},
                         "channel_strategy_ref": sb.get("channel_strategy"), "channel_strategy_mode": s1.get("channel_strategy"),
                         "gds_ref": b.get("gds"), "gds_mode": r.get("gds"), "geometry_hash_ref": b.get("geometry_hash"), "geometry_hash_mode": r.get("geometry_hash"),
                         "geometry_identical": b.get("geometry_hash") == r.get("geometry_hash")})
    ok = [x for x in rows if x["both_auto_passed"]]
    def summ(xs):
        c = collections.Counter(x["class"] for x in xs)
        rel = [x["rel"] for x in xs]
        return {"n": len(xs), "classes": dict(c), "mean_rel": statistics.mean(rel) if rel else None, "median_rel": statistics.median(rel) if rel else None,
                "min_rel": min(rel) if rel else None, "max_rel": max(rel) if rel else None,
                "passive_dominated": sum(x["passive_dominated"] for x in xs), "geometry_identical_to_ref": sum(x["geometry_identical"] for x in xs)}
    by_mode = {m: summ([x for x in ok if x["mode"] == m]) for m in MODES}
    by_topo = {t: {m: summ([x for x in ok if x["topology"] == t and x["mode"] == m]) for m in MODES} for t in sorted({x["topology"] for x in ok})}
    by_pdk = {p: {m: summ([x for x in ok if x["pdk"] == p and x["mode"] == m]) for m in MODES} for p in ("sky130", "gf180", "ihp130")}
    # area increases: which terms add area, and the largest one
    neg = [x for x in ok if x["class"] == "negative"]
    for x in neg:
        pos = {k: v for k, v in x["area_terms"].items() if v > 1e-6}
        x["increase_terms"] = sorted(pos, key=lambda k: -pos[k]); x["primary_mechanism"] = x["increase_terms"][0]
    terms = ("routing_tracks", "stub_separation", "wider_row", "taller_mos_rows", "other_height")
    mech = {"n": len(neg), "by_primary": dict(collections.Counter(x["primary_mechanism"] for x in neg)),
            "with_term": {t: sum(t in x["increase_terms"] for x in neg) for t in terms},
            "tracks_and_stub_separation": sum({"routing_tracks", "stub_separation"} <= set(x["increase_terms"]) for x in neg),
            "assembly_only": sum(set(x["increase_terms"]) <= {"routing_tracks", "stub_separation", "other_height"} for x in neg),
            "pairs": [{k: x[k] for k in ("case", "mode", "rel", "dW", "dH", "area_terms", "increase_terms", "primary_mechanism",
                                         "channel_strategy_ref", "channel_strategy_mode", "row_span_saving")} for x in sorted(neg, key=lambda x: -x["rel"])]}
    # examples: largest saving, largest loss, a passive-dominated pair (same scale figures are made from these)
    ex = {}
    pos = sorted([x for x in ok if x["class"] == "positive"], key=lambda x: x["rel"])
    if pos: ex["positive"] = pos[0]
    if neg: ex["negative"] = sorted(neg, key=lambda x: -x["rel"])[0]
    pdom = sorted([x for x in ok if x["passive_dominated"] and x["max_mos_row_span_saving"] > 0.5], key=lambda x: -x["max_mos_row_span_saving"])
    if pdom: ex["passive_dominated"] = pdom[0]
    out = {"n_pairs_all": len(rows), "n_pairs_both_auto_passed": len(ok), "by_mode": by_mode, "by_topology": by_topo, "by_pdk": by_pdk,
           "increase_mechanisms": mech, "examples": ex, "rows": rows, "dead_band": DEAD}
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("n_pairs_all", "n_pairs_both_auto_passed", "by_mode")}, indent=1))
    print(json.dumps({k: v for k, v in mech.items() if k != "pairs"}))
    for k, v in ex.items(): print(k, v["case"], v["mode"], v["rel"], "dW", v["dW"], "dH", v["dH"], "pdom", v["passive_dominated"])


if __name__ == "__main__":
    main()
