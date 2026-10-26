"""Prospective eight-point schematic control qualification, never formal S2.

Freeze all independent N(z) and exact source-specific analysis bodies before
simulation. Only the already declared legacy15pF time-window adaptation is
applied; no circuit, threshold, solver or analysis outcome selects a point.
"""
import argparse
import ast
import copy
from datetime import datetime, timezone
import difflib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path("/work") if Path("/work").is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TASKS = "runtime/task_preparation/otas_20261019T022816023029Z/private"
DRAFT = "runtime/e2_draft_preparation/20261019T021747204896Z"


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    draft = json.loads((ROOT / DRAFT / "e2_formal_draft.json").read_text())
    flattener = module("trusted_flat_reference", ROOT / "scripts/materialize_ota_tasks.py")
    rows = []
    for kind in ["five_t", "compact_miller", "fvf", "legacy_miller"]:
        source = ROOT / TASKS / kind / "trusted_bench/analysis_function.py"
        original = source.read_text()
        adapted = original
        if kind == "legacy_miller":
            replacements = [
                ('pulse(.89 .91 1u 10n 10n 1u 2u)', 'pulse(.89 .91 5u 10n 10n 5u 10u)'),
                ('tran 5n 4u', 'tran 5n 20u'),
                ('"end":4e-6', '"end":20e-6'),
                ('[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]', '[[8.5e-6,9.9e-6],[13.5e-6,14.9e-6]]'),
                ('high=(t>1.8e-6)&(t<1.99e-6);low=(t>2.8e-6)&(t<2.99e-6)',
                 'high=(t>8.5e-6)&(t<9.9e-6);low=(t>13.5e-6)&(t<14.9e-6)'),
                ('timeout=240)', 'timeout=900 if name=="transient" else 240)'),
            ]
            for before, after in replacements:
                if adapted.count(before) != 1:
                    raise ValueError("Declared legacy15 window site changed: "+before)
                adapted = adapted.replace(before, after)
        ast.parse(adapted)
        for size in [draft["families"][kind]["sizings"][i] for i in [0, 2]]:
            point = out / (kind+"_"+size["id"])
            point.mkdir()
            gold = Path(size["intended_gold"]).read_text()
            if kind == "fvf":
                reference = module("independent_FVF_v3", ROOT / "scripts/fvf_intent_reference.py")
                gold = reference.intended_reference(size["sizing"]["local_current_bias_params"])
            if kind == "legacy_miller":
                gold = flattener.flat_legacy_reference(gold)
            (point / "gold.spice").write_text(gold)
            (point / "analysis_original.py").write_text(original)
            (point / "analysis.py").write_text(adapted)
            (point / "analysis.patch").write_text("".join(difflib.unified_diff(
                original.splitlines(True), adapted.splitlines(True),
                fromfile=str(source), tofile="analysis.py")))
            rows.append({"point_id": point.name, "source_family": kind, "sizing_id": size["id"],
                "sizing": size["sizing"], "generator_arguments": size["generator_arguments"],
                "independent_reference_version": "FVF_v3_source_derived_per_finger_dummies" if kind == "fvf" else "original_independent_sizing_reference",
                "contract": draft["families"][kind]["contract"],
                "gold": str(point.relative_to(out) / "gold.spice"), "analysis": str(point.relative_to(out) / "analysis.py"),
                "original_analysis": str(source)})
    record = {"scope": "development_prospective_E2_nondefault_sizing_schematic_controls_NOT_S2_NOT_FORMAL",
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "points": rows,
        "order": [r["point_id"] for r in rows], "corners": ["tt", "ss", "ff"],
        "all_gold_and_decks_fixed_before_first_simulation": True,
        "new_geometries_or_PEX": 0,
        "interpretation": "Schematic controls establish electrical meaning and analysis completeness only. They do not establish layout/device-intent/fullRC feasibility. All failures and costs are retained. No threshold or sizing will be changed from these outcomes.",
        "application_provenance": "5T2pF and compact2pF original applications; FVF15pF prospective application from separate positive control; legacy15pF one authorized hypothesis with fixed20us window, never a rewrite of old.5pF results."}
    write(out / "plan.json", record)
    print(json.dumps({"plan": str(out), "points": 8, "simulation_calls": 0}))


