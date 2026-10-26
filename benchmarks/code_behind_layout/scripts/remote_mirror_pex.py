#!/usr/bin/env python3
"""Extract real R/C for the inspected Phase 0 mirror GDS; no S2 claim."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--gds", required=True)
parser.add_argument("--cell", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
gds = Path(args.gds).resolve()
run_id = datetime.now(timezone.utc).strftime("phase0_%Y%m%dT%H%M%S%fZ_mirror_rc")
out = root / "runs/phase0" / run_id
out.mkdir(parents=True)
name = "iscas-" + run_id.lower().replace("_", "-")
command = ["docker", "run", "--rm", "--pull=never", "--network", "none",
           "--cpus", "2", "--memory", "8g", "--name", name,
           "--user", str(os.getuid()) + ":" + str(os.getgid()),
           "-v", str(gds) + ":/input/layout.gds:ro",
           "-v", str(out) + ":/work", "-w", "/work",
           "-v", str(root / "vendor/glayout/src/glayout/verification/run_pex.sh") + ":/verification/run_pex.sh:ro",
           "-e", "PDK_ROOT=/foss/pdks",
           "-e", "PATH=/foss/tools/magic/bin:/foss/tools/ngspice/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
           "--entrypoint", "/bin/bash", "hpretl/iic-osic-tools:chipathon",
           "/verification/run_pex.sh", "/input/layout.gds", args.cell]
manifest = {"run_id": run_id, "scope": "development_RC_extraction_probe",
            "input_gds": str(gds), "top_cell": args.cell, "argv": command,
            "source_commit": subprocess.check_output(["git", "-C", str(root / "vendor/glayout"), "rev-parse", "HEAD"], text=True).strip(),
            "started_at_utc": datetime.now(timezone.utc).isoformat(), "status": "RUNNING"}
(out / "pilot_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
with (out / "console.log").open("w") as log:
    try:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        manifest["returncode"] = result.returncode
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "stop", "--time", "5", name], stdout=log, stderr=subprocess.STDOUT, timeout=20)
        manifest["returncode"] = None
netlist = out / (args.cell + "_pex.spice")
counts = {}
if netlist.is_file():
    lines = netlist.read_text(errors="replace").splitlines()
    counts = {kind: sum(bool(re.match(r"^\s*" + kind + r"\S*\s+", line, re.I)) for line in lines)
              for kind in ("R", "C", "M", "X")}
manifest["element_counts"] = counts
manifest["status"] = ("EXTRACTED_RC" if manifest["returncode"] == 0 and counts.get("R", 0) > 0 and counts.get("C", 0) > 0 else "INCOMPLETE")
manifest["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
temp = out / "pilot_manifest.json.tmp"
temp.write_text(json.dumps(manifest, indent=2) + "\n")
temp.replace(out / "pilot_manifest.json")
print(json.dumps({"run_id": run_id, "status": manifest["status"], "output": str(out), "element_counts": counts}, indent=2))
raise SystemExit(0 if manifest["status"] == "EXTRACTED_RC" else 2)
