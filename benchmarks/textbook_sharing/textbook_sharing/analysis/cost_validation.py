"""Validate the cost rule (cost.py) on main-grid runs: for every case whose independent run produced geometry and every
other mode that produced geometry, predict the mode's area from its plans + the independent run's assembly only, and
compare with the measured bounding-box area.  Reports sign accuracy of (A_mode - A_independent) with a dead band, and
every sign error with its type.  usage: python -m textbook_sharing.analysis.cost_validation --sizes sW1_sL1,sW1_sL1.5 --out <json>"""
from __future__ import annotations
import json, glob, argparse, collections
from pathlib import Path
from textbook_sharing import paths
DEAD = 0.005      # |relative change| below 0.5 % counts as "no change"


def sign(x):
    return 0 if abs(x) < DEAD else (1 if x > 0 else -1)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sizes", default=None); ap.add_argument("--out", required=True); ap.add_argument("--channel-rule", default=None); a = ap.parse_args()
    from textbook_sharing.run_case import load_case_dir, pdk_obj
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.layout import device_specs, sharing_groups
    from glayout.sharing import SharingPlan, rules_for
    from textbook_sharing.selection import cost
    from textbook_sharing.layout import build
    sizes = a.sizes.split(",") if a.sizes else None
    rows = []; model_mismatch = []
    for ind in sorted(glob.glob(str(paths.GRID_RUNS / "*/*/*/independent/result.json"))):
        base = json.load(open(ind)); parts = Path(ind).parts; cid, pdkn, size = parts[-5], parts[-4], parts[-3]
        if sizes and size not in sizes: continue
        if not base.get("assembly_stats") or "row_dims" not in base["assembly_stats"]: continue
        case, cj = load_case_dir(base["case_dir"]); circ = CIRCUITS[cid]; pdk = pdk_obj(pdkn); R = rules_for(pdk)
        groups = sharing_groups(device_specs(circ, case.sizing))
        base_plans = [SharingPlan.from_json(ap_["plan"]) for ap_ in base["applied_plans"]]
        # the estimate procedure builds the baseline once (grid runs predate the channel_net_sources stat): rebuild it
        # and confirm it is the same assembly
        rb = build(pdk, circ, case.sizing, mode="independent", name=f"{cid}_{pdkn}_{size}_costbase".replace(".", "p"))
        if abs(rb["assembly_stats"]["area_um2"] - base["assembly_stats"]["area_um2"]) > 1e-3:
            raise SystemExit(f"rebuilt baseline differs for {cid} {pdkn} {size}")
        bstats = rb["assembly_stats"]
        Nmodel = cost.channel_nets(bstats, groups, base_plans, [f"grp{i}" for i in range(len(groups))])
        Nreal = [set() for _ in Nmodel]
        for d in bstats["channel_net_sources"]["cells"].values():
            for ch, nets in d.items(): Nreal[int(ch)] |= set(nets)
        for ch, nets in bstats["channel_net_sources"]["taps"].items(): Nreal[int(ch)] |= set(nets)
        if Nmodel != Nreal: model_mismatch.append(f"{cid}_{pdkn}_{size}")
        bd = [cost.group_dims(R, g, p) for g, p in zip(groups, base_plans)]
        kinds = [r["kind"] for r in base["assembly_stats"]["row_dims"]]
        grow = [kinds.index("n" if g[0].model_role == "nfet" else "p") for g in groups]
        A0 = base["assembly_stats"]["area_um2"]
        for m in ("diffusion_only", "gate_only", "combined"):
            mp = Path(ind).parent.parent / m / "result.json"
            if not mp.exists(): continue
            r = json.load(open(mp))
            if not r.get("assembly_stats"): continue
            plans = [SharingPlan.from_json(ap_["plan"]) for ap_ in r["applied_plans"]]
            e = cost.estimate(R, groups, plans, bd, bstats, grow, base_plans=base_plans, channel_rule=a.channel_rule)
            A1 = r["assembly_stats"]["area_um2"]; d_true = (A1 - A0) / A0; d_hat = (e["area_hat"] - A0) / A0
            row = {"case": f"{cid}_{pdkn}_{size}", "mode": m, "A0": A0, "A_true": A1, "A_hat": e["area_hat"], "d_true": round(d_true, 5), "d_hat": round(d_hat, 5),
                   "sign_true": sign(d_true), "sign_hat": sign(d_hat), "passive_dominated": e["passive_dominated"],
                   "row_shift_true": r["assembly_stats"].get("row_x_shift"), "channel_true": r["assembly_stats"].get("channel_heights"),
                   "channel_base": base["assembly_stats"].get("channel_heights"), "strategy": r["assembly_stats"].get("channel_strategy"),
                   "channel_dh_hat": e.get("channel_dh")}
            if row["sign_true"] != row["sign_hat"]:
                ch_change = [round(x - y, 3) for x, y in zip(row["channel_true"] or [], row["channel_base"] or [])]
                pred = e.get("channel_dh") or [0.0] * len(ch_change)
                sh0 = base["assembly_stats"].get("row_x_shift") or []; sh1 = r["assembly_stats"].get("row_x_shift") or []
                d_shift = max([abs((a1 - a0)) for a0, a1 in zip(sh0, sh1)] + [0.0])
                ch_err = any(abs(x - y) > 1e-6 for x, y in zip(ch_change, pred))
                row["row_shift_change_um"] = round(d_shift, 3)
                if ch_err and d_shift > 0.3: row["error_type"] = "routing channel height mis-predicted + row x-shift changed"
                elif ch_err: row["error_type"] = "routing channel height mis-predicted"
                elif d_shift > 0.3: row["error_type"] = "row x-shift changed (cross-row via conflict, not modelled)"
                elif row["strategy"] != base["assembly_stats"].get("channel_strategy"): row["error_type"] = "assembly channel strategy changed"
                else: row["error_type"] = "group dimension estimate"
                row["channel_change"] = ch_change
            rows.append(row)
    n = len(rows); ok = sum(r["sign_true"] == r["sign_hat"] for r in rows)
    conf = collections.Counter((r["sign_true"], r["sign_hat"]) for r in rows)
    errs = collections.Counter(r.get("error_type") for r in rows if r["sign_true"] != r["sign_hat"])
    abs_err = sorted(abs(r["d_hat"] - r["d_true"]) for r in rows)
    import collections as _c
    def acc(key):
        d = _c.defaultdict(lambda: [0, 0])
        for r in rows: d[key(r)][0] += r["sign_true"] == r["sign_hat"]; d[key(r)][1] += 1
        return {k: {"correct": v[0], "n": v[1]} for k, v in sorted(d.items())}
    by = {"pdk": acc(lambda r: r["case"].split("_")[1]), "topology": acc(lambda r: r["case"].split("_")[0]), "mode": acc(lambda r: r["mode"])}
    summ = {"by": by, "n_pairs": n, "sign_correct": ok, "confusion(true,hat)": {f"{k[0]},{k[1]}": v for k, v in conf.items()}, "error_types": dict(errs),
            "median_abs_error_rel": abs_err[n // 2] if n else None, "p90_abs_error_rel": abs_err[int(0.9 * n)] if n else None, "dead_band": DEAD, "pin_model_mismatch_cases": model_mismatch,
            "rule": "textbook_sharing.selection.cost v2", "channel_rule": a.channel_rule or cost.CHANNEL_RULE}
    json.dump({"summary": summ, "rows": rows}, open(a.out, "w"), indent=1)
    print(json.dumps(summ, indent=1))
    for r in rows:
        if r["sign_true"] != r["sign_hat"]: print("  ERR", r["case"], r["mode"], r["d_true"], r["d_hat"], r.get("error_type"), r.get("channel_change"), r.get("channel_dh_hat"))


if __name__ == "__main__":
    main()
