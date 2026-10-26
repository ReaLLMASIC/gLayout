"""Compare documented RC simplification with the same full-mesh physical model."""
import json
import os
from pathlib import Path
import subprocess
import time
import sys
import numpy as np

sys.path.insert(0,"/work")
from src.report_parsers import rc_netlist_inventory

source = Path(os.environ["PROBE_INPUT"])
out = Path.cwd()
old = json.loads((source/"measurements.json").read_text())
gds = Path(old["input_directory"])/"ota7.gds"
ports=["VDD","GND","DIFFPAIR_BIAS","CS_BIAS","VP","VN","VOUT"]
script = Path("/work/vendor/glayout/src/glayout/verification/run_pex.sh").read_text()
if script.count("extresist simplify off")!=1:
    raise SystemExit("Expected full-mesh extraction script not found")
record={"scope":"development_RC_simplification_calibration","input_gds":str(gds),"variants":{},
    "tolerances":{"AC_rtol":1e-3,"AC_atol":1e-5,"OP_rtol":1e-5,"OP_atol":1e-8,"transient_max_abs_V":5e-5}}
arrays={}
for name in ["full_mesh","simplified"]:
    work=out/name;work.mkdir()
    net = source/"ota7_pex.spice" if name=="full_mesh" else work/"ota7_pex.spice"
    if name=="simplified":
        extraction_script=work/"run_pex.sh"
        extraction_script.write_text(script.replace("extresist simplify off","extresist simplify on"))
        with (work/"pex.log").open("w") as log:
            run=subprocess.run(["bash",str(extraction_script),str(gds),"ota7"],cwd=work,
                stdout=log,stderr=subprocess.STDOUT,timeout=180)
        if run.returncode: raise SystemExit("Simplified extraction failed")
    rc=rc_netlist_inventory(net.read_text(),"ota7_rc",ports)
    record["variants"][name]={"RC":rc,"analyses":{}}
    if not rc["has_real_RC"]:
        (out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
        raise SystemExit("Calibration requires positive full R/C models")
    (work/".spiceinit").write_text("set ngbehavior=hsa\n")
    arrays[name]={}
    for analysis in ["ac","transient"]:
        original=source/"post_rc/tt"/(analysis+".spice")
        deck=original.read_text().replace(".include "+str(source/"ota7_pex.spice"),".include "+str(net))
        deck=deck.replace(".control",".option reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16\n.control",1)
        (work/(analysis+".spice")).write_text(deck)
        started=time.monotonic()
        with (work/(analysis+"_console.log")).open("w") as log:
            run=subprocess.run(["ngspice","-b","-o",analysis+"_ngspice.log",analysis+".spice"],cwd=work,
                stdout=log,stderr=subprocess.STDOUT,timeout=240)
        record["variants"][name]["analyses"][analysis]={"returncode":run.returncode,"wall_seconds":time.monotonic()-started}
        for data_name in (["ac.dat","operating_point.dat"] if analysis=="ac" else ["transient.dat"]):
            arrays[name][data_name]=np.loadtxt(work/data_name,skiprows=1,ndmin=2)
        (out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
        print(json.dumps({"variant":name,"analysis":analysis,**record["variants"][name]["analyses"][analysis]}),flush=True)
comparisons={}
for data_name,rtol,atol in [("ac.dat",1e-3,1e-5),("operating_point.dat",1e-5,1e-8)]:
    a,b=(arrays[n][data_name] for n in ["full_mesh","simplified"])
    same=a.shape==b.shape
    comparisons[data_name]={"same_shape":same,"rtol":rtol,"atol":atol,
        "max_abs_difference":float(np.max(np.abs(a-b))) if same else None,
        "pass":bool(same and np.all(np.isfinite(b)) and np.allclose(a,b,rtol=rtol,atol=atol))}
a,b=(arrays[n]["transient.dat"] for n in ["full_mesh","simplified"])
grid=np.linspace(max(a[0,0],b[0,0]),min(a[-1,0],b[-1,0]),2001)
err=np.interp(grid,a[:,0],a[:,2])-np.interp(grid,b[:,0],b[:,2])
comparisons["transient.dat"]={"interpolation_grid_points":len(grid),"max_abs_difference_V":float(np.max(np.abs(err))),
    "atol_V":5e-5,"pass":bool(np.all(np.isfinite(err)) and np.max(np.abs(err))<=5e-5)}
record["comparisons"]=comparisons
record["pass"]=all(d["pass"] for d in comparisons.values())
(out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
print(json.dumps(comparisons,indent=2))
raise SystemExit(0 if record["pass"] else 2)
