"""E2 electrical stage on one byte-identical, already admitted physical RC.

The source-to-GDS and full DRC/LVS/intent/PEX acquisitions are retained and
charged at their original run. This stage runs the complete frozen electrical
benchmark. It does not regenerate or simplify RC or import candidate Python.
"""
import argparse
import json
from pathlib import Path
import shutil

from src.device_intent import compare_device_intent
from src.measurement import assess
from src.report_parsers import rc_netlist_inventory, magic_drc_report, netgen_lvs_report
from src.spice_validation import validate_analysis
import ota_frozen_bench
from e2_spice_process_profile import profiled_measure

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--gds", required=True)
p.add_argument("--output", required=True)
p.add_argument("--fidelity", choices=["pex_spice"], required=True)
a = p.parse_args()
out, trusted = Path(a.output), Path("/trusted")
meta = json.loads((trusted / "meta.json").read_text())
contract = json.loads((trusted / "contract.json").read_text())
configuration = json.loads(Path("/configuration.json").read_text())
if configuration["parameters"] != contract["immutable_parameters"]:
    raise ValueError("The electrical stage has a different intended sizing")
if Path(a.gds).read_bytes() != (trusted / "cached/candidate.gds").read_bytes():
    raise ValueError("The accepted GDS differs from the exact physical acquisition")
prior = json.loads((trusted / "cached/validation.json").read_text())
if not prior["assessment"]["S1"] or not prior["requested_fidelity_complete"]:
    raise ValueError("The original independent physical gates did not complete")
drc = prior["artifacts"]["drc"]
metadata = json.loads((trusted / "cached" / drc["metadata"]).read_text())
if (metadata.get("completed") is not True or metadata.get("style") != "drc(full)"
        or not magic_drc_report((trusted / "cached" / drc["report"]).read_text())["is_clean"]
        or not netgen_lvs_report((trusted / "cached" / prior["artifacts"]["lvs"]["report"]).read_text())["is_clean"]):
    raise ValueError("The original completed independent DRC/LVS reports are not clean")
intent = compare_device_intent((trusted / "cached/extracted_lvs.spice").read_text(),
    (trusted / "reference.spice").read_text())
if not intent["is_clean"]:
    raise ValueError("The cached independent physical/reference binding changed")
cell = meta["top_cell"]+"_rc"
pex = out / (meta["top_cell"]+"_pex.spice")
shutil.copyfile(trusted / "cached/physical_rc.spice", pex)
inventory = rc_netlist_inventory(pex.read_text(), cell, meta["ports"])
if not inventory["has_real_RC"]:
    raise ValueError("The cached positive unsimplified physical RC is invalid")
for name in ["extracted_lvs.spice", "reference.spice"]:
    source = trusted / ("cached/"+name if name == "extracted_lvs.spice" else name)
    shutil.copyfile(source, out / name)
for relative in [drc["report"], drc["metadata"], prior["artifacts"]["lvs"]["report"]]:
    destination = out / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(trusted / "cached" / relative, destination)
(out / "device_intent.json").write_text(json.dumps(intent, indent=2)+"\n")
(out / "rc_inventory.json").write_text(json.dumps(inventory, indent=2)+"\n")
observation = {key: contract[key] for key in ["task_id", "configuration_id", "reference_id"]}
observation.update(executed=True, gds_emitted=True, checks=prior["observation"]["checks"],
    pex=prior["observation"]["pex"], corners={})
artifacts = {"spice": {}, "drc": drc, "lvs": {"report": prior["artifacts"]["lvs"]["report"], "netlist": "extracted_lvs.spice", "reference": "reference.spice",
    "device_intent": "device_intent.json"}, "pex": {"netlist": pex.name, "top_cell": cell,
    "ports": inventory["ports"]}, "physical_acquisition": meta["physical_acquisition"]}
measure = ota_frozen_bench.run_vendor_post_rc if meta["bench_kind"] == "vendor_ota" else ota_frozen_bench.run_post_rc
returned = profiled_measure(measure, out, pex, cell, inventory["ports"], configuration["parameters"], contract,
    kind=meta["circuit"], bench_snapshot=trusted / "original_bench.py", reference_path=trusted / "reference.spice")
analysis_complete = True
for corner in contract["required_corners"]:
    row = returned["corners"].get(corner)
    if row is None:
        analysis_complete = False
        continue
    observation["corners"][corner] = {key: row[key] for key in ["converged", "operating_point_valid", "metrics"]}
    observation["corners"][corner]["metrics"]["original_development_predicate"] = {
        "value": int(row["original_development_constraints_passed"]), "unit": "1"}
    artifacts["spice"][corner] = {"analyses": {}}
    validations = {}
    for name, definition in contract["analysis_contracts"].items():
        artifact = row["analyses"][name]
        validations[name] = validate_analysis(artifact["data"], artifact["log"], definition, artifact.get("returncode"))
        artifacts["spice"][corner]["analyses"][name] = {**artifact,
            "data": str(Path(artifact["data"]).relative_to(out)), "log": str(Path(artifact["log"]).relative_to(out))}
    (out / (corner+"_analysis_validation.json")).write_text(json.dumps(validations, indent=2)+"\n")
    analysis_complete &= all(item["complete"] for item in validations.values())
complete = bool(analysis_complete and set(observation["corners"]) == set(contract["required_corners"]))
assessment = assess(contract, observation)
record = {"scope": "E2_full_electrical_on_exact_retained_actual_PEX", "contract": contract,
    "observation": observation, "artifacts": artifacts, "assessment": assessment,
    "point_evaluation_complete": complete, "analysis_complete": complete,
    "execution_integrity": "valid" if complete else "incomplete",
    "failure_class": None if complete and assessment["S2"] else "candidate" if complete else "unknown",
    "requested_fidelity": "pex_spice", "requested_fidelity_complete": complete,
    "physical_tool_calls": {"DRC": 0, "LVS": 0, "PEX": 0,
        "SPICE": sum(len(row.get("raw", {}).get("analyses", {})) for row in returned["corners"].values())},
    "physical_cost_reused_from": meta["physical_acquisition"], "physical_reuse_requires_exact_GDS_bytes": True}
record["per_analysis_actual_cost_files"] = sorted(str(p.relative_to(out)) for p in out.rglob("*_process_resource.json"))
record["per_analysis_CPU_is_component_of_trusted_total_not_additional"] = True
(out / "validation.json").write_text(json.dumps(record, indent=2, allow_nan=False)+"\n")
print(json.dumps(record), flush=True)
raise SystemExit(0 if complete and assessment["S2"] else 2)
