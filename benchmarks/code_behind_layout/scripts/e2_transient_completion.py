"""A4 transient-completion pass for E2 full-oracle candidates recorded unknown.

Amendment A4 (docs/protocol_amendments_20261019.md): candidates recorded as unknown
because a transient analysis exceeded the original 90 s inner limit are re-simulated
once with a 4x inner limit, on the retained extracted netlist and identical deck,
labelled ``transient_completion_v1``. Original records and the frozen rule stay
unchanged; the finite-pool oracle is reported both under the frozen rule (undefined
while unknowns exist) and under the completion rule.

Run on the trusted server from the repository root with the GLdev interpreter::

    runtime/GLdev/bin/python scripts/e2_transient_completion.py \
        --pool runs/formal/E2/full_oracle/five_t_s0 \
        --output runs/formal/E2/transient_completion_v1/five_t_s0 --execute

The archived frozen bench of each candidate is re-run inside the same pinned
executor image with the same mounts, privileges and resource limits as the
original trusted stage.  The only source change is the per-analysis timeout of
the transient analysis (90 s -> 90 s x factor); the modified bench is written as a
new file next to the archived original and the unified diff is recorded.
"""
import argparse
import difflib
import json
import shutil
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.measurement import assess  # noqa: E402

IMAGE = "hpretl/iic-osic-tools@sha256:7ef29be71a33b5b8994cde7f7476dfefd1af94f2922354242d1579346feec462"
LABEL = "transient_completion_v1"
GLDEV = "/headless/conda-env/miniconda3/envs/GLdev"
PYTHON = GLDEV + "/bin/python"
ORIGINAL_INNER_TIMEOUT_S = 90
BENCH_OUTER_TIMEOUT_S = 1200
UNITS = {"gain": ("gain_10Hz_dB", "dB"), "ugb": ("ugb_Hz", "Hz"), "phase_margin": ("phase_margin_deg", "deg"),
         "settled_tracking_error": ("settled_tracking_error_V", "V"), "power": ("power_W", "W")}


def now():
    return datetime.now(timezone.utc).isoformat()


def corners_from_measurements(measurements, kind):
    """Verbatim post-processing of scripts/ota_frozen_bench.run_post_rc for the measured corners."""
    corners = {}
    for name, row in measurements.get("results", {}).items():
        corner = row["corner"]
        op_field = "operating_point_integrity" if kind == "five_t" else "op_integrity"
        complete = bool(row.get(op_field, {}).get("complete") and set(row.get("analyses", {})) == {"ac", "tran", "dc"}
                        and all(v.get("returncode") == 0 and v.get("integrity", {}).get("complete") for v in row["analyses"].values()))
        metrics = {}
        if complete:
            metrics = {target: {"value": row[source], "unit": unit} for target, (source, unit) in UNITS.items() if source in row}
            metrics["nominal_tracking_error"] = {"value": abs(row["output_V"] - (1.1 if kind == "five_t" else 1.05)), "unit": "V"}
        healthy = bool(complete and row.get("positive_low_frequency_gain") and .15 < row["tail_V"] < .8)
        if healthy and kind == "five_t":
            healthy = .4 < row["mirror_V"] < 1.6 and 20e-6 < row["supply_current_A"] < 80e-6
        if healthy and kind == "compact_miller":
            healthy = .3 < row["stage1_V"] < 1.2 and 50e-6 < row["supply_current_A"] < 160e-6
        corners[corner] = {"complete": complete, "converged": complete, "operating_point_valid": bool(healthy), "metrics": metrics,
                           "original_development_constraints_passed": bool(row.get("development_feasible" if kind == "five_t" else "development_nominal_feasible")),
                           "analyses": {k: {"returncode": v.get("returncode"), "timeout": v.get("timeout"), "wall_seconds": v.get("wall_seconds")}
                                        for k, v in row.get("analyses", {}).items()}}
        if complete:
            metrics["original_development_predicate"] = {"value": float(corners[corner]["original_development_constraints_passed"]), "unit": "1"}
    return corners


def extract_evidence(archive, work):
    with tarfile.open(archive) as tar:
        members = [m for m in tar.getmembers()
                   if (m.name.startswith("evidence/post_rc_measurements/") or m.name == "evidence/validation.json")
                   and ".." not in m.name and not m.issym() and not m.islnk()]
        tar.extractall(work, members=members)
    return work / "evidence" / "post_rc_measurements", work / "evidence" / "validation.json"


