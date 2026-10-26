"""Prelayout development sweep of physical MIM dimensions; no formal data."""
import json
import os
from pathlib import Path
import re
import subprocess
import numpy as np

source = Path(os.environ["PROBE_INPUT"])/"ota7.spice"
out = Path.cwd()
reference = source.read_text()
decl = next(s.split() for s in reference.splitlines() if s.lower().startswith(".subckt ota7 "))
bindings = {"VDD":"vdd","GND":"0","DIFFPAIR_BIAS":"bias1","CS_BIAS":"bias2","VP":"vp","VN":"vn","VOUT":"out"}
nodes = [bindings[n.upper()] for n in decl[2:]]
record = {"scope":"development_sized_schematic_feasibility", "reference_directory":str(source.parent),
    "supply_V":1.8,"load_F":1e-12,"bias_A":[1e-5,1e-5],"results":{}}
for size in [20,24,30]:
    netlist = re.sub(r"(sky130_fd_pr__cap_mim_m3_1\s+)l=12(?:\.0)?\s+w=12(?:\.0)?",r"\g<1>l="+str(size)+" w="+str(size),reference)
    if netlist==reference:
        raise SystemExit("Expected physical MIM device line not found")
    work = out/f"size_{size}";work.mkdir()
    (work/"ota7.spice").write_text(netlist)
    (work/".spiceinit").write_text("set ngbehavior=hsa\n")
    record["results"][str(size)] = {}
    for corner in ["tt","ss","ff"]:
        deck = "\n".join(["Development compensation sizing sweep",
            ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
            ".option scale=1e-6 klu", ".temp 27", ".include "+str(work/"ota7.spice"),
            "VSUPPLY vdd 0 1.8", "IBIAS1 vdd bias1 10u", "IBIAS2 vdd bias2 10u",
            "CLOAD out 0 1p", "VIN vp 0 dc .9 ac 1", "LSERVO out vn 1G", "CAC vn 0 1G",
            "XDUT "+" ".join(nodes)+" ota7", ".control", "ac dec 30 10 1G",
            "set wr_vecnames", "set wr_singlescale", "wrdata "+corner+"_ac.dat real(v(out)) imag(v(out))",
            "quit", ".endc", ".end", ""])
        (work/(corner+".spice")).write_text(deck)
        with (work/(corner+"_console.log")).open("w") as log:
            sim = subprocess.run(["ngspice","-b","-o",corner+"_ngspice.log",corner+".spice"],cwd=work,
                stdout=log,stderr=subprocess.STDOUT,timeout=60)
        data = np.loadtxt(work/(corner+"_ac.dat"),skiprows=1,ndmin=2)
        f=data[:,0];response=data[:,1]+1j*data[:,2]
        db=20*np.log10(np.abs(response));phase=np.unwrap(np.angle(response))*180/np.pi
        cross=np.flatnonzero((db[:-1]>=0)&(db[1:]<0))
        result={"returncode":sim.returncode,"finite":bool(np.all(np.isfinite(data))),"gain_at_10Hz_dB":float(db[0])}
        if len(cross):
            i=int(cross[0]);t=-db[i]/(db[i+1]-db[i])
            result.update(ugb_Hz=float(np.exp(np.log(f[i])+t*np.log(f[i+1]/f[i]))),
                phase_margin_deg=float(180+phase[i]+t*(phase[i+1]-phase[i])))
        record["results"][str(size)][corner]=result
        print(json.dumps({"size_um":size,"corner":corner,**result}),flush=True)
    (out/"measurements.json").write_text(json.dumps(record,indent=2)+"\n")
