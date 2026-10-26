"""Materialize the prospective E2 12x64 stream with executable isolated inputs.

No formal labels are acquired here. Old development plans remain immutable.
The legacy15pF application is explicitly unadmitted: it may describe a complete
zero-feasible pool, but cannot supply an achievable E3 repair task.
"""
import argparse
import ast
import copy
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import shutil
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_e2_draft import gold_for_size, module
from scripts.ota_domain_qualification import analysis_contracts
from scripts.fvf_intent_reference import intended_reference
from src.e1_benchmarks import build_trusted
from src.measurement import validate_contract

TASKS = ROOT / "runtime/task_preparation/otas_20261019T022816023029Z/private"
LEGACY_CLOSURE = ROOT / "runtime/task_preparation/legacy_closure_repair_20261019T030431740812Z/private/legacy_miller/source_pack"
MODULES = {"five_t": "src/generators/five_t.py", "compact_miller": "src/generators/compact_miller.py",
    "fvf": "glayout/cells/composite/fvf_based_ota/ota.py", "legacy_miller": "glayout/cells/composite/opamp/opamp_twostage.py"}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def prepare(draft_path, out, serial_templates):
    draft_path, out = Path(draft_path).resolve(), Path(out).resolve()
    old = json.loads(draft_path.read_text())
    legacy_control = json.loads((ROOT / "runs/phase0/phase0_20261019T024226699014Z_independent_legacy_domain/domain_result.json").read_text())
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"status": "DRAFT_NOT_FROZEN", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "prospective_E2_executable_768_and_6_online_NO_FORMAL_LABELS", "draft_origin": str(draft_path),
        "candidate_pool_size": 64, "maximum_generation_attempts_per_pool": 256, "pools": [],
        "stage_levels": ["geometry", "actual_fullrule_DRC_LVS_intent_positive_PEX", "actual_nominal_TT_OP_AC", "full_three_corner_SPICE"],
        "calibrated_F3": {"admitted": False, "reason": "Needs independent train/validation UGB calibration; no evaluation outcome fitting"},
        "heuristics": {"fixed_area": "Full-evaluate16 smallest physical mask bbox areas; ties stream index",
            "adaptive_geometry": "Eight batches of2 actual full evaluations; start area rank; select wire rank after a batch with no feasible result, otherwise area rank. No UGB prediction or surrogate fitting.",
            "full_budget": 16, "meaning": "Explicit geometry heuristics; not calibrated fidelity predictors"},
        "source_group_caveat": old["source_independence"], "formal_execution_allowed": False,
        "development_labels_reused_as_formal": False,
        "online_execution": "Six separately dispatched executions on the six nondefault5T/compact/FVF sizing points. Each method regenerates its stream in a separate run, performs real new full calls, and receives no offline-oracle labels.",
        "blocking_before_freeze": ["Actual geometry-only/PEX-only smoke", "All12 independent size bindings and8 nondefault physical controls",
            "5T complete prospective timing/feedback calibration", "64 actual exact mask-distinct GDS per sizing",
            "Formal per-stage budgets and cost instrumentation", "Independent train/validation calibration for F3"],
        "legacy15_application": {"admitted_for_E3": False, "positive_control": False,
            "evidence": "phase0_20261019T024226699014Z_independent_legacy_domain", "complete": True,
            "worst_PM_deg": min(row["phase_margin_deg"] for row in legacy_control["metrics_by_corner"].values()), "no_load_search": True,
            "interpretation": "Full failure-accounting E2 domain only. No feasible oracle implies regret=null."}}
    for family, definition in old["families"].items():
        directory = out / family
        directory.mkdir()
        task_path = TASKS / family / "task.json"
        task = json.loads(task_path.read_text())
        original_pack = LEGACY_CLOSURE if family == "legacy_miller" else Path(task["source_pack"])
        pack = directory / "source"
        shutil.copytree(original_pack, pack)
        # CandidateExecutor transports metadata plus an explicit parameters
        # object. The old engineering preflight called component_build with
        # the raw dict, so its convenience CLI is not an isolated entrypoint.
        (pack / "generator.py").write_text("import argparse,json\nfrom pathlib import Path\nfrom component_build import build\n"
            "p=argparse.ArgumentParser();p.add_argument('--configuration');p.add_argument('--output');a=p.parse_args()\n"
            "build(json.loads(Path(a.configuration).read_text())['parameters'],Path(a.output))\n")
        target = MODULES[family]
        before = Path(definition["source_snapshot"]).read_text()
        (pack / target).write_text(before)
        if family in ["five_t", "compact_miller"]:
            adapter = pack / "component_build.py"
            prior = adapter.read_text()
            site = "output.parent/(output.stem+'_generated')"
            if prior.count(site) != 1:
                raise ValueError("Research generator scratch-directory binding changed")
            adapter.write_text(prior.replace(site, "Path('/tmp/e2_generated')"))
            (directory / "source_transport.patch").write_text("".join(difflib.unified_diff(prior.splitlines(True),
                adapter.read_text().splitlines(True), fromfile="engineering_component_build.py", tofile="isolated_component_build.py")))
        if family in ["fvf", "legacy_miller"]:
            # E2 changes complete original generator source constants, unlike
            # E3's semantically complete helper edit window. Do not overwrite
            # those changes by re-executing the old hoisted E3 face.
            adapter = pack / "component_build.py"
            prior = adapter.read_text()
            node = next(n for n in ast.parse(prior).body if isinstance(n, ast.FunctionDef) and n.name == "build")
            lines = prior.splitlines(True)
            exec_node = next(n for n in node.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name) and n.value.func.id == "exec")
            lines[exec_node.lineno-1:exec_node.end_lineno] = ["    # E2 invokes the complete frozen source module directly.\n"]
            adapter.write_text("".join(lines))
            (directory / "source_transport.patch").write_text("".join(difflib.unified_diff(prior.splitlines(True),
                adapter.read_text().splitlines(True), fromfile="E3_component_build.py", tofile="E2_component_build.py")))
        stream = []
        sampler = module("fixed_E2_sampler", ROOT / "scripts/e2_development_pilot.py")
        patches = directory / "layout_patches"
        patches.mkdir()
        for row in definition["candidate_stream"]:
            after = sampler.variant_text(before, family, row["controls"])
            ast.parse(after)
            path = patches / (f"layout_{row['stream_index']:03d}.patch")
            path.write_text("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=target, tofile=target)))
            stream.append({**row, "patch": str(path)})
        source_files = sorted(str(p.relative_to(pack)) for p in pack.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        original_plan = ROOT / "runs/phase0" / definition["development_selection_disclosure"]["observed_plan"]
        masks = directory / "retained_development_masks"
        masks.mkdir()
        retained_masks = []
        for path in sorted((ROOT / "runs/phase0").glob("*_e2_development_pilot/"+task["cell_name"]+".gds")):
            destination = masks / (path.parent.name+".gds")
            os.link(path, destination)
            retained_masks.append(str(destination))
        for size in definition["sizings"]:
            sid = size["id"]
            point = copy.deepcopy(task["configurations"][0])
            point["configuration_id"] = family+"_"+sid
            point["reference_id"] = "E2_independent_"+family+"_"+sid
            point["parameters"].update(size["generator_arguments"].get("config", size["generator_arguments"]))
            value = point["parameters"]["input_width"] if family in ["five_t", "compact_miller"] else (
                point["parameters"]["local_current_bias_params"][1] if family == "fvf" else point["parameters"]["half_diffpair_params"][0])
            _, _, gold = gold_for_size(family, original_plan, value)
            if family == "fvf":
                gold = intended_reference(point["parameters"]["local_current_bias_params"])
            sized = directory / sid
            sized.mkdir()
            reference = sized / "reference.spice"
            reference.write_text(gold)
            point["reference_file"] = str(reference)
            contract = point["contract"]
            contract.update(task_id="E2_"+family, configuration_id=point["configuration_id"], reference_id=point["reference_id"],
                immutable_parameters=point["parameters"], analysis_contracts=analysis_contracts(family, family == "legacy_miller"),
                objective={"id": "worst_corner_ugb", "metric": "ugb", "unit": "Hz", "direction": "maximize", "corner_aggregation": "worst"})
            if not any(s["name"] == "original_development_predicate" for s in contract["specifications"]):
                contract["specifications"].append({"name": "original_development_predicate", "unit": "1", "min": 1., "max": 1.})
            if family in ["fvf", "legacy_miller"]:
                contract["bench_parameters"] = {"supply_V": 1.8, "temperature_C": 27, "common_mode_V": .9,
                    "bias_currents_A": [1e-5, 1e-5], "load_F": 15e-12}
                contract["analysis_timeout_s"] = 900 if family == "legacy_miller" else 180
            validate_contract(contract)
            write(sized / "point.json", point)
            trusted = sized / "trusted_full"
            if family in ["five_t", "compact_miller"]:
                calibrated = Path(serial_templates[family]).resolve()
                binding = json.loads((calibrated / "binding.json").read_text())
                if binding["kind"] != family or not binding["measurement_function_source_identical"]:
                    raise ValueError("The prospective serial bench calibration belongs to a different source")
                build_trusted({"target": family, "top_cell": task["cell_name"], "source_template": str(calibrated / "task.json")}, point, trusted)
                write(sized / "serial_scheduling_binding.json", binding)
            else:
                trusted.mkdir()
                (trusted / "src").mkdir()
                (trusted / "src/__init__.py").write_text("")
                for name in ["physical_drc.py", "report_parsers.py", "device_intent.py", "measurement.py", "spice_validation.py", "corpus_metrics.py"]:
                    shutil.copyfile(ROOT / "src" / name, trusted / "src" / name)
                shutil.copyfile(ROOT / "scripts/e1_trusted_evaluator.py", trusted / "evaluate.py")
                shutil.copyfile(ROOT / "scripts/ota_frozen_bench.py", trusted / "ota_frozen_bench.py")
                bench = TASKS / family / "trusted_bench/original_retained_bench.py"
                if family == "legacy_miller":
                    bench = ROOT / "runs/phase0/phase0_20261019T024226699014Z_independent_legacy_domain/testbench_load15_long_window.py"
                text = bench.read_text()
                (trusted / "original_bench.py").write_text(text)
                loop = next(n for n in ast.parse(text).body if isinstance(n, ast.For))
                (trusted / "analysis_function.py").write_text("def run_exact_analysis_loop():\n"+textwrap.indent(ast.get_source_segment(text, loop), "    ")+"\n")
                write(trusted / "meta.json", {"bench_kind": "vendor_ota", "circuit": family, "top_cell": task["cell_name"], "ports": task["ports"]})
                shutil.copyfile(reference, trusted / "reference.spice")
                write(trusted / "contract.json", contract)
            pool_id = family+"_"+sid
            manifest["pools"].append({"pool_id": pool_id, "source_family": family, "sizing_id": sid,
                "point": str(sized / "point.json"), "source_dir": str(pack), "source_paths": source_files,
                "entrypoint": "generator.py", "layout_target": target, "source_snapshot": str(pack / target),
                "full_trusted": str(trusted), "top_cell": task["cell_name"], "candidate_stream": stream,
                "source_qualified": False, "physical_control_pending": sid != "s1",
                "development_mask_paths": retained_masks if sid == "s1" else [],
                "development_masks_retained_by_hardlink_no_extra_GDS_bytes": True,
                "online_selected": family != "legacy_miller" and sid in ["s0", "s2"]})
    if len(manifest["pools"]) != 12 or sum(p["online_selected"] for p in manifest["pools"]) != 6:
        raise ValueError("The declared12pool/6online matrix changed")
    write(out / "execution_manifest.json", manifest)
    print(json.dumps({"manifest": str(out / "execution_manifest.json"), "pools": 12, "prospective_labels": 768,
        "online_tasks": 6, "formal_allowed": False}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--draft", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--five-t-serial", type=Path, required=True)
    p.add_argument("--compact-serial", type=Path, required=True)
    a = p.parse_args()
    prepare(a.draft, a.output, {"five_t": a.five_t_serial, "compact_miller": a.compact_serial})
