"""Measure development-only OTA bias/load feasibility with real model decks."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import time
import numpy as np
import sys
sys.path.insert(0,"/work")
from src.spice_validation import validate_analysis

p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--cs-bias-ua",type=float,required=True)
p.add_argument("--diffpair-bias-ua",type=float,default=10)
p.add_argument("--loads-pf",type=float,nargs="+",default=[1,2,4])
a=p.parse_args()
source=Path(os.environ["PROBE_INPUT"])/"ota7.spice"
out=Path.cwd()
decl=next(s.split() for s in source.read_text().splitlines() if s.lower().startswith(".subckt ota7 "))
bindings={"VDD":"vdd","GND":"0","DIFFPAIR_BIAS":"bias1","CS_BIAS":"bias2","VP":"vp","VN":"vn","VOUT":"out"}
nodes=[bindings[n.upper()] for n in decl[2:]]
record={"scope":"development_bias_load_feasibility_not_formal", "source_netlist":str(source),
    "cs_bias_uA":a.cs_bias_ua,"diffpair_bias_uA":a.diffpair_bias_ua,"loads_pF":a.loads_pf,"results":{}}

def measure(corner,load_pf):
    name=f"{corner}_load_{load_pf:g}p";work=out/name;work.mkdir()
    (work/".spiceinit").write_text("set ngbehavior=hsa\n")
    deck="\n".join(["OTA development bias-load feasibility",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
        ".option scale=1e-6 klu", ".option reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
        ".temp 27", ".include "+str(source),"VSUPPLY vdd 0 1.8", "IBIAS1 vdd bias1 "+str(a.diffpair_bias_ua)+"u",
        "IBIAS2 vdd bias2 "+str(a.cs_bias_ua)+"u", "CLOAD out 0 "+str(load_pf)+"p",
        "VIN vp 0 dc .9 ac 1", "LSERVO out vn 1G", "CAC vn 0 1G",
        "XDUT "+" ".join(nodes)+" ota7", ".save v(out) v(vp) v(vn) v(bias1) v(bias2) i(vsupply)",
        ".control","op","set wr_vecnames","set wr_singlescale",
        "wrdata operating_point.dat v(out) v(bias1) v(bias2) i(vsupply)",
        "ac dec 30 10 1G","wrdata ac.dat real(v(out)) imag(v(out))","quit",".endc",".end",""])
    (work/"ac.spice").write_text(deck)
    started=time.monotonic()
    with (work/"console.log").open("w") as log:
        try:
            sim=subprocess.run(["ngspice","-b","-o","ngspice.log","ac.spice"],cwd=work,
                stdout=log,stderr=subprocess.STDOUT,timeout=90)
            result={"returncode":sim.returncode}
        except subprocess.TimeoutExpired:
            return name,{"returncode":None,"timeout":True,"wall_seconds":time.monotonic()-started}
    result.update(corner=corner,load_pF=load_pf,wall_seconds=time.monotonic()-started,finite=False)
    result["analysis_evidence"]={
        "op":validate_analysis(work/"operating_point.dat",work/"ngspice.log",{"kind":"op","columns":5},sim.returncode),
        "ac":validate_analysis(work/"ac.dat",work/"ngspice.log",{"kind":"ac","columns":3,"start":10,"end":1e9,"points":241,"scale":"log"},sim.returncode)}
    result["analyses_complete"]=all(v["complete"] for v in result["analysis_evidence"].values())
    if not (work/"ac.dat").exists() or not (work/"operating_point.dat").exists():return name,result
    data=np.loadtxt(work/"ac.dat",skiprows=1,ndmin=2);op=np.loadtxt(work/"operating_point.dat",skiprows=1,ndmin=2)
    response=data[:,1]+1j*data[:,2];db=20*np.log10(np.abs(response));phase=np.unwrap(np.angle(response))*180/np.pi
    result.update(finite=bool(np.all(np.isfinite(data)) and np.all(np.isfinite(op))),output_bias_V=float(op[-1,1]),
        diffpair_bias_V=float(op[-1,2]),cs_bias_V=float(op[-1,3]),power_W=float(-1.8*op[-1,4]),gain_at_10Hz_dB=float(db[0]))
    crossings=np.flatnonzero((db[:-1]>=0)&(db[1:]<0))
    if len(crossings):
        i=int(crossings[0]);t=-db[i]/(db[i+1]-db[i])
        result.update(ugb_Hz=float(np.exp(np.log(data[i,0])+t*np.log(data[i+1,0]/data[i,0]))),
            phase_margin_deg=float(180+phase[i]+t*(phase[i+1]-phase[i])))
    return name,result

with ThreadPoolExecutor(max_workers=2) as pool:
    futures=[pool.submit(measure,corner,load) for corner in ["tt","ss","ff"] for load in a.loads_pf]
    for future in as_completed(futures):
        name,result=future.result();record["results"][name]=result
        (out/"measurements.json").write_text(json.dumps(record,indent=2)+"\n")
        print(json.dumps({"configuration":name,**result}),flush=True)
