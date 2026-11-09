"""Bounded redesign search for the class-AB output stage (C18) at the nominal size point, schematic only.
Topology and body connections are those of the source netlist (fixed).  Searched: bias current of the replica-biased
current source M2 (ib), width multiplier of the diode stack M3/M4 (wd) and of the followers M5/M6 (wf), common length
multiplier (lm).  Every attempt and its schematic metrics are recorded; the first configuration (in the fixed search
order below, smallest current first) that meets every floor becomes the nominal point, otherwise the topology/PDK goes
to the diagnostic set.  Output: <results>/redesign_search/attempts_<pdks>.json.
usage: python -m textbook_sharing.redesign_search --pdks gf180,sky130,ihp130"""
import json, copy, argparse, itertools
from multiprocessing import Pool
from textbook_sharing.circuits import CIRCUITS
from textbook_sharing.cases import CaseSpec, PDK_POINT
from textbook_sharing.nominal import nominal
from textbook_sharing.presim import presim
from textbook_sharing.qualify import floors_for, qualify_and_freeze
from textbook_sharing import overrides
from textbook_sharing import paths

IB = (5e-6, 10e-6, 20e-6); WD = (1, 2, 4); WF = (1, 2); LM = (1.0, 2.0)


def attempt(job):
    pdk, ib, wd, wf, lm = job
    c0 = json.load(open(paths.NOMINAL / "C18" / f"{pdk}.json"))
    s, b, l, notes = overrides.apply("C18", pdk, c0["sizing"], c0["bias"], c0["load"])
    s = copy.deepcopy(s)
    for d, mult in (("M3", wd), ("M4", wd), ("M5", wf), ("M6", wf)):
        uw = s[d]["w"] / s[d]["nf"]; s[d]["nf"] = s[d]["nf"] * mult; s[d]["w"] = round(uw * s[d]["nf"], 4)
    for d in s:
        if "nf" in s[d]: s[d]["l"] = round(round(s[d]["l"] * lm * 200) / 200, 4)
    b = copy.deepcopy(b); b["VB1"] = {**b["VB1"], "current": ib}
    vdd = PDK_POINT[pdk]["vdd"]
    tag = f"ib{ib*1e6:g}u_wd{wd}_wf{wf}_lm{lm:g}"
    case = CaseSpec(f"C18_{pdk}_{tag}", "C18", pdk, tag, s, dict(c0["supply"]), b, l, {}, notes)
    pre = presim(pdk, CIRCUITS["C18"], case, paths.RESULTS / "redesign_search" / pdk / tag, dut_name=f"C18s_{pdk}_{tag}")
    floors = floors_for("C18", nominal("C18", pdk).specs, vdd)
    q = qualify_and_freeze("buffer_ab", floors, pre["measures"], pre["sim"]["status"], vdd, l.get("vout_target", vdd / 2))
    return {"pdk": pdk, "ib": ib, "wd": wd, "wf": wf, "lm": lm, "tag": tag, "qualified": q["qualified"], "reasons": q["reasons"],
            "measures": {k: pre["measures"].get(k) for k in ("vout0", "vin0", "iq", "gain_lf", "f3db", "out_swing", "thd_pct")}, "sizing": s, "bias": b}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--pdks", default="gf180,sky130,ihp130"); ap.add_argument("--jobs", type=int, default=16)
    a = ap.parse_args()
    jobs = [(p, ib, wd, wf, lm) for p in a.pdks.split(",") for ib, wd, wf, lm in itertools.product(IB, WD, WF, LM)]
    with Pool(a.jobs) as pool:
        res = pool.map(attempt, jobs)
    out = paths.RESULTS / "redesign_search" / f"attempts_{a.pdks.replace(',', '_')}.json"; out.parent.mkdir(parents=True, exist_ok=True)   # one file per PDK set
    json.dump(res, open(out, "w"), indent=1)
    for p in a.pdks.split(","):
        ok = [r for r in res if r["pdk"] == p and r["qualified"]]
        print(p, "attempts", sum(1 for r in res if r["pdk"] == p), "qualified", len(ok), ("first: " + ok[0]["tag"] + " " + json.dumps(ok[0]["measures"])) if ok else "")
        best = sorted([r for r in res if r["pdk"] == p], key=lambda r: len(r["reasons"]))[:3]
        for r in best: print("   ", r["tag"], {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r["measures"].items()}, r["reasons"][:2])


if __name__ == "__main__":
    main()
