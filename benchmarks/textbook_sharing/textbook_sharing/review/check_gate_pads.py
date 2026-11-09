"""Objective check for the visual-review flag "gate contact pad without via": in a GDS, every contact that sits on poly
(and not on active) must belong to a first-metal component that also touches a via1 (i.e. the pad is wired up the
stack).  Layer names come from glayout.sharing.rules (cont, poly, active, met1, via1 of the PDK mapping).
usage: python -m textbook_sharing.review.check_gate_pads <review_id>... --out <json>   (looks the records up under the run folder)"""
import json, glob, argparse
from pathlib import Path
from textbook_sharing import paths


def check(gds, pdkname):
    import klayout.db as kdb
    from textbook_sharing.run_case import pdk_obj
    from glayout.sharing import rules_for
    L = rules_for(pdk_obj(pdkname)).layers
    ly = kdb.Layout(); ly.read(gds); top = ly.top_cell()
    def reg(name):
        li = ly.find_layer(*L[name]) if L.get(name) is not None else None
        return kdb.Region(top.begin_shapes_rec(li)).merged() if li is not None else kdb.Region()
    poly, act, cont, m1, v1 = reg("poly"), reg("active"), reg("cont"), reg("met1"), reg("via1")
    tap = reg("tap") if L.get("tap") else kdb.Region()
    gc = cont.interacting(poly).not_interacting(act).not_interacting(tap)
    bad = []; n = 0
    for c in gc.each():
        n += 1
        comp = m1.interacting(kdb.Region(c))
        if comp.is_empty() or v1.interacting(comp).is_empty():
            b = c.bbox(); bad.append({"x": round(b.center().x * ly.dbu, 3), "y": round(b.center().y * ly.dbu, 3), "met1": not comp.is_empty()})
    return {"gate_contacts": n, "wired_to_via1": n - len(bad), "unwired": bad}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("ids", nargs="+"); ap.add_argument("--out", required=True); a = ap.parse_args()
    want = set(a.ids); out = {}
    for rp in glob.glob(str(paths.RUNS / "**" / "review_record.json"), recursive=True):
        r = json.load(open(rp))
        if r["review_id"] in want:
            res = json.load(open(Path(rp).parent.parent.parent / "result.json"))
            c = check(str(paths.resolve(r["gds"])), r["pdk"]); c.update({"run": paths.rel(Path(rp).parent.parent.parent), "drc": res["verify"].get("drc"), "lvs": res["verify"].get("lvs")})
            out[r["review_id"]] = c; print(r["review_id"], c["gate_contacts"], c["wired_to_via1"], c["unwired"][:3], c["drc"], c["lvs"])
    json.dump(out, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
