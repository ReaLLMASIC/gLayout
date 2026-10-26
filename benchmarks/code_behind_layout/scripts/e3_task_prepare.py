#!/usr/bin/env python3
"""Prepare draft E3 complete-source editing states on the trusted backend.

No GPT, physical experiment, split freeze, or hidden export is performed.
Source packs are reused by explicit path; only 24 complete editable overrides
are written. A generation capsule consumer is included for actual qualification.
"""
import argparse
import ast
import copy
from datetime import datetime, timezone
import difflib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.e3_task_prepare import TARGETS, EDITABLE, DEFAULTS, INITIALS, LEVELS, generator_wrapper, objective, packet, render_parameters


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def original_controls_evidence(target, index, source):
    """Bind old measured source bytes, never infer outcomes from a parameter ID."""
    if target not in ("five_t", "compact_miller"):
        return None
    old_ids = {"five_t": ("c00", "c07", "c15"), "compact_miller": ("c00", "c02", "c08")}
    derived = ROOT/"results/derived"/("e2_development_"+target+"_pool.json")
    pool = json.loads(derived.read_text())
    row = next(r for r in pool["pool_table"] if r["candidate_id"] == old_ids[target][index])
    run = ROOT/"runs/phase0"/row["run_id"]
    raw = run/"candidate_source.py"
    if not raw.is_file():
        raise ValueError("Actual prior candidate source missing: "+str(raw))
    actual = raw.read_text()
    # The complete historical source is retained, including formatting; accepting
    # a merely similar control table would silently associate different programs.
    same = source == actual
    same_ast = ast.dump(ast.parse(source), include_attributes=False) == ast.dump(ast.parse(actual), include_attributes=False)
    if not same_ast:
        raise ValueError("E3 rendered module differs from actual E2 source: "+str(raw))
    fields = ("candidate_id", "stream_index", "run_id", "status", "full_flow_complete",
              "all_corner_development_feasible", "footprint_area_um2", "worst_corner_ugb_Hz",
              "wirelength_rectilinear_proxy_um", "R_sum_ohm", "C_sum_F")
    return {"origin": "curated_fixed_layout_stream_development", "pool_report": str(derived),
            "source_path": str(raw), "source_bytes_identical": same,
            "complete_module_AST_identical": same_ast, "measurements": {key: row[key] for key in fields if key in row},
            "interpretation": "Prior measured engineering variant, not an uncurated production bug or a formal policy trial. Historical incomplete traces remain unknown."}


