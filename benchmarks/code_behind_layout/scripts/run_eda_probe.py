#!/usr/bin/env python3
"""Run a development probe on the authorized server in a CPU-only EDA container."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--script", required=True)
p.add_argument("--timeout", type=int, default=600)
p.add_argument("--input-dir", help="Existing run directory under the research root")
p.add_argument("--retry-of")
p.add_argument("--rerun-reason")
p.add_argument("--magic-runtime",choices=["installed", "magic-8.3.685"],default="installed")
p.add_argument("script_args", nargs=argparse.REMAINDER)
a = p.parse_args()
if bool(a.retry_of) != bool(a.rerun_reason):
    p.error("--retry-of and --rerun-reason must be supplied together")
root = Path(__file__).resolve().parents[1]
script = root / "scripts" / a.script
if not script.is_file() or script.parent != root / "scripts":
    p.error("script must name an existing script in this project's scripts directory")
run_id = datetime.now(timezone.utc).strftime("phase0_%Y%m%dT%H%M%S%fZ_") + script.stem
out = root / "runs/phase0" / run_id
out.mkdir(parents=True)
prefix = "/headless/conda-env/miniconda3/envs/GLdev"
magic_bin = "/foss/tools/magic/bin" if a.magic_runtime=="installed" else "/work/runtime/"+a.magic_runtime+"/bin"
name = "iscas-" + run_id.lower().replace("_", "-")
command = ["docker", "run", "--rm", "--pull=never", "--network", "none",
    "--cpus", "2", "--memory", "8g", "--name", name,
    "--user", f"{os.getuid()}:{os.getgid()}",
    "-v", str(root) + ":/work", "-v", str(root / "vendor/glayout") + ":/work/vendor/glayout:ro",
    "-v", str(root / "runtime/GLdev") + ":" + prefix + ":ro",
    "-w", "/work/runs/phase0/" + run_id,
    "-e", "PYTHONPATH=/work/vendor/glayout/src", "-e", "PDK_ROOT=/foss/pdks",
    "-e", "CONDA_PREFIX=" + prefix, "-e", "OMP_NUM_THREADS=1", "-e", "OPENBLAS_NUM_THREADS=1",
    "-e", "PATH=" + prefix + "/bin:"+magic_bin+":/foss/tools/netgen/bin:/foss/tools/ngspice/bin:/usr/local/bin:/usr/bin:/bin",
    "--entrypoint", prefix + "/bin/python", "hpretl/iic-osic-tools@sha256:7ef29be71a33b5b8994cde7f7476dfefd1af94f2922354242d1579346feec462",
    "-u", "/work/runs/phase0/" + run_id + "/profile_probe.py",
    "/work/runs/phase0/" + run_id + "/" + script.name]
command.extend(a.script_args[1:] if a.script_args[:1] == ["--"] else a.script_args)
if a.input_dir:
    input_dir = Path(a.input_dir).resolve()
    relative_input = input_dir.relative_to(root)
    if not input_dir.is_dir():
        p.error("input directory does not exist")
    command[command.index("--entrypoint"):command.index("--entrypoint")] = [
        "-e", "PROBE_INPUT=/work/" + str(relative_input)]
manifest = {"run_id": run_id, "phase": "development_pilot", "script": script.name,
    "magic_runtime":a.magic_runtime,
    "source_commit": subprocess.check_output(["git", "-C", str(root / "vendor/glayout"), "rev-parse", "HEAD"], text=True).strip(),
    "argv": command, "input_directory": a.input_dir, "retry_of":a.retry_of,"rerun_reason":a.rerun_reason,
    "started_at_utc": datetime.now(timezone.utc).isoformat(), "status": "RUNNING"}
(out / script.name).write_text(script.read_text())
(out / "profile_probe.py").write_text((root / "scripts/profile_probe.py").read_text())
(out / "pilot_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"run_id": run_id, "output": str(out)}), flush=True)
with (out / "console.log").open("w") as log:
    try:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=a.timeout)
        manifest.update(returncode=result.returncode, status="TOOL_COMPLETED" if result.returncode == 0 else "FAILED")
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "stop", "--time", "5", name], stdout=log, stderr=subprocess.STDOUT, timeout=20)
        manifest.update(returncode=None, status="TIMEOUT")
manifest["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
(out / "pilot_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2), flush=True)
raise SystemExit(0 if manifest["returncode"] == 0 else 2)
