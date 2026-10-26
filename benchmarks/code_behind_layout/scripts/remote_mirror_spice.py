#!/usr/bin/env python3
"""Check real post-RC mirror operating points at declared pilot corners.

This is an environment/bias sanity check. It has no frozen performance limits
and does not establish the study's S2 endpoint.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--netlist", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
netlist = Path(args.netlist).resolve()
declaration = next(line.split() for line in netlist.read_text().splitlines()
                   if line.lower().startswith(".subckt "))
cell, ports = declaration[1], declaration[2:]
bindings = {"B": "0", "VSS": "0", "VOUT": "vout", "VREF": "vref"}
nodes = [bindings[port.upper()] for port in ports]
run_id = datetime.now(timezone.utc).strftime("phase0_%Y%m%dT%H%M%S%fZ_mirror_spice")
out = root / "runs/phase0" / run_id
out.mkdir(parents=True)
manifest = {"run_id": run_id, "scope": "development_post_RC_bias_sanity_no_S2_claim",
            "input_netlist": str(netlist), "port_order": ports, "node_bindings": nodes,
            "corners": ["tt", "ss", "ff"], "temperature_C": 27,
            "supply_V": 1.8, "output_drive_V": 0.9, "reference_current_A": 1e-5,
            "MOS_dimension_scale": "1e-6; extracted w/l in micrometers",
            "started_at_utc": datetime.now(timezone.utc).isoformat(), "results": {}, "status": "RUNNING"}
(out / "pilot_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
for corner in manifest["corners"]:
    work = out / corner
    work.mkdir()
    # Model compatibility is configured locally for this isolated simulator run.
    (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
    deck = "\n".join([
        "Phase0 extracted current mirror operating point",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
        ".option scale=1e-6", ".temp 27", ".include /input/mirror.spice",
        "VDD vdd 0 1.8", "IREF vdd vref 10u", "VDRIVE vout 0 0.9",
        "XDUT " + " ".join(nodes) + " " + cell,
        ".control", "op", "set wr_vecnames", "set wr_singlescale",
        "print v(vref) v(vout) i(vdrive)",
        "wrdata operating_point.dat v(vref) v(vout) i(vdrive)", "quit", ".endc", ".end", ""])
    (work / "testbench.spice").write_text(deck)
    command = ["docker", "run", "--rm", "--pull=never", "--network", "none",
               "--cpus", "1", "--memory", "2g", "--user", str(os.getuid()) + ":" + str(os.getgid()),
               "-v", str(work) + ":/work", "-w", "/work",
               "-v", str(netlist) + ":/input/mirror.spice:ro",
               "--entrypoint", "/foss/tools/ngspice/bin/ngspice",
               "hpretl/iic-osic-tools:chipathon", "-b", "-o", "ngspice.log", "testbench.spice"]
    with (work / "console.log").open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=60)
    record = {"returncode": result.returncode, "argv": command, "numeric_output_present": False}
    data = work / "operating_point.dat"
    if data.is_file():
        lines = [line.split() for line in data.read_text().splitlines() if line.strip()]
        if len(lines) == 2 and len(lines[0]) == len(lines[1]) == 4:
            values = [float(value) for value in lines[1][1:]]
            record["numeric_output_present"] = all(math.isfinite(value) for value in values)
            record["metrics"] = {"vref_V": values[0], "vout_V": values[1], "output_drive_current_A": values[2]}
    manifest["results"][corner] = record
manifest["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
manifest["status"] = ("OPERATING_POINTS_RECORDED" if all(v["returncode"] == 0 and v["numeric_output_present"] for v in manifest["results"].values()) else "INCOMPLETE")
temp = out / "pilot_manifest.json.tmp"
temp.write_text(json.dumps(manifest, indent=2) + "\n")
temp.replace(out / "pilot_manifest.json")
print(json.dumps({"run_id": run_id, "status": manifest["status"], "output": str(out), "results": manifest["results"]}, indent=2))
raise SystemExit(0 if manifest["status"] == "OPERATING_POINTS_RECORDED" else 2)
