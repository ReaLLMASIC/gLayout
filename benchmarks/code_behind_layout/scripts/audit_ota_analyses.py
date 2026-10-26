#!/usr/bin/env python3
"""Recheck completed OTA raw analyses without rerunning or rewriting their results."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.spice_validation import validate_analysis

p=argparse.ArgumentParser(description=__doc__)
p.add_argument("runs",type=Path,nargs="+")
p.add_argument("--output",type=Path,required=True)
a=p.parse_args()
contracts={
    "operating_point":{"kind":"op","columns":7},
    "ac":{"kind":"ac","columns":3,"start":10,"end":1e9,"points":241,"scale":"log"},
    "transient":{"kind":"transient","columns":4,"start":0,"end":4e-6,
        "required_windows":[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]},
    "dc":{"kind":"dc","columns":4,"start":.6,"end":1.2,"points":7}}
record={"scope":"development_completed_raw_analysis_audit","runs":{},"all_complete":True}
for run in a.runs:
    manifest=json.loads((run/"pilot_manifest.json").read_text())
    measurements=json.loads((run/"measurements.json").read_text())
    results={}
    for fidelity,corners in measurements["results"].items():
        results[fidelity]={}
        for corner,old in corners.items():
            work=run/fidelity/corner
            results[fidelity][corner]={name:validate_analysis(work/(name+".dat"),
                work/(("ac" if name=="operating_point" else name)+"_ngspice.log"),contract,
                old["analyses"]["ac" if name=="operating_point" else name]["returncode"])
                for name,contract in contracts.items()}
    complete=manifest["status"]=="TOOL_COMPLETED" and bool(results) and all(
        r["complete"] for corners in results.values() for analyses in corners.values() for r in analyses.values())
    record["runs"][run.name]={"input_directory":measurements["input_directory"],
        "required_corners":measurements.get("required_corners",["tt","ss","ff"]),
        "numeric_options":measurements.get("numeric_options"),"all_complete":complete,"results":results}
    record["all_complete"] &= complete
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(record,indent=2)+"\n")
print(json.dumps({"output":str(a.output),"all_complete":record["all_complete"],
    "runs":{name:row["all_complete"] for name,row in record["runs"].items()}}))
raise SystemExit(0 if record["all_complete"] else 2)
