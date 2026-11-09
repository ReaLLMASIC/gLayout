"""One run: one qualified case x (one named mode | one explicit candidate) -> GDS -> verification -> matching check
-> post-layout simulation against the case's frozen specification -> result.json (with per-stage timings).
Statuses (first failure wins): NA (mode not applicable), rejected_plan, build_failed, drc_failed, lvs_failed,
constraints_failed (sizing or declared matching ratio), pex_failed, simulation_failed, spec_failed,
physical_review_failed; otherwise auto_passed (visual review pending)."""
from __future__ import annotations
import json, time, traceback, re, hashlib
from pathlib import Path
from textbook_sharing.layout import build, applicability
from textbook_sharing.circuits import CIRCUITS
from textbook_sharing.cases import CaseSpec
from textbook_sharing.presim import presim
from textbook_sharing.verify.pipeline import verify_layout
from textbook_sharing.pdk import pdk_obj
from textbook_sharing import paths
from textbook_sharing import matching
from glayout.sharing import SharingPlanRejected
from textbook_sharing.assembly import AssemblyError

ORDER = ["rejected_plan", "build_failed", "drc_failed", "lvs_failed", "constraints_failed", "pex_failed", "simulation_failed", "spec_failed", "physical_review_failed"]


def load_case_dir(cdir):
    cdir = paths.resolve(cdir); cj = json.load(open(cdir / "case.json")); specs = json.load(open(cdir / "specs.json"))
    return CaseSpec(cj["case_id"], cj["circuit_id"], cj["pdk"], cj["size"], cj["sizing"], cj["supply"], cj["bias"], cj["load"], specs, cj.get("notes", [])), cj


def lvs_target(cdir, top, out_dir):
    src = (Path(cdir) / "target_lvs.spice").read_text()
    orig = re.search(r"^\.subckt\s+(\S+)", src, re.M).group(1)
    txt = re.sub(rf"^(\.subckt\s+){re.escape(orig)}\b", rf"\g<1>{top}", src, flags=re.M)
    txt = re.sub(rf"^(\.ends\s+){re.escape(orig)}\b", rf"\g<1>{top}", txt, flags=re.M)
    out_dir.mkdir(parents=True, exist_ok=True); p = out_dir / f"{top}_target_lvs.spice"; p.write_text(txt)
    return p, hashlib.sha256(src.encode()).hexdigest()


