"""Write a new E2 candidate snapshot that applies the A4 transient-completion results.

The frozen-rule snapshot is left untouched; a new snapshot file (sorting last, so the
figure script picks it up) carries the completion-rule view for the candidates that the
``transient_completion_v1`` pass completed, and records the frozen-rule view beside it.

    python3 scripts/e2_apply_transient_completion.py \
        --completion results/derived/E2_transient_completion_v1_five_t_s0 --pool five_t_s0
"""
import argparse
import glob
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--completion", type=Path, required=True, help="local copy of the pass output (state.json + */result.json)")
    parser.add_argument("--pool", required=True, help="pool name, e.g. five_t_s0")
    parser.add_argument("--method", default="full_oracle", help="method prefix of the snapshot pool key (default full_oracle)")
    args = parser.parse_args()
    latest = sorted(glob.glob(str(ROOT / "results/derived/E2_formal_candidates_snapshot_*.json")))[-1]
    snapshot = json.loads(Path(latest).read_text())
    state = json.loads((args.completion / "state.json").read_text())
    if state.get("status") not in ("COMPLETE", "COMPLETE_WITH_REMAINING_UNKNOWNS"):
        raise SystemExit("completion pass not finished: " + str(state.get("status")))
    results = {}
    for path in sorted(args.completion.glob("*/result.json")):
        record = json.loads(path.read_text())
        results[int(record["stream_index"])] = record
    method = args.method
    pool = snapshot["pools"][method + "/" + args.pool]
    frozen_view = []
    applied = []
    for entry in pool["full_evaluations"]:
        if entry.get("complete", True):
            continue
        record = results.get(int(entry["stream_index"]))
        frozen_view.append(dict(entry))
        if record is None or record.get("status") != "COMPLETE":
            continue
        entry["complete"] = True
        entry["S2"] = bool(record["S2"])
        entry["worst_ugb_Hz"] = record.get("worst_ugb_Hz")
        entry["electrical_status"] = "complete_under_transient_completion_v1"
        entry["completion_rule"] = {"label": "transient_completion_v1", "transient_inner_timeout_s": record.get("transient_inner_timeout_s"),
                                    "transient_wall_seconds": {c: r.get("wall_seconds") for c, r in (record.get("transient_resources") or {}).items()},
                                    "result": str(args.completion / ("%03d_" % entry["stream_index"])) }
        applied.append(entry["stream_index"])
    if not any(not f.get("complete", True) for f in pool["full_evaluations"]):
        pool["finite_pool_oracle_defined"] = True  # completion rule: no unknown candidate remains
        pool["finite_pool_oracle_rule"] = "transient_completion_v1"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    out = ROOT / "results/derived" / ("E2_formal_candidates_snapshot_%s.json" % stamp)
    snapshot["at_utc"] = datetime.now(timezone.utc).isoformat()
    snapshot["source"] = str(snapshot.get("source")) + " | completion rule applied from %s (amendment A4, transient_completion_v1) on pool %s/%s, candidates %s; frozen-rule entries retained under frozen_rule_view" % (
        args.completion, method, args.pool, applied)
    snapshot.setdefault("frozen_rule_view", {})[method + "/" + args.pool] = frozen_view
    snapshot["transient_completion_v1"] = {"method": method, "pool": args.pool, "applied_stream_indices": applied, "pass_state": state.get("status"),
                                           "completion_rule": state.get("completion_rule"), "base_snapshot": Path(latest).name}
    out.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(out.name, "applied", applied)


if __name__ == "__main__":
    main()
