"""Count ledger (machine-readable + reader table).  Every class is mutually exclusive; totals are asserted.
Case level (648 requested = 18 topologies x 3 PDKs x 12 size points):
  requested = parameter_illegal + duplicate + distinct_legal
  distinct_legal = schematic_not_qualified + qualified
  qualified = reference_first_failure[stage] (independent-mode run of the main grid; or not_run) + reference_auto_passed
  formal entry = reference_auto_passed (diagnostic set = everything else that was requested, with its reason)
Mode level (main grid, qualified cases x 4 modes): NA (mode not applicable) / not_run / first failing stage / auto_passed,
  plus geometry-identical-to-another-mode counts (same GDS content apart from the cell name).
Candidate level (selection): per task raw tuples / static illegal / equivalent duplicates / unique per group,
  global product, selected, evaluated, first failing stage / auto_passed.
Visual review is a separate dimension: pending / pass / suspicious / fail, and its intersection with auto_passed.
usage: python -m textbook_sharing.analysis.ledger -> <results>/count_ledger.json + count_ledger.md"""
from __future__ import annotations
import json, glob, collections, hashlib
from pathlib import Path
from textbook_sharing import paths
STAGES = ["rejected_plan", "build_failed", "drc_failed", "lvs_failed", "constraints_failed", "pex_failed", "simulation_failed", "spec_failed", "physical_review_failed"]


def review_verdict(res):
    rp = paths.resolve(res["gds"]).parent / "verify" / "review" / "review_record.json" if res.get("gds") else None
    if rp is None: return "no_record"
    if rp.exists():
        rec = json.load(open(rp)); v = (rec.get("visual") or {}).get("verdict", "review_pending")
        if v in ("suspicious", "fail"):  # the reviewer's verdict is kept; the objective resolution is shown next to it
            v += "(" + (rec.get("visual_resolution") or {}).get("outcome", "unresolved") + ")"
        return v
    return "no_record"


def geometry_hash(gds):
    """GDS content hash with the cell name removed (modes that produced identical geometry share it)."""
    try:
        import klayout.db as kdb
        ly = kdb.Layout(); ly.read(gds); top = ly.top_cell(); h = hashlib.sha256()
        for li in sorted(ly.layer_indexes(), key=lambda i: (ly.get_info(i).layer, ly.get_info(i).datatype)):
            info = ly.get_info(li); reg = kdb.Region(top.begin_shapes_rec(li)); reg.merge()
            h.update(f"{info.layer}/{info.datatype}:".encode())
            for poly in sorted(str(p) for p in reg.each()): h.update(poly.encode())
        return h.hexdigest()[:16]
    except Exception as e:
        return None


def main():
    by_id = {r["case_id"]: r for r in json.load(open(paths.RESULTS / "case_build.json"))}   # one record per request
    req = list(by_id.values())
    L = {"requested": len(req)}
    st = collections.Counter(r["stage"] for r in req)
    L["parameter_illegal"] = st["parameter_illegal"]; L["duplicate"] = st["duplicate"]
    L["distinct_legal"] = st["schematic_not_qualified"] + st["qualified"]
    L["schematic_not_qualified"] = st["schematic_not_qualified"]; L["qualified"] = st["qualified"]
    assert L["requested"] == L["parameter_illegal"] + L["duplicate"] + L["distinct_legal"]
    ref = collections.Counter(); formal = []; diag = []; mode_rows = collections.Counter(); mode_by = collections.defaultdict(collections.Counter)
    identical = collections.Counter(); review = collections.Counter(); review_auto = collections.Counter()
    for r in req:
        if r["stage"] != "qualified":
            diag.append({"case_id": r["case_id"], "reason": r["stage"], "detail": (r.get("derivation") or {}).get("reason") or "; ".join((r.get("qualification") or {}).get("reasons", [])[:3]) or r.get("duplicate_of")}); continue
        base = paths.GRID_RUNS / r["circuit_id"] / r["pdk"] / r["size"]
        rr = base / "independent" / "result.json"
        s = json.load(open(rr)).get("primary_status") if rr.exists() else "not_run"
        ref[s] += 1
        if s == "auto_passed": formal.append(r["case_id"])
        else: diag.append({"case_id": r["case_id"], "reason": "reference_" + s})
        hashes = {}
        for m in ("independent", "diffusion_only", "gate_only", "combined"):
            mp = base / m / "result.json"
            ms = json.load(open(mp)) if mp.exists() else {"primary_status": "not_run"}
            mode_rows[ms["primary_status"]] += 1; mode_by[m][ms["primary_status"]] += 1
            if ms.get("gds"):
                v = review_verdict(ms); review[v] += 1
                if ms["primary_status"] == "auto_passed": review_auto[v] += 1
                gp = paths.resolve(ms["gds"])
                gh = ms.get("geometry_hash") or (geometry_hash(str(gp)) if gp.exists() else None); hashes[m] = gh
        if hashes:
            seen = {}
            for m, gh in hashes.items():
                if gh and gh in seen: identical[f"{m}=={seen[gh]}"] += 1
                else: seen[gh] = m
    L["reference"] = dict(ref); L["formal_entries"] = len(formal); L["diagnostic"] = len(diag)
    assert L["qualified"] == sum(ref.values())
    assert L["requested"] == L["formal_entries"] + L["diagnostic"]
    L["mode_rows"] = {"total": sum(mode_rows.values()), "by_status": dict(mode_rows), "by_mode": {m: dict(c) for m, c in mode_by.items()},
                      "geometry_identical_pairs": dict(identical)}
    L["visual_review_main_grid"] = {"all_kept_gds": dict(review), "auto_passed_gds": dict(review_auto)}
    # candidates
    cand = {"tasks": 0, "per_task": {}}
    agg = collections.Counter()
    for td in sorted(glob.glob(str(paths.SELECTION_RUNS / "*/catalogue.json"))):
        cat = json.load(open(td)); tdir = Path(td).parent; cand["tasks"] += 1
        ev = collections.Counter(); rv = collections.Counter()
        for cid in cat["entries"]:
            rp = tdir / cid / "result.json"
            if rp.exists():
                rs = json.load(open(rp)); ev[rs.get("primary_status")] += 1
                if rs.get("gds"): rv[review_verdict(rs)] += 1
            else: ev["not_run"] += 1
        cand["per_task"][cat["task_id"]] = {"ledger": cat["ledger"], "evaluated": dict(ev), "review": dict(rv)}
        agg["selected"] += cat["ledger"]["selected_for_evaluation"]
        for k, v in ev.items(): agg[f"eval:{k}"] += v
        for k, v in rv.items(): agg[f"review:{k}"] += v
    cand["totals"] = dict(agg)
    out = paths.RESULTS; out.mkdir(parents=True, exist_ok=True)
    json.dump({"cases": L, "formal_entries": formal, "diagnostic": diag, "candidates": cand}, open(out / "count_ledger.json", "w"), indent=1)
    md = ["# Count ledger", "", "| level | count |", "|---|---|"]
    for k in ("requested", "parameter_illegal", "duplicate", "distinct_legal", "schematic_not_qualified", "qualified", "formal_entries", "diagnostic"):
        md.append(f"| {k} | {L[k]} |")
    md += ["", "reference (independent mode) first status: " + json.dumps(dict(ref)), "", "mode rows: " + json.dumps(L["mode_rows"]["by_status"]),
           "", "selection candidates: " + json.dumps(cand["totals"])]
    (out / "count_ledger.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