def run(cdir, out_dir, mode=None, plans=None, label=None, context=None, nominal_sizing=None):
    cdir = paths.resolve(cdir).resolve()
    case, cj = load_case_dir(cdir); circ = CIRCUITS[case.circuit_id]; pdkname = case.pdk; pdk = pdk_obj(pdkname)
    out_dir = Path(out_dir).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
    label = label or mode or "candidate"
    res = {"case_id": case.case_id, "case_dir": paths.rel(cdir), "label": label, "mode": mode, "t_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "timing_s": {}}
    t0 = time.time()
    try:
        if plans is None:
            appl = applicability(pdk, circ, case.sizing); res["applicability"] = appl["modes"]
            if not appl["modes"].get(mode, False):
                res["primary_status"] = "NA"; json.dump(res, open(out_dir / "result.json", "w"), indent=1, default=str); return res
        top = re.sub(r"[^A-Za-z0-9_]", "_", f"{case.case_id}_{label}".replace(".", "p"))[:90]   # gdsfactory-safe cell name
        tb = time.time()
        r = build(pdk, circ, case.sizing, mode=mode or "independent", name=top, plans=plans)
        gds = out_dir / f"{top}.gds"; r["component"].write_gds(str(gds))
        res["timing_s"]["geometry_generation"] = round(time.time() - tb, 2)
        from textbook_sharing.analysis.ledger import geometry_hash
        res["geometry_hash"] = geometry_hash(str(gds))      # cell-name independent: identical geometries share it
        res.update({"gds": paths.rel(gds), "gds_sha256": hashlib.sha256(gds.read_bytes()).hexdigest(), "groups": r["groups"], "applied_plans": r["applied_plans"],
                    "evidence": r["evidence"], "assembly_stats": r["assembly_stats"], "area_um2_assembly": r["assembly_stats"]["area_um2"]})
        tdevs = [{"name": d.name, "model": d.kind, "d": d.nets[0], "g": d.nets[1], "s": d.nets[2], "b": d.nets[3], "w": case.sizing[d.name]["w"], "l": case.sizing[d.name]["l"],
                  "nf": case.sizing[d.name]["nf"]} for d in circ.devices if d.kind in ("nfet", "pfet")]
        body_n = next((d.nets[3] for d in circ.devices if d.kind == "nfet"), "VSS")
        tl, tsha = lvs_target(cdir, top, out_dir); res["target_lvs_sha256"] = tsha
        v = verify_layout(pdkname, str(gds), top, str(tl), tdevs, circ.ports, out_dir / "verify", expected_fingers=r["expected_fingers"],
                          context=(context or {}) | {"case": case.case_id, "label": label}, sub_net=body_n)
        res["verify"] = {k: (val.get("status") if isinstance(val, dict) else val) for k, val in v["stages"].items()}
        res["timing_s"].update(v.get("timing_s", {}))
        res["area_um2"] = v["area_um2"]; res["fail_reasons"] = list(v["fail_reasons"]); res["review_id"] = v["review_id"]
        res["pex_policy"] = (v["stages"].get("pex") or {}).get("policy"); res["pex_counts"] = {k: (v["stages"].get("pex") or {}).get(k) for k in ("n_res", "n_cap", "n_devices", "floating_nodes")}
        m = matching.check(case.circuit_id, nominal_sizing or case.sizing, case.sizing, r["applied_plans"]); res["matching"] = m
        if m["status"] != "passed" and "constraints_failed" not in res["fail_reasons"]: res["fail_reasons"].append("constraints_failed")
        pexsp = v["stages"].get("pex", {}).get("spice")
        if pexsp:
            ts = time.time()
            s = presim(pdkname, circ, case, out_dir / "postsim", include_override=pexsp, dut_name=top)
            res["timing_s"]["post_layout_simulation"] = round(time.time() - ts, 2)
            res["postsim"] = {"status": s["status"], "measures": s["measures"], "spec": s["spec"].get("details") if s.get("spec") else None, "errors": s["sim"]["errors"][:3]}
            if s["status"] != "passed": res["fail_reasons"].append("simulation_failed" if s["status"].startswith("simulation") else "spec_failed")
        else:
            res["postsim"] = {"status": "NOT_RUN", "reason": "no PEX netlist"}
            if "pex_failed" not in res["fail_reasons"]: res["fail_reasons"].append("pex_failed")
        prim = next((o for o in ORDER if o in res["fail_reasons"]), None)
        res["primary_status"] = prim or "auto_passed"
    except SharingPlanRejected as e:
        res.update({"primary_status": "rejected_plan", "report": e.report.to_json()})
    except AssemblyError as e:
        res.update({"primary_status": "build_failed", "error": f"AssemblyError: {e}"})
    except Exception as e:
        res.update({"primary_status": "build_failed", "error": repr(e), "trace": traceback.format_exc()[-2500:]})
    res["timing_s"]["end_to_end"] = round(time.time() - t0, 2)
    json.dump(res, open(out_dir / "result.json", "w"), indent=1, default=str)
    return res


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Build and verify one layout of one case, e.g. "
                                             "python -m textbook_sharing.run_case data/cases/C08/sky130/sW1_sL1 /tmp/out --mode combined")
    ap.add_argument("case_dir"); ap.add_argument("out_dir")
    how = ap.add_mutually_exclusive_group(required=True)
    how.add_argument("--mode", choices=("independent", "diffusion_only", "gate_only", "combined"), help="a named mode")
    how.add_argument("--plans", help="JSON file {group index: SharingPlan json}")
    how.add_argument("--from-record", help="result.json of an earlier run: rebuild with the plans it recorded")
    a = ap.parse_args()
    plans = json.load(open(a.plans)) if a.plans else None
    if a.from_record:
        plans = {str(p["group"]): p["plan"] for p in json.load(open(a.from_record))["applied_plans"]}
    r = run(a.case_dir, a.out_dir, mode=a.mode, plans=plans, label=a.mode or "plans")
    print(json.dumps({k: r.get(k) for k in ("primary_status", "area_um2", "geometry_hash", "verify")}, indent=1))


if __name__ == "__main__":
    main()
