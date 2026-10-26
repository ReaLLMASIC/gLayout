"""Prepare prospective E2 source/size/control bindings; never run EDA or SPICE.

This is a development-informed DRAFT. Preparation neither freezes the main
protocol nor turns previously observed development labels into formal data.
"""
import argparse
import ast
from datetime import datetime, timezone
import difflib
import importlib.util
import itertools
import json
from pathlib import Path
import re
import shutil


PLANS = {
    "five_t": "phase0_20261019T011122226634Z_e2_development_pilot",
    "compact_miller": "phase0_20261019T012051320824Z_e2_development_pilot",
    "fvf": "phase0_20261019T012053961469Z_e2_development_pilot",
    "legacy_miller": "phase0_20261019T012056202713Z_e2_development_pilot",
}
LEVELS = {
    "five_t": {"channel_gap_um": [22, 24, 28, 30], "drop_width_um": [.68, .76, .84, .92],
        "trunk_width_um": [.8, 1.4, 1, 1.2], "bus_pitch_um": [3, 4, 3.25, 3.75]},
    "compact_miller": {"spine_width_um": [.6, .7, .8, .9], "bus_width_um": [.88, .96, 1.04, 1.12],
        "capacitor_center_x_um": [130, 146, 134, 142], "output_landing_clearance_um": [4, 8, 5, 7]},
    "fvf": {"pblock_gap_um": [8, 9, 11, 12], "bias_route_extension_um": [8.8, 9.6, 10.4, 11.2],
        "source_tie_width_um": [.6, .9, .7, .8], "lcmfb_route_width_um": [.9, 1.2, 1, 1.1]},
    "legacy_miller": {"stage_gap_um": [10, 11, 13, 14], "output_route_width_um": [2.2, 2.4, 2.6, 2.8],
        "output_route_extension_um": [2, 6, 3, 5], "input_antenna_span_multiplier": [9, 13, 10, 12]},
}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def gold_for_size(family, plan, value):
    if family in ["five_t", "compact_miller"]:
        ref = module("draft_reference_"+family, plan / "reference_snapshot.py")
        sizes = dict(json.loads((plan / "pool_plan.json").read_text())["fixed_sizing"])
        sizes["input_width"] = value
        return sizes, {"config": sizes}, ref.schematic(sizes)
    original = (plan / "gold.spice").read_text()
    if family == "fvf":
        # Intended local PMOS bias devices only; preserve actual per-finger
        # width1.88/m2 main and width3.76/m1 body dummy declarations.
        gold, count = re.subn(r"^(Xlocal_p(?:diode|out|dummy)[12]\b.*\bl=)3(?=\s|$)",
            lambda m: m[1]+f"{value:g}", original, flags=re.M)
        if count != 6:
            raise ValueError("Independent FVF local-bias reference binding changed")
        return {"local_current_bias_params": [3.76, value], "all_other_arguments": "unchanged defaults"}, {
            "local_current_bias_params": [3.76, value]}, gold
    def change_width(match):
        return re.sub(r"(\bw=)6(?:\.0)?(?=\s|$)", lambda m: m[1]+f"{value:g}", match[0])
    gold, first = re.subn(r"^\.subckt NMOS .*?^\.ends NMOS$", change_width, original, count=1, flags=re.M|re.S)
    gold, second = re.subn(r"^\.subckt DIFF_PAIR .*?^\.ends DIFF_PAIR$", change_width, gold, count=1, flags=re.M|re.S)
    if first != 1 or second != 1:
        raise ValueError("Independent legacy input-device reference blocks changed")
    return {"half_diffpair_params": [value, 1, 4], "mim_cap_size": [30, 30], "rmult": 2,
            "all_other_arguments": "unchanged defaults"}, {
            "half_diffpair_params": [value, 1, 4], "mim_cap_size": [30, 30], "rmult": 2}, gold


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sampler = module("draft_existing_variant_sites", root / "scripts/e2_development_pilot.py")
    draft = {
        "status": "DRAFT_NOT_FROZEN_NO_FORMAL_MEASUREMENTS", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_pack": str(out), "target": {"source_programs": 4, "sizings_per_source": 3,
            "geometry_distinct_candidates_per_sizing": 64, "target_measured_candidates": 768},
        "source_independence": "Four distinct high-level OTA source programs; vendor FVF and Miller share circuit helpers and the vendor-connected dependency cluster. These are not four independent ancestry clusters. Report high-level-program results plus source-closure sensitivity.",
        "development_labels_reused_as_formal": False, "formal_execution_allowed": False,
        "generation_or_dedup_is_not_S0_S1_S2_measurement": True,
        "sizing_rule": "One declared transistor category varied symmetrically about each qualified default; every sizing has separate intended gold. No sizing is selected by a new outcome. Nondefault sizing qualification remains pending.",
        "layout_stream_rule": "First64=4x4x2x2, then remaining4^4 combinations in fixed lexicographic order. Geometry only selects first64 mask-distinct successful GDS. All generation failures and duplicates consume cost and stay in denominators. Never replace a DRC/LVS/PEX/electrical failure. Stop after256 generation attempts; insufficient64distinct is an admission failure, not permission to search further.",
        "development_overlap_control": "The second layout control has four new interior levels, disjoint from the old development endpoints; exact Boolean-mask dedup must still exclude any actual old geometry matches. Old labels and raw trials are never copied into this pool. Baseline control is separate known development context and is not one of the64 new combinations.",
        "geometry_equality": {"implementation": "src/e2_mask_geometry.py", "operation": "Flatten including paths/repetitions; convert physical coordinates to um; use original GDS precision; ignore text and PDK pin/label annotation layers; union each physical layer/datatype; remove common translation; exact XOR-empty equality on every layer. Area/bbox can reject but cannot certify equality.",
            "PDK_exclusion_binding": "At main freeze enumerate the exact SKY130 glayers ending _pin/_label plus(64,44); save this explicit list. No physical conductor/device layer excluded.",
            "prohibited_distinctness": ["translation", "cell names", "text labels", "polygon partitioning or orientation", "renaming devices"],
            "comparison_scope": "each source/sizing plus known development masks; cross-source or different-N equivalence is separately reported, never a new source lineage"},
        "objective": {"metric": "ugb_Hz", "direction": "maximize", "unit": "Hz", "aggregation": "minimum over tt/ss/ff after all constraints pass"},
        "no_feasible_oracle": {"regret": None, "report": "observed feasible fraction, budgeted unresolved/censored fraction and complete electrical infeasible fraction separately; no finite made-up penalty or fake regret"},
        "fidelities": [
            {"id": "geometry", "observes": ["GDS footprint area_um2", "rectilinear conductor proxy_um", "exact mask distinctness"], "requires": "actual source-to-GDS generation", "target_prediction": None, "interpretation": "Descriptive geometry, not calibrated UGB prediction"},
            {"id": "physical_and_PEX", "observes": ["full DRC", "independent unique LVS", "complete actual positive fullRC", "R_sum_ohm", "C_sum_F"], "requires": "actual DRC/LVS/PEX", "target_prediction": None, "interpretation": "R*C features have actual PEX acquisition cost; not a cheap pre-PEX L1"},
            {"id": "nominal_OP_AC", "observes": ["tt OP", "tt AC at source-specific declared grid", "tt UGB_Hz"], "requires": "admitted actual PEX", "target_prediction": "Only after train/validation calibration to worst-cornerUGB; otherwise descriptive nominal metric"},
            {"id": "complete_three_corner", "observes": ["tt/ss/ff OP", "AC", "transient", "declared complete DC"], "requires": "strict completion/axis/finite/log gates", "interpretation": "Only this establishes complete constrained objective/S2"}],
        "cost_contract": {"per_stage": ["generation", "mask_union_and_duplicate_comparison", "DRC", "LVS", "PEX", "each corner/analysis"],
            "required_actual_fields": ["monotonic_wall_seconds", "self_user_cpu_seconds", "self_system_cpu_seconds", "children_user_cpu_seconds", "children_system_cpu_seconds", "returncode_or_timeout", "attempt_id", "input_artifact_reuse", "queue_wait_seconds"],
            "allocation": "Charge source-to-GDS and PEX once on actual first acquisition, then reference dependencies. A reused artifact saves repeated work but retains its first acquisition cost. Global CPU samples are shared scheduling context, never summed across pools.",
            "development_cost_limits": "Existing pilots record stage wall times and total process/child CPU; they do not retrospectively establish missing per-stageCPU. New cost instrumentation and calibrated formal budgets remain pending.",
            "failure_accounting": "Include syntax/generation failures, duplicates, physical failures, PEX failures, incomplete numeric traces and timeout CPU/wall/queue costs; unresolved is not intrinsic infeasible."},
        "promotion_methods": {"status": "DRAFT_IMPLEMENTATION_AND_BUDGET_CALIBRATION_PENDING", "required": ["all candidate full evaluation oracle", "fixed promotion", "adaptive promotion", "matched verification resources"],
            "calibration": "Fit same-target predictions and selection thresholds on separately assigned train/validation source groups only. Never fit or retune on these E2 evaluation pool labels."},
        "families": {},
        "blocking_before_main_freeze": ["all12sizing references need application-specific admission;8nondefault sizing points have no physical qualification", "64exact mask-distinct GDS perN not yet generated", "explicit PDK mask exclusions not yet frozen", "calibrated cross-fidelity predictions/promotion budgets not yet frozen", "formal per-stageCPU and immutable isolated sampler executor not yet wired", "legacy15pF single qualification still pending; no further load search allowed"],
    }
    for family, plan_id in PLANS.items():
        plan = root / "runs/phase0" / plan_id
        manifest = json.loads((plan / "pool_plan.json").read_text())
        destination = out / family
        destination.mkdir()
        for name in ["generator_snapshot.py", "reference_snapshot.py", "gold.spice", "pool_plan.json", "testbench_original.py", "testbench_snapshot.py"]:
            # The first5T plan predates retained-PEX transport; its unchanged
            # bench has only the testbench_snapshot.py name.
            path = plan / name
            if name == "testbench_original.py" and not path.exists():
                path = plan / "testbench_snapshot.py"
            shutil.copy2(path, destination / name)
        source = (plan / "generator_snapshot.py").read_text()
        levels = LEVELS[family]
        keys = list(levels)
        prefix = list(itertools.product(levels[keys[0]], levels[keys[1]], levels[keys[2]][:2], levels[keys[3]][:2]))
        reserve = [v for v in itertools.product(*levels.values()) if v not in prefix]
        candidates = []
        patches = destination / "layout_patches"
        patches.mkdir()
        for i, values in enumerate(prefix+reserve):
            controls = dict(zip(keys, values))
            candidate = sampler.variant_text(source, family, controls)
            ast.parse(candidate)
            patch = f"layout_{i:03d}.patch"
            (patches / patch).write_text("".join(difflib.unified_diff(source.splitlines(True), candidate.splitlines(True), fromfile="generator_snapshot.py", tofile=f"layout_{i:03d}.py")))
            candidates.append({"stream_index": i, "controls": controls, "initial64": i < 64, "patch": "layout_patches/"+patch})
        sizes = [2.5, 3, 3.5] if family in ["five_t", "compact_miller", "fvf"] else [5, 6, 7]
        size_rows = []
        for i, value in enumerate(sizes):
            sizing, arguments, gold = gold_for_size(family, plan, value)
            p = destination / f"sizing_{i}"
            p.mkdir()
            (p / "gold.spice").write_text(gold)
            size_rows.append({"id": f"s{i}", "sizing": sizing, "generator_arguments": arguments,
                "intended_gold": str(p / "gold.spice"), "gold_bound_before_GDS": True,
                "physical_qualification": "pending" if i != 1 else
                    "source and sizing qualified at old.5pF only; prospective15pF pending" if family == "legacy_miller" else
                    "qualified default at declared development application only; no formal trial"})
        contract = dict(manifest["contract"])
        if family == "fvf":
            contract["load_F"] = 15e-12
            contract["qualification"] = "Separate15pF positive control phase0_20261019T012047189356Z_fvf_validate; never relabel old10pF E2"
        if family == "legacy_miller":
            contract.pop("bench_source_unchanged")
            contract["bench_source_base"] = "testbench_snapshot.py"
            contract["prospective_window_adapter"] = "independent_legacy_domain.py retained in draft source pack"
            contract["load_F"] = 15e-12
            contract["analysis_coverage"]["transient_s"] = [0, 20e-6]
            contract["transient_window_binding"] = "scripts/independent_legacy_domain.py:5us delay/5us plateau/10us period;5ns step;8.5..9.9us and13.5..14.9us settled windows"
            contract["qualification"] = "Single15pF actual qualification pending. Failure remains in draft; no load/spec search. UGB>=1MHz and PM>=60 unchanged."
        observations = []
        for result_path in (root / "runs/phase0").glob("*_e2_development_pilot/candidate_result.json"):
            try:
                result = json.loads(result_path.read_text())
            except ValueError:
                continue
            if result.get("pool_id") == plan_id and result["status"] != "STARTING":
                observations.append(result)
        counts = {s: sum(r["status"] == s for r in observations) for s in sorted({r["status"] for r in observations})}
        stage_costs = {stage: sum(r.get("stage_wall_seconds", {}).get(stage, 0) for r in observations)
            for stage in ["generation", "geometry", "DRC", "LVS", "PEX", "electrical"]}
        draft["families"][family] = {"source_snapshot": str(destination / "generator_snapshot.py"),
            "dependency_revision": manifest["dependency_revision"],
            "source_origin": manifest.get("source_origin", str(root / "src/generators/five_t.py")),
            "contract": contract, "control_levels": levels, "sizings": size_rows,
            "candidate_stream": candidates, "initial_designed_combinations": 64, "maximum_geometry_attempts": 256,
            "development_selection_disclosure": {"observed_plan": plan_id, "observed_terminal_attempts": len(observations), "observed_status_counts": counts,
                "observed_actual_stage_wall_seconds_sum": stage_costs,
                "effect_on_proposal": "Preserve source control sites and development endpoint ranges; add declared interior levels before formal labels. No exclusion of known failing endpoint(s), no reruns chosen by prior success. Three symmetric sizing points chosen now; no nondefault-size postRC outcome observed.",
                "application_selection": "FVF15pF chosen after10pF SS58.59 failed60deg; positive-control PMmin67.11 known. Legacy15pF is a one-time load hypothesis after.5pF lowPM; outcome pending. These are explicit development-informed application choices, not a blind posthoc comparison.",
                "timeout_selection": "Old5T/compact incomplete90/120s transients stay unresolved; longer formal budgets, if adopted, must be calibrated and frozen before any formal candidate labels. Old outcomes never relabeled."}}
    shutil.copy2(root / "src/e2_mask_geometry.py", out / "e2_mask_geometry.py")
    shutil.copy2(root / "scripts/independent_legacy_domain.py", out / "independent_legacy_domain.py")
    (out / "e2_formal_draft.json").write_text(json.dumps(draft, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"status": draft["status"], "source_pack": str(out), "sizing_golds": 12,
        "layout_patches": 1024, "formal_physical_trials": 0}), flush=True)


if __name__ == "__main__":
    main()