def run_candidate(entry, args, kind):
    index = entry["stream_index"]
    run_dir = Path(entry["full_electrical"]["run_directory"])
    archive = run_dir / "terminal_raw.tar.gz"
    work = args.output / f"{index:03d}_{run_dir.name}"
    result_path = work / "result.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    record = {"label": LABEL, "stream_index": index, "original_run_directory": str(run_dir), "archive": str(archive),
              "started_at_utc": now(), "factor": args.factor, "transient_inner_timeout_s": ORIGINAL_INNER_TIMEOUT_S * args.factor}
    prm, validation_path = extract_evidence(archive, work)
    validation = json.loads(validation_path.read_text())
    contract = validation["contract"]
    observation = validation["observation"]
    record["original_assessment"] = validation["assessment"]
    # The pass applies only to candidates whose transient hit the original inner limit.
    timeouts = {}
    for corner_dir in sorted(prm.glob("*_[0-9]*pF")):
        resource = corner_dir / "tran_process_resource.json"
        if resource.exists():
            data = json.loads(resource.read_text())
            timeouts[corner_dir.name] = {"original_timeout_s": data.get("original_timeout_s"), "exception": data.get("exception"),
                                         "wall_seconds": data.get("wall_seconds")}
    record["original_transient_resources"] = timeouts
    if not any(v.get("exception") == "TimeoutExpired" and v.get("original_timeout_s") == ORIGINAL_INNER_TIMEOUT_S for v in timeouts.values()):
        record.update(status="NOT_ELIGIBLE_NO_TRANSIENT_TIMEOUT", ended_at_utc=now())
        result_path.write_text(json.dumps(record, indent=2) + "\n")
        return record
    # Keep the archived corner outputs and summaries under original_* names.
    for item in list(prm.iterdir()):
        if item.is_dir() and item.name.endswith("pF") or item.name in ("measurements.json", "normalized.json", "bench_console.log"):
            item.rename(prm / ("original_" + item.name))
    original_bench = (prm / "frozen_bench.py").read_text()
    anchor = "stdout=log, stderr=subprocess.STDOUT, timeout=90)"
    if original_bench.count(anchor) != 1:
        record.update(status="FAILED_BENCH_TIMEOUT_SITE_NOT_UNIQUE", ended_at_utc=now())
        result_path.write_text(json.dumps(record, indent=2) + "\n")
        return record
    modified = original_bench.replace(anchor, "stdout=log, stderr=subprocess.STDOUT, timeout=(%d if analysis == \"tran\" else 90))" % (ORIGINAL_INNER_TIMEOUT_S * args.factor))
    bench_name = "frozen_bench_%s.py" % LABEL
    (prm / bench_name).write_text(modified)
    (prm / ("bench_%s.patch" % LABEL)).write_text("".join(difflib.unified_diff(
        original_bench.splitlines(True), modified.splitlines(True), fromfile="frozen_bench.py", tofile=bench_name)))
    launcher_source = (prm / "run_bench.py").read_text()
    launcher_modified = launcher_source.replace("/evidence/post_rc_measurements/frozen_bench.py", "/evidence/post_rc_measurements/" + bench_name)
    if launcher_modified == launcher_source:
        record.update(status="FAILED_LAUNCHER_SITE_NOT_FOUND", ended_at_utc=now())
        result_path.write_text(json.dumps(record, indent=2) + "\n")
        return record
    launcher_name = "run_bench_%s.py" % LABEL
    (prm / launcher_name).write_text(launcher_modified)
    name = "iscas-tc-%03d-%s" % (index, datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S%f"))
    command = ["docker", "run", "--pull=never", "--name", name, "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "KILL", "--security-opt", "no-new-privileges",
               "--pids-limit", "128", "--cpus", "2", "--memory", "8g", "--user", "0:0",
               "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m,mode=1777", "--mount", "type=volume,target=/telemetry",
               "-v", str(ROOT / "runtime/GLdev") + ":" + GLDEV + ":ro",
               "-v", str(run_dir / "launcher.py") + ":/launcher.py:ro",
               "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "OMP_NUM_THREADS=1", "-e", "OPENBLAS_NUM_THREADS=1",
               "-v", str(work / "evidence") + ":/evidence:rw",
               "-v", str(ROOT / "src") + ":/trusted/src:ro",
               "-w", "/evidence/post_rc_measurements", "-e", "PYTHONPATH=/trusted", "-e", "PDK_ROOT=/foss/pdks",
               "-e", "PATH=" + GLDEV + "/bin:/work/runtime/magic-8.3.685/bin:/foss/tools/netgen/bin:/foss/tools/ngspice/bin:/usr/bin:/bin",
               "--entrypoint", PYTHON, IMAGE, "/launcher.py", "1044", "1045", PYTHON, "/evidence/post_rc_measurements/" + launcher_name]
    record["container"] = {"name": name, "image": IMAGE, "argv": command}
    started = time.monotonic()
    timed_out = False
    with (work / "container_console.log").open("w") as log:
        try:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=BENCH_OUTER_TIMEOUT_S + 3 * ORIGINAL_INNER_TIMEOUT_S * args.factor)
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
            subprocess.run(["docker", "kill", name], capture_output=True, timeout=30)
    subprocess.run(["docker", "cp", name + ":/telemetry/resource_usage.json", str(work / "resource_usage.json")], capture_output=True, timeout=60)
    subprocess.run(["docker", "rm", "-v", name], capture_output=True, timeout=60)
    record["container"].update(returncode=returncode, outer_timeout=timed_out, wall_seconds=time.monotonic() - started)
    measurement_file = prm / "measurements.json"
    measurements = json.loads(measurement_file.read_text()) if measurement_file.exists() else {"results": {}}
    corners = corners_from_measurements(measurements, kind)
    new_resources = {}
    for corner_dir in sorted(prm.glob("*_[0-9]*pF")):
        if corner_dir.name.startswith("original_"):
            continue
        resource = corner_dir / "tran_process_resource.json"
        if resource.exists():
            data = json.loads(resource.read_text())
            new_resources[corner_dir.name] = {"timeout_s": data.get("original_timeout_s"), "exception": data.get("exception"),
                                              "returncode": data.get("returncode"), "wall_seconds": data.get("wall_seconds"),
                                              "child_user_cpu_seconds": data.get("waited_child_user_CPU_seconds")}
    record["transient_resources"] = new_resources
    completion_observation = dict(observation)
    completion_observation["corners"] = {c: {k: v for k, v in row.items() if k in ("complete", "converged", "operating_point_valid", "metrics")}
                                         for c, row in corners.items()}
    assessment = assess(contract, completion_observation)
    all_complete = set(corners) == set(contract["required_corners"]) and all(row["complete"] for row in corners.values())
    worst_ugb = None
    if all_complete and all("ugb" in row["metrics"] for row in corners.values()):
        worst_ugb = min(row["metrics"]["ugb"]["value"] for row in corners.values())
    record.update(corners=corners, assessment=assessment, complete=bool(all_complete and not timed_out),
                  S2=bool(assessment.get("S2")), worst_ugb_Hz=worst_ugb,
                  status="COMPLETE" if all_complete and not timed_out else "STILL_INCOMPLETE", ended_at_utc=now())
    result_path.write_text(json.dumps(record, indent=2, default=str) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--factor", type=int, default=4)
    parser.add_argument("--only", type=int, nargs="*", help="restrict to these stream indices (smoke run)")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    args.pool = args.pool.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    state = json.loads((args.pool / "state.json").read_text())
    kind = "five_t" if "five_t" in args.pool.name else "compact_miller" if "miller" in args.pool.name else None
    if kind is None:
        raise SystemExit("Only the OTA pools with the frozen OTA bench are supported")
    unknown = [f for f in state["full_evaluations"] if not f.get("complete", True)]
    if args.only:
        unknown = [f for f in unknown if f["stream_index"] in set(args.only)]
    summary = {"label": LABEL, "pool": str(args.pool), "pool_status": state.get("status"), "started_at_utc": now(),
               "frozen_rule": {"unknown_candidates": sum(1 for f in state["full_evaluations"] if not f.get("complete", True)),
                               "finite_pool_oracle": "undefined while unknowns exist"},
               "selected": [f["stream_index"] for f in unknown], "results": {}}
    (args.output / "state.json").write_text(json.dumps({**summary, "status": "RUNNING"}, indent=2) + "\n")
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for record in pool.map(lambda f: run_candidate(f, args, kind), unknown):
            summary["results"][str(record["stream_index"])] = {k: record.get(k) for k in ("status", "complete", "S2", "worst_ugb_Hz", "transient_resources")}
    original_s2 = [f["worst_ugb_Hz"] for f in state["full_evaluations"] if f.get("S2") and f.get("worst_ugb_Hz") is not None]
    new_s2 = [r["worst_ugb_Hz"] for r in summary["results"].values() if r.get("S2") and r.get("worst_ugb_Hz") is not None]
    remaining_unknown = sum(1 for r in summary["results"].values() if not r.get("complete"))
    summary["completion_rule"] = {"S2_count": len(original_s2) + len(new_s2), "newly_complete": sum(1 for r in summary["results"].values() if r.get("complete")),
                                  "newly_S2": len(new_s2), "remaining_unknown": remaining_unknown,
                                  "finite_pool_oracle_best_Hz": max(original_s2 + new_s2) if (original_s2 + new_s2) else None,
                                  "original_best_Hz": max(original_s2) if original_s2 else None,
                                  "oracle_best_changed": bool(new_s2 and max(new_s2) > (max(original_s2) if original_s2 else float("-inf"))),
                                  "finite_pool_oracle_defined": remaining_unknown == 0}
    summary["status"] = "COMPLETE" if remaining_unknown == 0 else "COMPLETE_WITH_REMAINING_UNKNOWNS"
    summary["ended_at_utc"] = now()
    (args.output / "state.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["completion_rule"]))


if __name__ == "__main__":
    main()
