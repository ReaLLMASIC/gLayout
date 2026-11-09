"""Evaluate one model proposal for one task (evaluator side; the model never sees this folder).
usage: python -m textbook_sharing.llm.evaluate <session_dir> <proposal_index>
Reads <session_dir>/session.json (task_id, case_dir, model, rep) and <session_dir>/p<k>_answer.md; writes
<session_dir>/p<k>_report.json (full, evaluator-side) and <session_dir>/p<k>_feedback.txt (what the model sees).
Every proposal consumes one unit of the proposal budget; a full EDA verification is run only for a legal plan that
was not proposed before in the same session (duplicates return the earlier feedback, flagged)."""
from __future__ import annotations
import sys, json, time, hashlib
from pathlib import Path
from textbook_sharing.llm.plan_parser import extract_code, parse_program, to_sharing_plan, ParseError


def feedback_text(rep):
    if rep["status"] == "rejected_program":
        lines = [f"Proposal {rep['k']}: REJECTED before building (no geometry was generated)."]
        for e in rep["errors"]: lines.append(f"  - [{e.get('code')}] {e.get('message')}" + (f" (line {e['line']})" if e.get("line") else "") + (f" group {e['group']}" if "group" in e else ""))
        return "\n".join(lines)
    r = rep["run"]
    lines = [f"Proposal {rep['k']}: built and verified" + (" (DUPLICATE of an earlier proposal; same result)" if rep.get("duplicate_of") else "") + f". Overall status: {r['primary_status']}."]
    v = r.get("verify", {})
    lines.append("  stages: " + ", ".join(f"{k}={v.get(k)}" for k in ("drc", "lvs", "constraints", "pex", "physical") if k in v) + f", post-layout simulation/spec={(r.get('postsim') or {}).get('status')}")
    if r.get("area_um2") is not None:
        st = r.get("assembly_stats", {})
        lines.append(f"  full-DUT bounding box: {st.get('width')} x {st.get('height')} um = {r['area_um2']} um^2")
        for row in st.get("row_dims", []):
            lines.append(f"    row {row['kind']}: width {row['width']} um (+ taps {2 * row['tap_extent']:.2f}), height {row['height']} um; cells " + ", ".join(f"{c['name']} {c['w']}x{c['h']}" for c in row["cells"]))
        lines.append(f"    routing channels: heights {[round(x, 3) for x in st.get('channel_heights', [])]} um; channel strategy {st.get('channel_strategy')}")
    for gi, ev in enumerate(r.get("evidence") or []):
        lines.append(f"  group {gi}: active islands {ev.get('active_islands')}, cross-device shared diffusion nodes {ev.get('n_cross_device_shared_nodes')}, cross-device shared gate conductors {ev.get('n_cross_device_gate_conductors')}")
    det = r.get("detail", {})
    for k in ("drc_categories", "lvs_final", "sizing", "spec_failures", "error"):
        if det.get(k): lines.append(f"  {k}: {det[k]}")
    return "\n".join(lines)


def main():
    sd = Path(sys.argv[1]).resolve(); k = int(sys.argv[2])
    sess = json.load(open(sd / "session.json"))
    from textbook_sharing.run_case import load_case_dir, pdk_obj, run
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.layout import device_specs, sharing_groups
    from glayout.sharing import validate_plan, rules_for
    case, cj = load_case_dir(sess["case_dir"]); circ = CIRCUITS[case.circuit_id]; pdk = pdk_obj(case.pdk)
    groups = sharing_groups(device_specs(circ, case.sizing))
    ans = (sd / f"p{k}_answer.md").read_text()
    rep = {"k": k, "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "answer_chars": len(ans)}
    t0 = time.time(); errors = []; plans = {}
    try:
        code = extract_code(ans); rep["program_chars"] = len(code)
        calls = parse_program(code, sess.get("interface", "sharing"))
        missing = [gi for gi in range(len(groups)) if gi not in calls]; extra = [gi for gi in calls if gi >= len(groups)]
        if missing: errors.append({"code": "missing_group", "message": f"no plan for group(s) {missing}"})
        if extra: errors.append({"code": "unknown_group", "message": f"group index(es) {extra} do not exist (groups 0..{len(groups) - 1})"})
        R = rules_for(pdk)
        for gi, call in calls.items():
            if gi >= len(groups): continue
            try:
                plan = to_sharing_plan(call, groups[gi], pdk)
            except ParseError as e:
                errors.append({**e.to_json(), "group": gi}); continue
            vr = validate_plan(R, groups[gi], plan)
            if not vr.ok:
                for e in vr.errors: errors.append({"code": e["code"], "message": e["message"], "group": gi})
                continue
            plans[str(gi)] = plan.to_json()
    except ParseError as e:
        errors.append(e.to_json())
    rep["parse_check_s"] = round(time.time() - t0, 3)
    if errors:
        rep.update({"status": "rejected_program", "errors": errors})
    else:
        gid = hashlib.sha256(json.dumps([plans[str(i)]["plan_id"] for i in range(len(groups))]).encode()).hexdigest()[:16]
        rep["global_plan_id"] = gid
        seen = json.load(open(sd / "seen.json")) if (sd / "seen.json").exists() else {}
        if gid in seen:
            old = json.load(open(sd / f"p{seen[gid]}_report.json"))
            rep.update({"status": "evaluated", "duplicate_of": seen[gid], "run": old["run"]})
        else:
            od = sd / f"p{k}_run"
            r = run(sess["case_dir"], od, plans=plans, label=f"{sess['model_tag']}_r{sess['rep']}_p{k}", context={"experiment": "llm", "task": sess["task_id"], "model": sess["model_tag"]},
                    nominal_sizing=sess.get("nominal_sizing"))
            det = {}
            vr = json.load(open(od / "verify" / "result.json")) if (od / "verify" / "result.json").exists() else {}
            stg = vr.get("stages", {})
            if stg.get("drc", {}).get("categories"): det["drc_categories"] = stg["drc"]["categories"]
            lv = stg.get("lvs", {})
            if lv.get("status") not in (None, "passed"): det["lvs_final"] = (lv.get("parsed") or {}).get("final") or lv.get("reason")
            if stg.get("constraints", {}).get("status") not in (None, "passed"): det["sizing"] = {k2: v2 for k2, v2 in stg["constraints"].items() if k2 in ("status", "mismatches", "error")}
            sp = (r.get("postsim") or {}).get("spec") or {}
            fails = {m: {"value": d.get("value"), "limit": d.get("spec")} for m, d in sp.items() if not d.get("ok")}
            if fails: det["spec_failures"] = fails
            if r.get("error"): det["error"] = r["error"][:300]
            r["detail"] = det
            rep.update({"status": "evaluated", "run": {k2: r.get(k2) for k2 in ("primary_status", "verify", "area_um2", "assembly_stats", "evidence", "postsim", "detail", "timing_s", "gds_sha256", "applied_plans", "matching")}})
            seen[gid] = k; json.dump(seen, open(sd / "seen.json", "w"))
    rep["evaluator_s"] = round(time.time() - t0, 2)
    json.dump(rep, open(sd / f"p{k}_report.json", "w"), indent=1, default=str)
    fb = feedback_text(rep)
    (sd / f"p{k}_feedback.txt").write_text(fb)
    print(fb)


if __name__ == "__main__":
    main()
