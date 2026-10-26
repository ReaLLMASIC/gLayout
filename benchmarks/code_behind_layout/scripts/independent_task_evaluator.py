"""Trusted evaluator for the five declared independent source domains.

Only the GDS enters this process. Its reference, contract and the exact verified
bench function body are supplied by the read-only trusted snapshot.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import gdstk

sys.path.insert(0, "/trusted")
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
from src.measurement import assess
import bench

parser = argparse.ArgumentParser()
parser.add_argument("--gds")
parser.add_argument("--output")
parser.add_argument("--fidelity")
args = parser.parse_args()
out = Path(args.output)
gds = Path(args.gds)
meta = json.loads(Path("/trusted/meta.json").read_text())
contract = json.loads(Path("/trusted/contract.json").read_text())
configuration = json.loads(Path("/configuration.json").read_text())
if configuration != contract["immutable_parameters"]:
    raise ValueError("Independent reference and immutable configuration differ")
name = meta["circuit"]
library = gdstk.read_gds(gds)
top, = library.top_level()
if top.name != name:
    raise ValueError("Candidate top differs from the independent reference")
box = top.bounding_box()
area = float((box[1][0] - box[0][0]) * (box[1][1] - box[0][1]) * (library.unit / 1e-6) ** 2)
observation = {key: contract[key] for key in ["task_id", "configuration_id", "reference_id"]}
observation.update(executed=True, gds_emitted=True, checks={}, corners={})
artifacts = {"spice": {}}
drc = {}


def save():
    assessment = assess(contract, observation)
    complete = all(observation["corners"].get(c, {}).get("converged") is True for c in contract["required_corners"])
    rejected = ((drc.get("completed") is True and observation["checks"].get("drc") is False)
                or ("lvs" in artifacts and observation["checks"].get("lvs") is False))
    result = {"contract": contract, "observation": observation, "artifacts": artifacts, "assessment": assessment,
        "analysis_complete": complete, "point_evaluation_complete": complete or rejected,
        "execution_integrity": "valid" if complete or rejected else "incomplete",
        "failure_class": None if assessment["S2"] else "candidate" if complete or rejected else "unknown",
        "scope": "development_independent_trusted_point_no_candidate_source_import"}
    (out / "validation.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def magic(lines, stem):
    text = "\n".join(lines + ["puts stdout EXTRACTION_COMPLETE", "quit -noprompt", ""])
    (out / (stem + ".tcl")).write_text(text)
    with (out / (stem + ".log")).open("w") as log:
        result = subprocess.run(["magic", "-rcfile", "/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc", "-noconsole", "-dnull"],
            input=text, text=True, cwd=out, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    if result.returncode:
        raise RuntimeError("Magic failed; raw log retained")


drc = check_gds(gds, out / "drc", timeout=120)
(out / "drc/metadata.json").write_text(json.dumps(drc, indent=2) + "\n")
artifacts["drc"] = {"report": "drc/direct_drc.rpt", "metadata": "drc/metadata.json"}
observation["checks"]["drc"] = drc["is_clean"]
save()
magic(["drc off", "gds read {" + str(gds) + "}", "load " + name, "select top cell", "flatten " + name + "_lvs",
       "load " + name + "_lvs", "select top cell", "extract all", "ext2spice lvs", "ext2spice -o extracted_lvs.spice"], "lvs_extract")
with (out / "netgen.log").open("w") as log:
    result = subprocess.run(["netgen", "-batch", "lvs", str(out / "extracted_lvs.spice") + " " + name + "_lvs",
        "/trusted/reference.spice " + name, "/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl", str(out / "lvs.rpt")],
        stdout=log, stderr=subprocess.STDOUT, timeout=120)
lvs = netgen_lvs_report((out / "lvs.rpt").read_text() if (out / "lvs.rpt").is_file() else "")
clean = lvs["is_clean"] and result.returncode == 0
for key in ["lvs", "devices", "ports", "intent"]:
    observation["checks"][key] = clean
artifacts["lvs"] = {"report": "lvs.rpt"}
save()
if not drc["completed"]:
    raise RuntimeError("DRC did not complete")
if not drc["is_clean"] or not clean:
    raise SystemExit(2)
if args.fidelity == "pex_spice":
    cell = name + "_rc"
    netlist = out / (name + "_pex.spice")
    magic(["drc off", "gds read {" + str(gds) + "}", "load " + name, "select top cell", "flatten " + cell,
           "load " + cell, "select top cell", "extract do local", "extract all", "feedback save extraction_feedback.tcl",
           "ext2sim labels on", "ext2sim", "extresist simplify off", "extresist all", "ext2spice lvs",
           "ext2spice cthresh 0", "ext2spice extresist on", "ext2spice -o " + netlist.name], "rc_extract")
    inventory = rc_netlist_inventory(netlist.read_text(), cell, meta["ports"])
    (out / "rc_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    artifacts["pex"] = {"netlist": netlist.name, "top_cell": cell, "ports": meta["ports"]}
    real = inventory["has_real_RC"]
    observation["pex"] = {"executed": True, "kind": "physical_rc", "resistance_extracted": real, "capacitance_extracted": real}
    save()
    if not real:
        raise SystemExit(2)
    bench.out = out
    if meta["bench_function"] == "corner_run":
        bench.gold, bench.cell, bench.name = netlist, cell, name
        bench.nodes = [meta["bindings"][port.upper()] for port in inventory["ports"]]
        bench.a = SimpleNamespace(analysis_timeout=180)
        bench.record = {"results": {}}
        bench.lock = threading.Lock()
        bench.save = lambda: (out / "bench_measurements.json").write_text(json.dumps(bench.record, indent=2, allow_nan=False) + "\n")
    for corner in contract["required_corners"]:
        if meta["bench_function"] == "measure":
            row = bench.measure(netlist, cell, "post_rc", corner, inventory["ports"])
            complete, healthy = row["complete"], row.get("electrical_meaning", row.get("operating_point_valid", False))
            prefix = "post_rc/" + corner + "/"
        else:
            bench.corner_run(corner)
            row = bench.record["results"][corner]
            complete, healthy = row["complete"], row.get("development_electrical_meaning", False)
            prefix = corner + "/"
        metrics = {"area": {"value": area, "unit": "um2"}}
        if complete:
            values = row["metrics"]
            for target, definition in meta["metric_bindings"].items():
                value = values[definition["source"]]
                metrics[target] = {"value": abs(value) if definition.get("absolute") else value, "unit": definition["unit"]}
        observation["corners"][corner] = {"converged": complete, "operating_point_valid": bool(healthy), "metrics": metrics}
        analyses = dict(row["analyses"])
        if "op" in contract["analysis_contracts"] and "op" not in analyses:
            analyses["op"] = analyses["ac"]
        artifacts["spice"][corner] = {"analyses": {key: {"data": prefix + key + ".dat",
            "log": prefix + ("ac" if key == "op" else key) + ".log", "returncode": item["returncode"]}
            for key, item in analyses.items()}}
        save()
result = save()
print(json.dumps(result), flush=True)
raise SystemExit(0 if result["assessment"]["S2"] and result["analysis_complete"] else 2)
