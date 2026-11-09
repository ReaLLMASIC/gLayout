"""Extraction sensitivity (separate from the formal results): re-extract a kept layout with capacitance only, run the
SAME testbench deck against that netlist, and compare the measures with the formal R+C result.
usage: python -m textbook_sharing.analysis.pex_sensitivity <run_dir> [<run_dir> ...] --out <json>"""
import re, json, argparse
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("runs", nargs="+"); ap.add_argument("--out", required=True); a = ap.parse_args()
    from textbook_sharing.verify import pex_sim
    from textbook_sharing.verify.lvs import run
    rows = []
    for rd in a.runs:
        rd = Path(rd).resolve(); r = json.load(open(rd / "result.json")); pdk = r["case_dir"].split("/")[-2]
        rc_net = next((rd / "verify/pex").glob("*_pex.spice")); top = re.search(r"^\.subckt\s+(\S+)", rc_net.read_text(), re.M | re.I).group(1)
        od = rd / "sensitivity_c_only"; od.mkdir(exist_ok=True)
        saved = dict(pex_sim.PEX_POLICY[pdk]); pex_sim.PEX_POLICY[pdk] = {"with_resist": False, "extresist_tolerance": None, "note": "sensitivity: C only"}
        try: px = pex_sim.pex(pdk, r["gds"], top, od)
        finally: pex_sim.PEX_POLICY[pdk] = saved
        deck = next((rd / "postsim").glob("tb_*.spice")).read_text()
        deck = deck.replace(str(rc_net), px["spice"]); assert px["spice"] in deck
        (od / "tb_c_only.spice").write_text(deck)
        run(f"ngspice -b {od}/tb_c_only.spice -o {od}/tb_c_only.out", str(od), od / "tb_c_only.log", timeout=900)
        m = pex_sim.read_measures((od / "tb_c_only.out").read_text(errors="replace"))
        row = {"run": paths.rel(rd), "status": r["primary_status"], "rc_measures": r["postsim"].get("measures"), "c_only_measures": m,
               "c_only_counts": {k: px.get(k) for k in ("n_res", "n_cap", "n_devices")}, "spec": {k: v["spec"] for k, v in (r["postsim"].get("spec") or {}).items()}}
        rows.append(row); print(json.dumps({k: row[k] for k in ("run", "status")}), {k: (row["rc_measures"] or {}).get(k) for k in row["spec"]}, {k: m.get(k) for k in row["spec"]})
    json.dump(rows, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
