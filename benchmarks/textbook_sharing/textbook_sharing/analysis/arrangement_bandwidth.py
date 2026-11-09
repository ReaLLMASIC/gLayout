"""Electrical cost of finger arrangement in the selection catalogue: per task and per group axis value, status counts
and mean post-layout f3db / gain (all evaluated candidates).  Written for the C16 bandwidth failures (resistor-loaded
pair: f3db ~ 1/(2 pi R_L C_out), interleaving lengthens the output nets).
usage: python -m textbook_sharing.analysis.arrangement_bandwidth --topology C16 --out <results>/analysis/arrangement_bandwidth_C16.json"""
import json, glob, argparse, collections, statistics
from pathlib import Path
from textbook_sharing import paths


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--topology", default="C16"); ap.add_argument("--out", required=True); a = ap.parse_args()
    out = {}
    for td in sorted(glob.glob(str(paths.SELECTION_RUNS / f"{a.topology}_*"))):
        cat = json.load(open(Path(td) / "catalogue.json")); agg = collections.defaultdict(lambda: {"status": collections.Counter(), "f3db": [], "gain_lf": [], "area": []})
        for cid, e in cat["entries"].items():
            rp = Path(td) / cid / "result.json"
            if not rp.exists(): continue
            r = json.load(open(rp)); m = (r.get("postsim") or {}).get("measures") or {}
            for gi, pid in enumerate(e["plan_ids"]):
                tup = next((t for p, t in cat["tables"][gi]["unique"] if p == pid), None)
                for ax in ("arrangement", "orientation", "diffusion", "gate", "strap_start"):
                    k = f"group{gi}.{ax}={tup[ax] if tup else 'independent'}"
                    agg[k]["status"][r["primary_status"]] += 1
                    if m.get("f3db"): agg[k]["f3db"].append(m["f3db"])
                    if m.get("gain_lf") is not None: agg[k]["gain_lf"].append(m["gain_lf"])
                    if r.get("area_um2"): agg[k]["area"].append(r["area_um2"])
        out[Path(td).name] = {k: {"status": dict(v["status"]), "mean_f3db_MHz": statistics.mean(v["f3db"]) / 1e6 if v["f3db"] else None,
                                  "mean_gain_dB": statistics.mean(v["gain_lf"]) if v["gain_lf"] else None, "mean_area_um2": statistics.mean(v["area"]) if v["area"] else None}
                              for k, v in sorted(agg.items())}
    json.dump(out, open(a.out, "w"), indent=1)
    for t, d in out.items():
        print(t); [print("  ", k, v["status"], None if v["mean_f3db_MHz"] is None else round(v["mean_f3db_MHz"], 1)) for k, v in d.items() if ".arrangement=" in k]


if __name__ == "__main__":
    main()
