"""Back up terminal engineering runs, excluding private configuration domains."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def backup(name, mutable):
    selected, excluded = [], []
    for directory in sorted((ROOT / "runs/phase0").iterdir()):
        if not directory.is_dir():
            continue
        if directory.name.endswith(("_domain_smoke", "_independent_task_preflight", "_ota_task_preflight",
                                    "_materialize_e1_packets", "_e1_schematic_feasibility", "_e1_exact_grid_domain",
                                    "_revise_e1_mirror_domain")):
            excluded.append({"run_id": directory.name, "reason": "private_configuration_domain_not_exportable_to_policy_host"})
            continue
        if directory.name in mutable:
            excluded.append({"run_id": directory.name, "reason": "terminal_plan_process_but_active_pool_metadata"})
            continue
        try:
            manifest = json.loads((directory / "pilot_manifest.json").read_text())
        except (OSError, ValueError):
            excluded.append({"run_id": directory.name, "reason": "no_readable_terminal_manifest"})
            continue
        if manifest.get("status") not in ["TOOL_COMPLETED", "FAILED", "TIMEOUT"]:
            excluded.append({"run_id": directory.name, "reason": "still_running"})
            continue
        selected.append(directory)
    archive = ROOT / "private_checkpoints" / (name + ".tar.gz")
    with tarfile.open(archive, "x:gz") as stream:
        for directory in selected:
            stream.add(directory, arcname=str(directory.relative_to(ROOT)))
    record = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "archive": str(archive),
        "bytes": archive.stat().st_size, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "selected_run_count": len(selected), "selected_run_ids": [path.name for path in selected], "excluded": excluded,
        "scope": "Terminal development records only; all hidden task tables and GDS remain on the execution endpoint"}
    with archive.with_suffix("").with_suffix(".json").open("x") as index:
        json.dump(record, index, indent=2)
        index.write("\n")
    return {key: record[key] for key in ["archive", "bytes", "sha256", "selected_run_count"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--mutable-plan", action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(backup(args.name, set(args.mutable_plan))))
