"""Profiled host mask comparison after the curated sampler's GDS boundary.

Read only accepted GDS paths. Never inspect physical reports or electrical
labels. Existing pinned GLdev Python supplies gdstk; no new runtime is installed.
"""
import argparse
import json
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.e2_mask_geometry import read_masks, same_masks

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--inputs", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
started, cpu = time.monotonic(), time.process_time()
inputs = json.loads(a.inputs.read_text())
candidate = read_masks(inputs["candidate_gds"], inputs["excluded_layer_datatypes"])
duplicate = None
comparisons = []
new_summaries = []
prior_GDS_reads = 0
for previous in inputs["previous_masks"]:
    summary = previous.get("trusted_mask_summary")
    if summary is not None and summary["precision_um"] != candidate.precision_um:
        raise ValueError("Frozen mask cache has a different GDS database precision")
    rejected_by_summary = summary is not None and summary["layers"] != candidate.summary["layers"]
    if rejected_by_summary:
        equal = False
    else:
        prior_GDS_reads += 1
        prior = read_masks(previous["gds"], inputs["excluded_layer_datatypes"])
        equal = same_masks(candidate, prior)
        if summary is None:
            new_summaries.append({"gds": previous["gds"], "trusted_mask_summary": prior.summary})
    comparisons.append({"candidate_id": previous["candidate_id"], "source_scope": previous["source_scope"],
        "equal": equal, "rejected_by_prior_trusted_summary": rejected_by_summary,
        "exact_XOR_required_for_equality": True})
    if equal:
        duplicate = previous
        break
record = {"scope": "E2_exact_geometry_comparison_no_electrical_labels", "fidelity": "geometry",
    "candidate_gds": inputs["candidate_gds"], "duplicate": duplicate,
    "comparison_count": len(comparisons), "comparisons": comparisons, "mask_summary": candidate.summary,
    "new_prior_trusted_summaries": new_summaries,
    "actual_prior_GDS_mask_reads": prior_GDS_reads,
    "summary_cache_scope": "Only immutable accepted GDS and trusted geometry-stage summaries; unequal area/bbox rejects, equal summaries still require actual XOR",
    "wall_seconds": time.monotonic()-started, "software_CPU_seconds": time.process_time()-cpu,
    "new_DRC_LVS_PEX_SPICE_calls": 0, "new_full_GDS_copies": 0}
a.output.write_text(json.dumps(record, indent=2, allow_nan=False)+"\n")
print(json.dumps({k: v for k, v in record.items() if k not in ["comparisons", "mask_summary", "new_prior_trusted_summaries"]}), flush=True)
