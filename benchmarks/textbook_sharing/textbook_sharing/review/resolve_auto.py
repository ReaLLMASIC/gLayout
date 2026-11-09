"""Resolve open visual-review flags (verdict suspicious/fail without a resolution) by objective checks.  A flag is marked
resolved_ok only when ALL hold: official DRC passed, LVS passed, extraction reports no floating conductor, every gate
pad (contact on poly) reaches a via1, every met2 piece reaches a via2.  Anything else stays open and is listed for manual
inspection (zoomed render).  usage: python -m textbook_sharing.review.resolve_auto --out <results>/analysis/resolve_auto_<tag>.json [--by NAME]"""
import json, glob, argparse
from pathlib import Path
from textbook_sharing import paths


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--by", default="maintainer"); a = ap.parse_args()
    from textbook_sharing.review.check_connectivity import analyse
    from textbook_sharing.review.visual_review import resolve
    done = {}; open_ = {}
    for rp in glob.glob(str(paths.RUNS / "**" / "review_record.json"), recursive=True):
        r = json.load(open(rp)); v = r["visual"]
        if v["verdict"] not in ("suspicious", "fail") or v.get("reused_from") or r.get("visual_resolution"): continue
        run = Path(rp).parent.parent.parent; res = json.load(open(run / "result.json"))
        c = analyse(str(paths.resolve(r["gds"])), r["pdk"])
        ok = (res["verify"].get("drc") == "passed" and res["verify"].get("lvs") == "passed" and not (res.get("pex_counts") or {}).get("floating_nodes")
              and c["gate_pads_without_via1"] == 0 and not c["met2_without_via2"])
        rec = {"run": paths.rel(run), "verdict": v["verdict"], "issues": v.get("issue_locations"), "drc": res["verify"].get("drc"), "lvs": res["verify"].get("lvs"),
               "pex_floating": (res.get("pex_counts") or {}).get("floating_nodes"), "gate_pads_without_via1": c["gate_pads_without_via1"], "met2_without_via2": c["met2_without_via2"]}
        if ok and v["verdict"] == "suspicious":
            resolve(r["review_id"], "resolved_ok", "Objective checks: official DRC and LVS passed; extraction reports no floating conductor; every contact on poly reaches a via1 through its first-metal component; every met2 piece reaches a via2 (no dangling stub). The flagged structure is connected.",
                    "textbook_sharing.review.resolve_auto (check_connectivity gate-pad / met2-via2 checks, pex floating-node list, verify/drc, verify/lvs)", by=a.by)
            done[r["review_id"]] = rec
        else:
            open_[r["review_id"]] = rec
    json.dump({"resolved": done, "open": open_}, open(a.out, "w"), indent=1)
    print("resolved", len(done), "open", len(open_))
    for k, v in open_.items(): print("  OPEN", k, v["run"], v["verdict"], v["issues"][:1] if v["issues"] else None)


if __name__ == "__main__":
    main()