def materialize(preparation, output):
    if not (ROOT/"runtime/GLdev/bin/python").is_file():
        raise ValueError("Private 25-point tables must be prepared on the trusted execution host")
    if output.exists():
        raise ValueError("A draft is never overwritten; choose a new output directory")
    began = time.monotonic()
    output.mkdir(parents=True, mode=0o700)
    public, private = output/"public", output/"private"
    public.mkdir(); private.mkdir(mode=0o700)
    rows, sources = [], {}
    for target in TARGETS:
        original_task_path = preparation/"private"/("draft_E1_"+target+"_s01")/"task.json"
        original = json.loads(original_task_path.read_text())
        pack = Path(original["source_pack"])
        path = EDITABLE[target]
        before = (pack/path).read_text()
        actual_states = []
        for index, controls in enumerate(INITIALS[target]):
            ident = "draft_E3_"+target+"_edit%02d" % (index+1)
            folder = private/ident
            state_source = render_parameters(target, before, controls)
            if state_source in actual_states:
                raise ValueError("Two IDs would represent the same complete source")
            actual_states.append(state_source)
            source_file = folder/"source"/path
            source_file.parent.mkdir(parents=True)
            source_file.write_text(state_source)
            original_file = folder/"original"/path
            original_file.parent.mkdir(parents=True)
            original_file.write_text(before)
            wrapper = folder/"frozen_export/generator.py"
            wrapper.parent.mkdir()
            wrapper.write_text(generator_wrapper(target))
            (folder/"original/generator.py").write_bytes((pack/"generator.py").read_bytes())
            wrapper_patch = "".join(difflib.unified_diff((pack/"generator.py").read_text().splitlines(keepends=True),
                wrapper.read_text().splitlines(keepends=True), fromfile="a/generator.py", tofile="b/generator.py"))
            (folder/"frozen_export/export_transport.patch").write_text(wrapper_patch)
            diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), state_source.splitlines(keepends=True),
                fromfile="a/"+path, tofile="b/"+path))
            (folder/"initial_layout_variant.patch").write_text(diff)
            historic = original_controls_evidence(target, index, state_source)
            points = copy.deepcopy(original["configurations"])
            for point in points:
                # N(z), original measurements, and all original electrical limits
                # are retained. Only the prospective task identity/QoR changes.
                point["contract"].update(task_id=ident, objective=objective(target))
                if point["contract"]["specifications"] != original["configurations"][0]["contract"]["specifications"]:
                    raise ValueError("Electrical specifications changed across one family")
            task = {"status": "DRAFT_E3_SOURCE_INVENTORY_NOT_PHYSICALLY_ADMITTED", "task_id": ident,
                "target": target, "logical_group": original["logical_group"],
                "merge_sensitivity_group": original["merge_sensitivity_group"],
                "parent_lineage": original["target_logic_id"], "source_pack_base": str(pack),
                "source_files": original["source_files"], "source_overrides": {path: str(source_file)},
                "frozen_source_overrides": {"generator.py": str(wrapper)},
                "export_transport": {"original_generator": str(folder/"original/generator.py"),
                    "patch": str(folder/"frozen_export/export_transport.patch"),
                    "reason": "Extract immutable configuration.parameters, build auxiliary files only inside /tmp, then export the single declared candidate.gds; original assembly and marker binding unchanged"},
                "editable_paths": [path], "entrypoint": "generator.py", "top_cell": original["top_cell"],
                "representation": "G2", "trusted_template": original["source_template"],
                "configuration_input": {"parameters": "The exact immutable per-z sizing dictionary"},
                "E1_binding": str(original_task_path), "independent_reference_binding": "Exact original per-z reference_file paths; no reference bytes modified or exported",
                "configurations": points, "shared_domain_id": original["shared_domain_id"],
                "domain_relationship": "All three edit states share the exact s01 role assignment of one 25-point domain; 24 programs are eight target logics, merged sensitivity seven groups.",
                "application": original["application"], "parameter_controls": controls,
                "parameter_baseline": {"renderer": "src.e3_task_prepare.render_parameters", "immutable_original_module": str(original_file),
                    "levels": LEVELS[target], "expresses_initial_state_exactly": True,
                    "does_not_express": "Arbitrary new placement algorithms/routing topology; no transistor or capacitor resizing is permitted"},
                "ancestry": {"origin": "unmodified_target_module" if index == 0 else ("curated_fixed_layout_stream_development" if historic else "explicit_legal_layout_parameter_variant"),
                    "source_template": original["source_template"], "base_module": str(pack/path),
                    "initial_patch": str(folder/"initial_layout_variant.patch"), "historical_evidence": historic,
                    "injected_defect": False, "production_natural_bug_claimed": False},
                "qualification": {"actual_generation": None, "initial_S0_S1_S2": None,
                    "feasible_improving_witness": None, "clean_but_poor_established": False,
                    "objective_adapter_required": target in ("five_t", "compact_miller"),
                    "domain_feasibility": "Shared independent N(z) qualification is upstream; it does not establish this layout's S1/S2.",
                    "natural_or_clean_poor_admission": "Pending actual source/geometry and physical qualification; no minimum quota is satisfied by these flags."},
                "formal_admission": False, "formal_trials": 0, "training_examples": 0}
            save(folder/"task.json", task)
            e1_packet = json.loads((preparation/"public"/("draft_E1_"+target+"_s01")/"G2.json").read_text())
            save(public/ident/"packet.json", packet(e1_packet, task, state_source))
            row = {"task_id": ident, "target": target, "logical_group": task["logical_group"],
                "merged_source_group": task["merge_sensitivity_group"], "editable_paths": [path],
                "complete_source_bytes": len(state_source.encode()), "initial_controls": controls,
                "origin": task["ancestry"]["origin"], "injected_defect": False,
                "historically_measured": historic is not None,
                "historical_status": historic["measurements"]["status"] if historic else None,
                "actual_initial_physical_status": None, "natural_shortfall_admitted": False,
                "objective": objective(target), "P_exact_initial_state": True,
                "configuration_counts": {"anchor": 1, "development": 8, "hidden": 16}}
            rows.append(row)
        sources[target] = {"original_complete_module": str(pack/path), "three_distinct_complete_modules": len(set(actual_states)) == 3}
    report = {"status": "DRAFT_NOT_FROZEN_NOT_FORMAL", "preparation": str(output), "E1_binding": str(preparation),
        "tasks": rows, "task_count": len(rows), "target_logics": 8, "primary_groups": 8, "merged_sensitivity_groups": 7,
        "P_common_tasks": len(rows), "three_distinct_complete_modules_per_target": sources,
        "injected_defect_count": 0, "historically_measured_states": sum(r["historically_measured"] for r in rows),
        "currently_admitted_natural_shortfall_states": 0, "required_natural_or_clean_poor_states": 12,
        "hidden_exported": False, "formal_trials": 0, "training_examples": 0,
        "cost": {"preparation_wall_seconds": time.monotonic()-began, "EDA_calls": 0, "model_calls": 0},
        "blockers": ["Actual generation and per-target geometric distinctness control", "Inherited electrical-spec feasibility of each editing initial state",
            "At least 12 actual natural failures or clean-but-poor source states with feasible improvement witnesses",
            "Prospective E3 objective metrics in the trusted evaluator", "Full context token preflight", "E3 protocol and split freeze"]}
    save(public/"inventory.json", report)
    save(output/"summary.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("tasks", "three_distinct_complete_modules_per_target")}), flush=True)
    return report


def make_working_directories_writable(output):
    """Only a newly copied workspace gets writable directories, never its source."""
    for folder in [output, *(p for p in output.rglob('*') if p.is_dir())]:
        folder.chmod(folder.stat().st_mode | 0o700)


def capsule(task_path, output):
    """Generation-only source capsule; no hidden config/evaluator mounted here."""
    task = json.loads(task_path.read_text())
    if output.exists():
        raise ValueError("Capsule output exists")
    shutil.copytree(task["source_pack_base"], output, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    make_working_directories_writable(output)
    for relative, source in {**task.get("frozen_source_overrides", {}), **task["source_overrides"]}.items():
        target = output/relative
        target.chmod(0o644)
        target.write_bytes(Path(source).read_bytes())
    files = sorted(str(p.relative_to(output)) for p in output.rglob("*") if p.is_file())
    if files != sorted(task["source_files"]):
        raise ValueError("Source capsule file set changed")
    return {"task_id": task["task_id"], "source_pack": str(output), "source_files": files,
            "entrypoint": task["entrypoint"], "editable_paths": task["editable_paths"]}


def preflight(preparation, output):
    from transformers import AutoTokenizer
    from src.local_model_adapter import decision_prompt
    from src.model_adapter import prompt_token_budget, PACKET_FIELDS
    from src.policy_state import current_state_request
    settings = json.loads((ROOT/"configs/training/backbone_cache.json").read_text())
    tokenizer = AutoTokenizer.from_pretrained(settings["snapshot"], local_files_only=True, trust_remote_code=False)
    results = []
    for path in sorted((preparation/"public").glob("draft_E3_*/packet.json")):
        view = json.loads(path.read_text())
        if set(view) != PACKET_FIELDS:
            raise ValueError("Packet whitelist changed")
        request = current_state_request(view, [{"observation": {"status": "initial"}}], view["visible_sources"])
        tokens = prompt_token_budget(tokenizer, decision_prompt(request), {"max_context_tokens": 8192, "max_new_tokens": 1024})
        results.append({"task_id": view["task_id"], **tokens})
    report = {"scope": "E3_draft_initial_full_source_preflight_no_inference", "preparation": str(preparation),
        "tokenizer_revision": settings["revision"], "context_limit": 8192, "output_reserve": 1024,
        "history_policy": "current_source_and_feedback_v1", "source_truncated": False,
        "PDK_rules_truncated": False, "all_fit": len(results) == 24 and all(r["fits_with_full_output_reserve"] for r in results),
        "results": results, "model_calls": 0, "formal_trials": 0}
    save(output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}), flush=True)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preparation", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--capsule", type=Path)
    p.add_argument("--preflight", action="store_true")
    a = p.parse_args()
    if a.capsule:
        print(json.dumps(capsule(a.capsule, a.output)), flush=True)
    elif a.preflight:
        raise SystemExit(0 if preflight(a.preparation, a.output)["all_fit"] else 2)
    else:
        materialize(a.preparation, a.output)