def candidate(out, inputs, index):
    import numpy as np
    from src.report_parsers import duplicate_subcircuits, rc_netlist_inventory
    from src.spice_validation import validate_analysis
    plan = json.loads((inputs / "plan.json").read_text())
    row = plan["points"][index]
    kind = row["source_family"]
    write(out / "point_manifest.json", {"scope": plan["scope"], "input_plan": str(inputs), **row})
    gold = out / "gold.spice"
    gold.write_bytes((inputs / row["gold"]).read_bytes())
    if duplicate_subcircuits(gold.read_text()):
        raise ValueError("Independent per-sizing schematic has duplicate declarations")
    code = (inputs / row["analysis"]).read_text()
    (out / "analysis.py").write_text(code)
    shutil.copy2((inputs / row["analysis"]).parent / "analysis.patch", out / "analysis.patch")
    measures = {"scope": "schematic_only_no_layout_no_PEX_no_S2", "results": {}}
    def save():
        write(out / "measurements.json", measures)
    ns = {"out": out, "source": gold, "reference": gold, "ref": gold,
        "pex": out / "NO_PEX_WAS_ACQUIRED.spice", "np": np, "re": re, "json": json,
        "subprocess": subprocess, "time": time, "validate_analysis": validate_analysis,
        "rc_netlist_inventory": rc_netlist_inventory, "duplicate_subcircuits": duplicate_subcircuits,
        "record": measures, "save": save}
    common = {"fidelity": "prelayout", "corners": ["tt", "ss", "ff"], "solver": "klu", "load_pf": 15., "analysis_timeout": 180}
    ns["a"] = ns["args"] = SimpleNamespace(**common)
    if kind in ["five_t", "compact_miller"]:
        ns.update(subcircuit=kind+"_ota", tail_node="tail", mirror_node="mirror", stage1_node="stage1")
        if kind == "five_t":
            ns.update(instance_nodes="vdd 0 bias vp vn out")
            ns["a"] = SimpleNamespace(vcm=1.1, bias_ua=20.)
        else:
            ns.update(nodes="vdd 0 bn bp vp vn out")
            ns["a"] = SimpleNamespace(vcm=1.05, n_bias_ua=20., p_bias_ua=10.)
    started = time.monotonic()
    exec(compile(code, str(out / "analysis.py"), "exec"), ns)
    if kind in ["five_t", "compact_miller"]:
        fn = ns["simulate" if kind == "five_t" else "measure"]
        for corner in ["tt", "ss", "ff"]:
            name, value = fn(corner, 2.)
            measures["results"][name] = value
            save()
        flag = "development_all_corners_feasible" if kind == "five_t" else "all_corners_nominal_feasible"
        row_flag = "development_feasible" if kind == "five_t" else "development_nominal_feasible"
        measures[flag] = all(r.get(row_flag, False) for r in measures["results"].values())
    else:
        ns["run_exact_analysis_loop"]()
        integrity = "analysis_validation" if kind == "fvf" else "analysis_evidence"
        flag = "simulation_flow_complete" if kind == "fvf" else "flow_complete"
        measures[flag] = bool(set(measures["results"]["prelayout"]) == {"tt", "ss", "ff"} and all(
            all(v["complete"] for v in row[integrity].values()) for row in measures["results"]["prelayout"].values()))
    save()
    temporary = copy.deepcopy(measures)
    if kind in ["fvf", "legacy_miller"]:
        temporary["results"]["post_rc"] = temporary["results"].pop("prelayout")
    summary = module("trusted_e2_metric_summary", ROOT / "scripts/e2_development_pilot.py")
    if kind != "legacy_miller":
        complete, feasible, metrics = summary.electrical_summary(temporary, kind)
    else:
        # The new application has declared later settled windows. Preserve the
        # exact retained bench's mean-error formulas for those actual windows.
        complete = measures["flow_complete"]
        corners = measures["results"]["prelayout"]
        normalized = []
        for value in corners.values():
            m = value["metrics"]
            errors = [m.get("positive_step_final_error_V"), m.get("negative_step_final_error_V")]
            normalized.append({"gain_10Hz_dB": m.get("gain_at_10Hz_dB"), "ugb_Hz": m.get("ugb_Hz"),
                "phase_margin_deg": m.get("phase_margin_deg"), "power_W": m.get("power_W"),
                "output_V": m.get("output_bias_V"), "positive_low_frequency_gain": m.get("gain_at_10Hz_real", 0) > 0,
                "settled_tracking_error_V": max(abs(v) for v in errors) if all(v is not None for v in errors) else None})
        feasible = bool(complete and all(m["gain_10Hz_dB"] is not None and m["gain_10Hz_dB"] >= 30
            and m["ugb_Hz"] is not None and m["ugb_Hz"] >= 1e6
            and m["phase_margin_deg"] is not None and 60 <= m["phase_margin_deg"] <= 180
            and m["positive_low_frequency_gain"] and abs(m["output_V"]-.9) < .01
            and m["settled_tracking_error_V"] is not None and m["settled_tracking_error_V"] < .01
            and 0 < m["power_W"] <= .001 for m in normalized))
        metrics = ({key: min(m[key] for m in normalized) for key in ["gain_10Hz_dB", "ugb_Hz", "phase_margin_deg"]}
            | {key: max(m[key] for m in normalized) for key in ["power_W", "settled_tracking_error_V"]}) if complete else None
    result = {"scope": plan["scope"], "point_id": row["point_id"], "source_family": kind,
        "status": "SCHEMATIC_COMPLETE_FEASIBLE" if complete and feasible else "SCHEMATIC_COMPLETE_INFEASIBLE" if complete else "SCHEMATIC_INCOMPLETE_UNKNOWN",
        "all_analyses_complete": complete, "schematic_constraints_passed": feasible,
        "worst_corner_metrics": metrics, "new_GDS_DRC_LVS_PEX_calls": 0,
        "S1_or_S2_established": False, "simulation_wall_seconds": time.monotonic()-started,
        "metric_normalization": "Same source-specific feasibility formulas applied to prelayout rows. Legacy15 uses its predeclared later settled windows. A temporary post_rc source-format key for the FVF summary is only an internal normalizer and never a claim that RC was acquired."}
    write(out / "sizing_result.json", result)
    print(json.dumps(result), flush=True)
    return 0 if complete and feasible else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["plan", "candidate"], required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    if args.mode == "plan":
        prepare(args.out)
        return 0
    if args.index not in range(8):
        parser.error("index must be0..7 in the fixed stream")
    return candidate(Path.cwd(), Path(os.environ["PROBE_INPUT"]), args.index)


if __name__ == "__main__":
    raise SystemExit(main())
