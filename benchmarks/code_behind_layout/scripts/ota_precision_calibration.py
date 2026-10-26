"""Compare prelayout AC solver agreement at fixed normal and tighter tolerances."""
import json
import os
from pathlib import Path
import subprocess
import time
import numpy as np

source = Path(os.environ["PROBE_INPUT"])/"prelayout/tt/ac.spice"
out = Path.cwd()
record = {"scope":"development_numeric_precision_calibration", "reference_deck":str(source),"variants":{}}
arrays = {}
for name, solver, precision in [
    ("default_klu","klu",""),
    ("tight_klu","klu",".option reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16"),
    ("tight_sparse","sparse",".option reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16")]:
    work = out/name;work.mkdir()
    (work/".spiceinit").write_text("set ngbehavior=hsa\n")
    deck = source.read_text().replace("scale=1e-6 klu", "scale=1e-6 "+solver)
    deck = deck.replace(".control",precision+"\n.control",1)
    (work/"ac.spice").write_text(deck)
    started = time.monotonic()
    with (work/"console.log").open("w") as log:
        sim = subprocess.run(["ngspice","-b","-o","ngspice.log","ac.spice"],cwd=work,
            stdout=log,stderr=subprocess.STDOUT,timeout=120)
    data = np.loadtxt(work/"ac.dat",skiprows=1,ndmin=2)
    op = np.loadtxt(work/"operating_point.dat",skiprows=1,ndmin=2)
    arrays[name] = {"ac":data,"op":op}
    response=data[:,1]+1j*data[:,2];db=20*np.log10(np.abs(response))
    phase=np.unwrap(np.angle(response))*180/np.pi;cross=np.flatnonzero((db[:-1]>=0)&(db[1:]<0))
    result={"returncode":sim.returncode,"wall_seconds":time.monotonic()-started,
        "precision":precision,"solver":solver,"finite":bool(np.all(np.isfinite(data)) and np.all(np.isfinite(op))),
        "output_bias_V":float(op[-1,1]),"gain_at_10Hz_dB":float(db[0])}
    if len(cross):
        i=int(cross[0]);t=-db[i]/(db[i+1]-db[i])
        result.update(ugb_Hz=float(np.exp(np.log(data[i,0])+t*np.log(data[i+1,0]/data[i,0]))),
            phase_margin_deg=float(180+phase[i]+t*(phase[i+1]-phase[i])))
    record["variants"][name]=result
    (out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps({name:result}),flush=True)
record["tight_solver_agreement"]={k:{"rtol":1e-5,"atol":1e-8,
    "max_absolute_difference":float(np.max(np.abs(arrays["tight_klu"][k]-arrays["tight_sparse"][k]))),
    "within_tolerance":bool(np.allclose(arrays["tight_klu"][k],arrays["tight_sparse"][k],rtol=1e-5,atol=1e-8))}
    for k in ["ac","op"]}
record["pass"] = all(v["within_tolerance"] for v in record["tight_solver_agreement"].values())
(out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
print(json.dumps(record["tight_solver_agreement"]),flush=True)
raise SystemExit(0 if record["pass"] else 2)
