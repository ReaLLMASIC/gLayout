#!/usr/bin/env python3
"""Run an existing SMGR DRC/LVS pilot in the recovered, CPU-only EDA image.

Run this script on the research server after the frozen source worktree and
private image exist. This pilot does not run PEX/SPICE or establish S2.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["current_mirror_nfet", "opamp", "opamp_twostage", "super_class_ab_ota"],
                        default="current_mirror_nfet")
    parser.add_argument("--retry-of", help="Previous pilot run ID, when rerunning")
    parser.add_argument("--rerun-reason", help="Explicit infrastructure repair reason")
    args = parser.parse_args()
    if bool(args.retry_of) != bool(args.rerun_reason):
        parser.error("--retry-of and --rerun-reason must be supplied together")
    root = Path(__file__).resolve().parents[1]
    if not (root / "vendor/glayout/tests/run_smgr_regression.py").is_file():
        raise SystemExit("Frozen remote SMGR worktree is missing")
    run_id = datetime.now(timezone.utc).strftime("phase0_%Y%m%dT%H%M%S%fZ_") + args.case
    output = root / "runs/phase0" / run_id
    output.mkdir(parents=True)
    container = "iscas-" + run_id.lower().replace("_", "-")
    image = "hpretl/iic-osic-tools:chipathon"
    runtime = root / "runtime/GLdev"
    if not (runtime / "bin/python").exists():
        raise SystemExit("Recovered GLdev environment is missing")
    prefix = "/headless/conda-env/miniconda3/envs/GLdev"
    script = "\n".join([
        "set -euo pipefail",
        'export CONDA_PREFIX=' + prefix,
        'export PATH="' + prefix + '/bin:/foss/tools/magic/bin:/foss/tools/netgen/bin:/foss/tools/ngspice/bin:$PATH"',
        "export PDK_ROOT=/foss/pdks",
        "export PYTHONPATH=/work/vendor/glayout/src",
        "cd /work/runs/phase0/" + run_id,
        "python -u /work/vendor/glayout/tests/run_smgr_regression.py --cases " + args.case +
        " --output-dir /work/runs/phase0/" + run_id,
    ])
    command = ["docker", "run", "--rm", "--pull=never", "--network", "none",
               "--cpus", "2", "--memory", "8g", "--name", container,
               "--user", str(os.getuid()) + ":" + str(os.getgid()),
               "-e", "OMP_NUM_THREADS=1", "-e", "OPENBLAS_NUM_THREADS=1",
               "-v", str(root) + ":/work",
               "-v", str(root / "vendor/glayout") + ":/work/vendor/glayout:ro",
               "-v", str(runtime) + ":" + prefix + ":ro",
               "--entrypoint", "/bin/bash", image, "-c", script]
    source_commit = subprocess.check_output(
        ["git", "-C", str(root / "vendor/glayout"), "rev-parse", "HEAD"], text=True).strip()
    source_diff = subprocess.check_output(
        ["git", "-C", str(root / "vendor/glayout"), "diff", "HEAD"], text=True)
    if source_diff:
        (output / "source.patch").write_text(source_diff)
    manifest = {"run_id": run_id, "phase": "development_pilot",
                "scope": "existing_SMGR_DRC_LVS_only_no_PEX_SPICE",
                "case": args.case, "source_commit": source_commit,
                "source_has_uncommitted_patch": bool(source_diff),
                "image": image, "container": container, "argv": command,
                "retry_of": args.retry_of, "rerun_reason": args.rerun_reason,
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "timeout_seconds": 300, "status": "RUNNING"}
    (output / "pilot_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with (output / "console.log").open("w") as log:
        try:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=300)
            manifest.update(returncode=result.returncode,
                            status="TOOL_COMPLETED" if result.returncode == 0 else "FAILED")
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "stop", "--time", "5", container],
                           stdout=log, stderr=subprocess.STDOUT, timeout=20)
            manifest.update(returncode=None, status="TIMEOUT")
    manifest["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    temp = output / "pilot_manifest.json.tmp"
    temp.write_text(json.dumps(manifest, indent=2) + "\n")
    temp.replace(output / "pilot_manifest.json")
    print(json.dumps({"run_id": run_id, "status": manifest["status"], "output": str(output)}, indent=2))
    return 0 if manifest["status"] == "TOOL_COMPLETED" else 2


if __name__ == "__main__":
    sys.exit(main())
