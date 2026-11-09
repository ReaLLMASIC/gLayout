"""Re-run ONLY the post-layout simulation of existing runs after a testbench change (geometry, DRC, LVS, sizing check
and PEX are unchanged and not repeated).  For every result.json under the given roots whose case uses a testbench whose
text changed, the old postsim block is kept in res["postsim_history"], the post-layout simulation is repeated on the same
extracted netlist with the current testbench (against the case's CURRENT frozen specs), and fail_reasons/primary_status
are recomputed.  Runs whose regenerated deck is identical to the one they used are skipped.
usage: python -m textbook_sharing.resim --roots grid,selection --jobs 20 --tag <name>   (roots are relative to the run folder)"""
from __future__ import annotations
import json, glob, time, argparse, shutil, re, collections
from pathlib import Path
from multiprocessing import Pool
from textbook_sharing import paths
ORDER = None


def strip_header(deck):
    # the stored deck = header (title, model includes, optional osdi block) + testbench text; compare from the DUT instance on
    i = deck.find("\nX1 ")
    return deck[i:] if i >= 0 else deck


def job(args):
    rp, tag = args
    from textbook_sharing.run_case import load_case_dir, ORDER as ORD
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.testbench import make_testbench
    from textbook_sharing.presim import presim
    rp = Path(rp); res = json.load(open(rp))
    if res.get("primary_status") in ("NA", "rejected_plan", "build_failed") or not res.get("postsim") or res["postsim"].get("status") == "NOT_RUN":
        return "skipped_no_postsim"
    od = rp.parent; ps = od / "postsim"
    old_decks = sorted(ps.glob("tb_*.spice"))
    if not old_decks: return "skipped_no_deck"
    pexsp = next((od / "verify" / "pex").glob("*_pex.spice"), None)
    if pexsp is None: return "skipped_no_pex"
    case, cj = load_case_dir(res["case_dir"]); circ = CIRCUITS[case.circuit_id]
    top = re.search(r"^\.subckt\s+(\S+)", pexsp.read_text(), re.M | re.I).group(1)
    new_tb = make_testbench(circ, top, str(pexsp), case, case.pdk)
    if strip_header(old_decks[0].read_text()).strip() == ("\n" + new_tb).strip() or strip_header(old_decks[0].read_text()).strip() == new_tb.strip():
        return "unchanged_deck"
    keep = od / f"postsim_superseded_{tag}"
    if not keep.exists(): shutil.move(str(ps), str(keep))
    else: shutil.rmtree(ps, ignore_errors=True)
    ts = time.time()
    s = presim(case.pdk, circ, case, ps, include_override=str(pexsp), dut_name=top)
    hist = res.get("postsim_history", [])
    hist.append({"tag": tag, "old_postsim": res["postsim"], "old_primary_status": res["primary_status"], "old_fail_reasons": res.get("fail_reasons"),
                 "old_post_layout_simulation_s": (res.get("timing_s") or {}).get("post_layout_simulation"), "moved_to": keep.name})
    res["postsim_history"] = hist
    res["postsim"] = {"status": s["status"], "measures": s["measures"], "spec": s["spec"].get("details") if s.get("spec") else None, "errors": s["sim"]["errors"][:3]}
    fr = [f for f in (res.get("fail_reasons") or []) if f not in ("spec_failed", "simulation_failed")]
    if s["status"] != "passed": fr.append("simulation_failed" if s["status"].startswith("simulation") else "spec_failed")
    res["fail_reasons"] = fr
    prim = next((o for o in ORD if o in fr), None); res["primary_status"] = prim or "auto_passed"
    res.setdefault("timing_s", {})["post_layout_simulation"] = round(time.time() - ts, 2)
    json.dump(res, open(rp, "w"), indent=1, default=str)
    return f"{hist[-1]['old_primary_status']}->{res['primary_status']}"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--roots", required=True); ap.add_argument("--jobs", type=int, default=16); ap.add_argument("--tag", required=True)
    ap.add_argument("--circuits", default=None); a = ap.parse_args()
    files = []
    for root in a.roots.split(","):
        files += sorted(glob.glob(str(paths.RUNS / root / "**" / "result.json"), recursive=True))
    files = [f for f in files if "/verify/" not in f and "postsim" not in f]
    if a.circuits:
        cs = set(a.circuits.split(","))
        files = [f for f in files if any(f"/{c}/" in f or f"/{c}_" in f for c in cs)]
    print("result files", len(files), flush=True)
    c = collections.Counter(); changes = []
    with Pool(a.jobs, maxtasksperchild=8) as pool:
        for f, st in zip(files, pool.imap(job, [(f, a.tag) for f in files], chunksize=1)):
            c[st] += 1
            if "->" in st and st.split("->")[0] != st.split("->")[1]: changes.append((f, st)); print("CHANGED", f, st, flush=True)
    out = paths.ANALYSIS / f"resim_{a.tag}.json"; out.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"counts": dict(c), "status_changes": changes}, open(out, "w"), indent=1)
    print(dict(c))


if __name__ == "__main__":
    main()
