#!/usr/bin/env python3
"""Summarize retained development runs; legacy DRC zeros are not acceptance."""
import csv
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.report_parsers import netgen_lvs_report

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--raw-root", type=Path, default=ROOT / "results/raw/server/runs/phase0")
base = parser.parse_args().raw_root
rows = []
measurements = {}
drc_links = {}
for path in sorted(base.glob("*/pilot_manifest.json")):
    data = json.loads(path.read_text())
    if data["status"] == "RUNNING":
        continue
    directory = path.parent
    validation = json.loads((directory/"validation.json").read_text()) if (directory/"validation.json").exists() else {}
    measured = json.loads((directory/"measurements.json").read_text()) if (directory/"measurements.json").exists() else {}
    resources = json.loads((directory/"resource_usage.json").read_text()) if (directory/"resource_usage.json").exists() else {}
    counts = measured.get("element_counts", validation.get("element_counts", data.get("element_counts", {})))
    drc = validation.get("DRC", measured.get("DRC", {}))
    if validation.get("scope")=="actual_top_full_bbox_completed_DRC":
        drc = validation
    trusted_drc = drc.get("completed") is True and drc.get("style")=="drc(full)"
    reports = list(directory.rglob("*_lvs.rpt"))
    lvs = [netgen_lvs_report(p.read_text()) for p in reports]
    row = {"run_id":data["run_id"], "status":data["status"],
        "case":data.get("case",data.get("script")), "source_commit":data.get("source_commit"),
        "scope":validation.get("scope",measured.get("scope",data.get("scope",data.get("phase")))),
        "wall_seconds":None, "cpu_seconds":None,
        "R_elements":counts.get("R"), "C_elements":counts.get("C"),
        "DRC_clean":drc.get("is_clean") if trusted_drc else None,
        "DRC_evidence":"completed_full_rules" if trusted_drc else "not_established_or_legacy_withdrawn",
        "LVS_clean":all(v["is_clean"] for v in lvs) if lvs else None,
        "retained_LVS_reports":len(reports),
        "flow_complete":validation.get("flow_complete",measured.get("flow_complete")),
        "retry_of":data.get("retry_of"),"rerun_reason":data.get("rerun_reason")}
    if data.get("started_at_utc") and data.get("ended_at_utc"):
        row["wall_seconds"] = (datetime.fromisoformat(data["ended_at_utc"]) - datetime.fromisoformat(data["started_at_utc"])).total_seconds()
    if resources:
        row["cpu_seconds"] = sum(resources[k] for k in ["self_user_cpu_seconds","self_system_cpu_seconds","children_user_cpu_seconds","children_system_cpu_seconds"])
    if trusted_drc and drc.get("input_gds"):
        parts = Path(drc["input_gds"]).parts
        if "phase0" in parts:
            origin = parts[parts.index("phase0")+1]
            drc_links.setdefault(origin,[]).append({"run_id":data["run_id"],"input_gds":drc["input_gds"],"is_clean":drc["is_clean"]})
    if measured:
        measurements[data["run_id"]] = measured
    elif data.get("results"):
        measurements[data["run_id"]] = data["results"]
    if validation:
        measurements.setdefault(data["run_id"],validation)
    rows.append(row)
if not rows:
    raise SystemExit("No completed raw development manifests; restore the checkpoint archive")
out = ROOT / "results/derived"
out.mkdir(parents=True, exist_ok=True)
summary = {"status":"PHASE0_IN_PROGRESS", "dataset_role":"development_pilot",
    "formal_experiment_runs":0,"formal_S2_results":0,
    "legacy_DRC_acceptance":"WITHDRAWN_KNOWN_FALSE_NEGATIVE_CONTROL", "runs":rows,
    "independent_full_DRC_rechecks":drc_links,"development_measurements":measurements,
    "resource_totals":{"wall_seconds_sum_not_elapsed":sum(r["wall_seconds"] or 0 for r in rows),
        "measured_cpu_seconds":sum(r["cpu_seconds"] or 0 for r in rows),
        "runs_missing_actual_CPU":sum(r["cpu_seconds"] is None for r in rows)}}
(out/"phase0_summary.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
with (out/"phase0_runs.csv").open("w",newline="") as stream:
    writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
print(json.dumps({"pilot_records":len(rows),"formal_runs":0,"output":str(out/"phase0_summary.json")},indent=2))
