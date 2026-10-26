"""Calibrate numerical convergence hints against the completed default RC solve."""
import json
import os
from pathlib import Path
import subprocess
import time
import numpy as np

source = Path(os.environ["PROBE_INPUT"])/"post_rc/tt"
out = Path.cwd()
reference = {n:np.loadtxt(source/n,skiprows=1,ndmin=2) for n in ["operating_point.dat","ac.dat"]}
record = {"scope":"development_convergence_calibration", "reference_directory":str(source),"variants":{}}
for name, option in [
    ("external_nodeset", ".nodeset v(out)=.9 v(vn)=.9 v(bias1)=.62 v(bias2)=.55"),
    ("original_gmin", ".option gminsteps=2")]:
    work = out/name;work.mkdir()
    (work/".spiceinit").write_text("set ngbehavior=hsa\n")
    deck = (source/"ac.spice").read_text().replace(".control", option+"\n.control",1)
    (work/"ac.spice").write_text(deck)
    started = time.monotonic()
    with (work/"console.log").open("w") as log:
        try:
            run = subprocess.run(["ngspice","-b","-o","ngspice.log","ac.spice"],cwd=work,
                stdout=log,stderr=subprocess.STDOUT,timeout=150)
            result = {"returncode":run.returncode}
        except subprocess.TimeoutExpired:
            result = {"returncode":None,"timeout":True}
    result.update(wall_seconds=time.monotonic()-started, option=option, comparisons={})
    for n, old in reference.items():
        path = work/n
        if not path.exists():
            result["comparisons"][n] = {"within_tolerance":False};continue
        new = np.loadtxt(path,skiprows=1,ndmin=2)
        same = old.shape==new.shape
        result["comparisons"][n] = {"same_shape":same,
            "max_absolute_difference":float(np.max(np.abs(old-new))) if same else None,
            "rtol":1e-4,"atol":1e-8,
            "within_tolerance":bool(same and np.all(np.isfinite(new)) and np.allclose(old,new,rtol=1e-4,atol=1e-8))}
    result["pass"] = result["returncode"]==0 and all(x["within_tolerance"] for x in result["comparisons"].values())
    record["variants"][name] = result
    (out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps({name:result}),flush=True)
