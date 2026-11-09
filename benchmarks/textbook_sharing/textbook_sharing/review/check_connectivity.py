"""Objective connectivity checks used to resolve visual-review flags (independent of DRC/LVS, which are also reported).
For one GDS:
  * conductor components: merged shapes of active, tap, poly, met1, met2, met3 joined through cont (active/tap/poly <->
    met1), via1 (met1 <-> met2) and via2 (met2 <-> met3); a component that carries no met3 pin/label shape is FLOATING;
  * gate pads: contacts on poly (not on active/tap) whose met1 component has no via1;
  * met2 pieces without a via2 (stubs that never reach a trunk).
Passive bodies (resistor poly, MIM plates) are part of the poly / metal layers or of PDK-specific layers that are not
traced; a resistor's two heads are joined through its poly body.
usage: python -m textbook_sharing.review.check_connectivity <review_id>... --out <json>"""
import json, glob, argparse
from pathlib import Path
from textbook_sharing import paths


DROP = ()


def analyse(gds, pdkname):
    import klayout.db as kdb
    from textbook_sharing.run_case import pdk_obj
    from glayout.sharing import rules_for
    L = rules_for(pdk_obj(pdkname)).layers
    ly = kdb.Layout(); ly.read(gds); top = ly.top_cell(); dbu = ly.dbu
    def reg(name):
        spec = L.get(name)
        if spec is None: return kdb.Region()
        li = ly.find_layer(*spec)
        return kdb.Region(top.begin_shapes_rec(li)).merged() if li is not None else kdb.Region()
    R = {n: reg(n) for n in ("active", "tap", "poly", "cont", "met1", "via1", "met2", "via2", "met3", "met3_pin", "met3_label")}
    R["active"] = (R["active"] - R["poly"]).merged()          # source/drain regions only (channels cut by the gates)
    for n in DROP: R[n] = kdb.Region()                         # negative control
    # nodes: every merged polygon of a conductor layer
    nodes = []
    for lay in ("active", "tap", "poly", "met1", "met2", "met3"):
        for p in R[lay].each(): nodes.append((lay, kdb.Region(p)))
    parent = list(range(len(nodes)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def union(i, j): parent[find(i)] = find(j)
    idx = {lay: [i for i, (l, _) in enumerate(nodes) if l == lay] for lay in ("active", "tap", "poly", "met1", "met2", "met3")}
    def join(cut, lower_layers, upper):
        for c in R[cut].each():
            cr = kdb.Region(c)
            lows = [i for lay in lower_layers for i in idx[lay] if not nodes[i][1].interacting(cr).is_empty()]
            ups = [i for i in idx[upper] if not nodes[i][1].interacting(cr).is_empty()]
            for a in lows + ups[1:]:
                if ups: union(a, ups[0])
    join("cont", ("active", "tap", "poly"), "met1"); join("via1", ("met1",), "met2"); join("via2", ("met2",), "met3")
    pins = R["met3_pin"] + R["met3_label"]
    comps = {}
    for i in range(len(nodes)): comps.setdefault(find(i), []).append(i)
    floating = []
    for root, members in comps.items():
        has_pin = any(nodes[i][0] == "met3" and not nodes[i][1].interacting(pins).is_empty() for i in members) if not pins.is_empty() else any(nodes[i][0] == "met3" for i in members)
        if not has_pin:
            bb = kdb.Region(); [bb.insert(nodes[i][1]) for i in members]; b = bb.bbox()
            floating.append({"layers": sorted({nodes[i][0] for i in members}), "bbox_um": [round(b.left * dbu, 3), round(b.bottom * dbu, 3), round(b.right * dbu, 3), round(b.top * dbu, 3)]})
    gc = R["cont"].interacting(R["poly"]).not_interacting(R["active"]).not_interacting(R["tap"])
    unwired = [c for c in gc.each() if R["via1"].interacting(R["met1"].interacting(kdb.Region(c))).is_empty()]
    m2_no_v2 = [p.bbox() for p in R["met2"].each() if R["via2"].interacting(kdb.Region(p)).is_empty()]
    return {"components": len(comps), "floating_components": floating, "gate_pads": gc.count(), "gate_pads_without_via1": len(unwired),
            "met2_without_via2": [[round(b.left * dbu, 2), round(b.bottom * dbu, 2), round(b.right * dbu, 2), round(b.top * dbu, 2)] for b in m2_no_v2]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("ids", nargs="+"); ap.add_argument("--out", required=True); ap.add_argument("--drop", default=""); a = ap.parse_args()
    global DROP; DROP = tuple(x for x in a.drop.split(",") if x)
    want = set(a.ids); out = {}
    for rp in glob.glob(str(paths.RUNS / "**" / "review_record.json"), recursive=True):
        r = json.load(open(rp))
        if r["review_id"] not in want: continue
        res = json.load(open(Path(rp).parent.parent.parent / "result.json"))
        c = analyse(str(paths.resolve(r["gds"])), r["pdk"]); c.update({"run": paths.rel(Path(rp).parent.parent.parent), "drc": res["verify"].get("drc"), "lvs": res["verify"].get("lvs"),
                                                  "primary_status": res.get("primary_status")})
        out[r["review_id"]] = c
        print(r["review_id"], c["run"], "components", c["components"], "floating", c["floating_components"][:3], "pads w/o via1", c["gate_pads_without_via1"],
              "met2 w/o via2", c["met2_without_via2"][:3], c["drc"], c["lvs"], flush=True)
    json.dump(out, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
