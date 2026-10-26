"""Compare KLU against a completed Sparse OP/AC solve on the same actual RC deck."""
import json
import os
from pathlib import Path
import subprocess
import numpy as np

source = Path(os.environ["PROBE_INPUT"])/"post_rc/tt"
out = Path.cwd()
(out/".spiceinit").write_text("set ngbehavior=hsa\n")
deck=(source/"ac.spice").read_text().replace(".control", ".options klu\n.control",1)
(out/"ac.spice").write_text(deck)
with (out/"console_ngspice.log").open("w") as log:
    sim=subprocess.run(["ngspice","-b","-o","ngspice.log","ac.spice"],
        stdout=log,stderr=subprocess.STDOUT,timeout=120)
record={"scope":"development_solver_calibration", "reference_directory":str(source),
    "returncode":sim.returncode,"actual_klu": "Using KLU" in (out/"ngspice.log").read_text(),"comparisons":{}}
for name,rtol,atol in [("operating_point.dat",1e-5,1e-8),("ac.dat",1e-4,1e-6)]:
    old=np.loadtxt(source/name,skiprows=1,ndmin=2)
    new=np.loadtxt(out/name,skiprows=1,ndmin=2)
    same_shape=old.shape==new.shape
    record["comparisons"][name]={"same_shape":same_shape,"rtol":rtol,"atol":atol,
        "max_absolute_difference":float(np.max(np.abs(old-new))) if same_shape else None,
        "within_tolerance":bool(same_shape and np.all(np.isfinite(new)) and np.allclose(old,new,rtol=rtol,atol=atol))}
record["pass"]=(sim.returncode==0 and record["actual_klu"] and all(v["within_tolerance"] for v in record["comparisons"].values()))
(out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
print(json.dumps(record,indent=2))
raise SystemExit(0 if record["pass"] else 2)
