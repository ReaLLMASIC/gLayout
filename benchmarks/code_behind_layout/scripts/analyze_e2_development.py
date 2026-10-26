"""Analyze a completed development pool under explicit, saved tie/frontier rules."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.fidelity_analysis import rank_diagnostics, finite_pool_selection


def analyze(pool, rule):
    if not pool["all_candidate_attempts_terminal"]:
        raise ValueError("Preserve running candidates; analyze only the completed frozen stream")
    rows, seen = [], set()
    for attempt in sorted(pool["attempts"], key=lambda row: row["stream_index"]):
        result = attempt["result"]
        digest = result.get("L0", {}).get("canonical_polygon_digest")
        if not digest or digest in seen:
            continue
        seen.add(digest)
        row = {"candidate_id": attempt["candidate_id"], "feasible": result.get("all_corner_development_feasible", False),
               **result.get("L0", {}), "worst_corner_ugb_Hz": result.get("worst_corner_metrics", {}).get("ugb_Hz")}
        # Old raw development records retain their original L1 key. These values
        # are still explicitly post-PEX features; no acquisition is reclassified.
        parasitics = result.get("post_PEX_features", result.get("L1", {}))
        r, c = parasitics.get("R_sum_ohm"), parasitics.get("C_sum_F")
        if r and c:
            row["post_PEX_one_pole_proxy_Hz"] = 1 / (2*math.pi*r*c)
        nominal = [value["ugb_Hz"] for value in result.get("electrical", {}).get("results", {}).values()
                   if value.get("corner") == "tt" and "ugb_Hz" in value]
        if len(nominal) == 1:
            row["nominal_ugb_Hz"] = nominal[0]
        rows.append(row)
    measured = [row for row in rows if row.get("worst_corner_ugb_Hz") is not None]
    size = max(1, math.ceil(len(rows)*rule["near_frontier"]["fraction"]))
    frontier = {row["candidate_id"] for row in sorted(rows, key=lambda row: (row["footprint_area_um2"], row["candidate_id"]))[:size]}
    def describe(subset):
        outputs = {}
        for name in ("post_PEX_one_pole_proxy_Hz", "nominal_ugb_Hz", "footprint_area_um2", "wirelength_rectilinear_proxy_um"):
            selected = [row for row in subset if name in row]
            if len(selected) < 2:
                outputs[name] = {"n": len(selected), "status": "insufficient_measured_pairs"}
                continue
            tie = rule["numerical_tie"]
            result = rank_diagnostics([row[name] for row in selected], [row["worst_corner_ugb_Hz"] for row in selected],
                prediction_absolute_tolerance=tie["absolute_Hz"] if name.endswith("Hz") else 0,
                actual_absolute_tolerance=tie["absolute_Hz"], relative_tolerance=tie["relative"])
            if not name.endswith("Hz"):
                result = {key: result[key] for key in ("n", "spearman_exact_ties", "kendall_tau_b_declared_ties")}
                result["interpretation"] = "descriptive association, not prediction accuracy or reversal error"
            outputs[name] = result
        return outputs
    return {"scope": "development_E2_finite_pool_diagnostics_not_formal_results", "pool_id": pool["pool_id"],
            "analysis_rule": rule, "all_attempts": pool["attempt_count"], "geometry_unique": len(rows),
            "complete_circuit_measurements": len(measured), "feasible": sum(row["feasible"] for row in rows),
            "broad_pool": describe(measured), "predefined_near_frontier_ids": sorted(frontier),
            "near_frontier": describe([row for row in measured if row["candidate_id"] in frontier]),
            "finite_pool": finite_pool_selection(rows, [], objective=rule["objective"], direction=rule["direction"]),
            "rows": rows, "selection_policy_comparison": "not_run_by_this_descriptive_analysis"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pool", type=Path)
    parser.add_argument("--rule", type=Path, default=ROOT / "configs/development/e2_analysis.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(json.loads(args.pool.read_text()), json.loads(args.rule.read_text()))
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("pool_id", "all_attempts", "geometry_unique", "complete_circuit_measurements", "feasible")}))
