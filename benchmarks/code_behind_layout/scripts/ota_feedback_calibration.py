"""Compare exact-wire follower feedback with a redundant ideal 0V source."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np

sys.path.insert(0,"/work")
from src.spice_validation import validate_analysis

p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--comparison-runs",nargs="+",required=True)
p.add_argument("--method",choices=["trap","gear"],default="trap")
a=p.parse_args()
out=Path.cwd()
record={"scope":"development_exact_feedback_wire_numeric_calibration","method":a.method,
    "voltage_agreement_rtol":1e-5,"voltage_agreement_atol_V":5e-5,"results":{}}
for name in a.comparison_runs:
    source=Path(name)
    for deck in sorted(source.glob("*/tt/transient.spice")):
        fidelity=deck.parent.parent.name
        key=source.name+"_"+fidelity
        work=out/key;work.mkdir()
        lines=deck.read_text().splitlines()
        fixed=[]
        for line in lines:
            fields=line.split()
            if fields and fields[0].upper()=="VFEEDBACK":continue
            if fields and fields[0].upper()=="XDUT":
                line=" ".join("out" if value=="vn" else value for value in fields)
            if line.startswith(".save "):line=line.replace(" v(vn)","")
            fixed.append(line)
        if a.method=="gear":fixed.insert(1,".option method=gear maxord=2")
        (work/".spiceinit").write_text("set ngbehavior=hsa\n")
        (work/"transient.spice").write_text("\n".join(fixed)+"\n")
        t=time.monotonic()
        with (work/"console.log").open("w") as log:
            try:
                result=subprocess.run(["ngspice","-b","-o","ngspice.log","transient.spice"],
                    cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=240)
                rc=result.returncode
            except subprocess.TimeoutExpired:rc=None
        evidence=validate_analysis(work/"transient.dat",work/"ngspice.log",
            {"kind":"transient","columns":4,"start":0,"end":4e-6,
            "required_windows":[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]},rc)
        row={"complete":evidence["complete"],"evidence":evidence,"wall_seconds":time.monotonic()-t}
        original=validate_analysis(deck.parent/"transient.dat",deck.parent/"transient_ngspice.log",
            {"kind":"transient","columns":4,"start":0,"end":4e-6,
            "required_windows":[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]},0)
        row["original_complete"]=original["complete"]
        if evidence["complete"] and original["complete"]:
            before=np.loadtxt(deck.parent/"transient.dat",skiprows=1,ndmin=2)
            after=np.loadtxt(work/"transient.dat",skiprows=1,ndmin=2)
            # Both variable-step solutions are compared on the same 2ns grid.
            grid=np.linspace(0,4e-6,2001)
            b=np.interp(grid,before[:,0],before[:,2]);c=np.interp(grid,after[:,0],after[:,2])
            row.update(max_voltage_difference_V=float(np.max(np.abs(b-c))),
                agreement=bool(np.allclose(b,c,rtol=record["voltage_agreement_rtol"],atol=record["voltage_agreement_atol_V"])))
        record["results"][key]=row
        (out/"calibration.json").write_text(json.dumps(record,indent=2)+"\n")
        print(json.dumps({"case":key,**row}),flush=True)
record["passed"]=all(r["complete"] and r.get("agreement",True) for r in record["results"].values())
(out/"calibration.json").write_text(json.dumps(record,indent=2)+"\n")
raise SystemExit(0 if record["passed"] else 2)
