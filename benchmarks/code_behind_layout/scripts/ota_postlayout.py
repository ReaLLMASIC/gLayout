"""Development seven-port OTA prelayout/post-RC OP, AC, follower transient and DC.

No performance threshold is inferred from these results. The DC servo uses a
large inductor in feedback and a capacitor at VN to open the AC feedback path.
Every netlist, testbench, waveform and simulator log is retained.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import numpy as np

sys.path.insert(0,"/work")
from src.physical_drc import check_gds
from src.report_parsers import rc_netlist_inventory, duplicate_subcircuits
from src.spice_validation import validate_analysis

source = Path(os.environ["PROBE_INPUT"])
out = Path.cwd()
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--fidelity",choices=["prelayout","post_rc","both"],default="both")
parser.add_argument("--solver",choices=["klu","sparse"],default="klu")
parser.add_argument("--corners",choices=["tt","ss","ff"],nargs="+",default=["tt","ss","ff"])
parser.add_argument("--load-pf",type=float,default=1)
args=parser.parse_args()
if args.load_pf<=0:parser.error("load must be positive")
reference = source / "ota7.spice"
pex = out / "ota7_pex.spice"
validation = json.loads((source / "validation.json").read_text())
if not validation["LVS_match"]:
    raise SystemExit("Independent seven-terminal LVS must pass before performance measurements")
drc = check_gds(source/"ota7.gds", out/"drc_full")
if not drc["is_clean"]:
    raise SystemExit("Completed full-rule DRC must pass before performance measurements")
record = {"scope":"development_feasibility_no_frozen_S2_claim", "input_directory":str(source),
    "supply_V":1.8,"common_mode_V":.9,"bias_currents_A":[1e-5,1e-5],
    "load_F":args.load_pf*1e-12,"temperature_C":27,"solver":args.solver,"DRC":drc,
    "numeric_options":{"reltol":1e-6,"abstol_A":1e-14,"vntol_V":1e-8,"chgtol_C":1e-16},
    "required_corners":args.corners,
    "follower_feedback":"direct_node_alias_calibrated_against_ideal_zero_V_source",
    "transient_window_s":4e-6,"follower_dc_input_range_V":[.6,1.2],
    "follower_dc_step_V":.1,"results":{}}
if args.fidelity in ["post_rc","both"]:
    with (out/"pex.log").open("w") as log:
        extraction=subprocess.run(["bash","/work/vendor/glayout/src/glayout/verification/run_pex.sh",
            str(source/"ota7.gds"),"ota7"],stdout=log,stderr=subprocess.STDOUT,timeout=240)
    record["pex_returncode"]=extraction.returncode
    if extraction.returncode!=0:
        raise SystemExit("Standalone RC extraction failed")
for fidelity, netlist in [("prelayout",reference),("post_rc",pex)]:
    if args.fidelity not in [fidelity,"both"]:
        continue
    text = netlist.read_text()
    if duplicate_subcircuits(text):
        raise SystemExit("Ambiguous duplicate subcircuit declarations are not a valid reference or extracted circuit")
    if fidelity == "post_rc":
        record["element_counts"] = {k:len(re.findall(r"^"+k+r"\S*\s",text,re.I|re.M)) for k in ["R","C","X","M"]}
        if any(record["element_counts"][k] == 0 for k in ["R","C"]):
            raise SystemExit("Full resistance and capacitance extraction required")
        record["RC"] = rc_netlist_inventory(text,"ota7_rc",["VDD","GND","DIFFPAIR_BIAS","CS_BIAS","VP","VN","VOUT"])
        if not record["RC"]["has_real_RC"]:
            raise SystemExit("Positive literal R/C and complete reference-bound ports required")
    declarations = [line.split() for line in text.splitlines() if line.lower().startswith(".subckt ")]
    decl = next(d for d in declarations if d[1].lower()==("ota7_rc" if fidelity=="post_rc" else "ota7"))
    bindings = {"VDD":"vdd","GND":"0","DIFFPAIR_BIAS":"bias1","CS_BIAS":"bias2",
                "VP":"vp","VN":"vn","VOUT":"out"}
    nodes = [bindings[n.upper()] for n in decl[2:]]
    record["results"][fidelity] = {}
    for corner in args.corners:
        work = out/fidelity/corner;work.mkdir(parents=True)
        (work/".spiceinit").write_text("set ngbehavior=hsa\n")
        common = ["Seven-terminal OTA development measurements",
            ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
            ".option scale=1e-6"+(" klu" if args.solver=="klu" else " sparse"), ".temp 27", ".include "+str(netlist),
            ".option reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
            "VSUPPLY vdd 0 1.8", "IBIAS1 vdd bias1 10u", "IBIAS2 vdd bias2 10u",
            "CLOAD out 0 "+str(args.load_pf)+"p", "XDUT "+" ".join(nodes)+" "+decl[1],
            ".save v(out) v(vp) v(vn) v(bias1) v(bias2) i(vsupply)"]
        analyses = {
            "ac": ["VIN vp 0 dc .9 ac 1", "LSERVO out vn 1G", "CAC vn 0 1G",
                ".control","op","set wr_vecnames","set wr_singlescale",
                "wrdata operating_point.dat v(out) v(vp) v(vn) v(bias1) v(bias2) i(vsupply)",
                "ac dec 30 10 1G", "wrdata ac.dat real(v(out)) imag(v(out))","quit",".endc",".end", ""],
            "transient": ["VIN vp 0 pulse(.89 .91 1u 10n 10n 1u 2u)",
                ".control","set wr_vecnames","set wr_singlescale","tran 5n 4u",
                "wrdata transient.dat v(vp) v(out) i(vsupply)","quit",".endc",".end", ""],
            "dc": ["VIN vp 0 .9", ".control","set wr_vecnames","set wr_singlescale",
                "dc VIN .6 1.2 .1","wrdata dc.dat v(vp) v(out) i(vsupply)","quit",".endc",".end", ""]}
        result = {"analyses":{},"metrics":{}}
        for name, tail in analyses.items():
            analysis_common=list(common)
            if name!="ac":
                follower_nodes=["out" if node=="vn" else node for node in nodes]
                analysis_common=[("XDUT "+" ".join(follower_nodes)+" "+decl[1]) if line.startswith("XDUT ")
                    else line.replace(" v(vn)","") if line.startswith(".save ") else line for line in common]
            (work/(name+".spice")).write_text("\n".join(analysis_common+tail))
            with (work/(name+"_console.log")).open("w") as log:
                try:
                    sim = subprocess.run(["ngspice","-b","-o",name+"_ngspice.log",name+".spice"],
                        cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=240)
                    result["analyses"][name] = {"returncode":sim.returncode}
                except subprocess.TimeoutExpired:
                    result["analyses"][name] = {"returncode":None,"timeout":True}
        contracts={
            "operating_point":{"kind":"op","columns":7},
            "ac":{"kind":"ac","columns":3,"start":10,"end":1e9,"points":241,"scale":"log"},
            "transient":{"kind":"transient","columns":4,"start":0,"end":4e-6,
                "required_windows":[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]},
            "dc":{"kind":"dc","columns":4,"start":.6,"end":1.2,"points":7}}
        result["analysis_evidence"]={name:validate_analysis(work/(name+".dat"),
            work/(("ac" if name=="operating_point" else name)+"_ngspice.log"),contract,
            result["analyses"]["ac" if name=="operating_point" else name]["returncode"])
            for name,contract in contracts.items()}
        result["all_analyses_complete"]=all(v["complete"] for v in result["analysis_evidence"].values())
        def read_data(name, columns):
            path = work/name
            if not path.exists():return None
            try:
                data = np.loadtxt(path,skiprows=1,ndmin=2)
                return data if data.shape[1]==columns and np.all(np.isfinite(data)) else None
            except ValueError:return None
        op = read_data("operating_point.dat",7)
        if op is not None:
            row=op[-1]
            result["metrics"].update(output_bias_V=float(row[1]),vp_V=float(row[2]),vn_V=float(row[3]),
                diffpair_bias_V=float(row[4]),cs_bias_V=float(row[5]),power_W=float(-1.8*row[6]))
        ac = read_data("ac.dat",3)
        if ac is not None:
            freq=ac[:,0]; response=ac[:,1]+1j*ac[:,2]
            gain_db=20*np.log10(np.maximum(np.abs(response),1e-300))
            phase=np.unwrap(np.angle(response))*180/np.pi
            crossings=np.flatnonzero((gain_db[:-1]>=0)&(gain_db[1:]<0))
            result["metrics"].update(gain_at_10Hz_dB=float(gain_db[0]),
                gain_at_10Hz_real=float(response[0].real),descending_unity_crossings=len(crossings))
            if len(crossings):
                i=int(crossings[0]);t=-gain_db[i]/(gain_db[i+1]-gain_db[i])
                result["metrics"].update(ugb_Hz=float(np.exp(np.log(freq[i])+t*np.log(freq[i+1]/freq[i]))),
                    phase_margin_deg=float(180+phase[i]+t*(phase[i+1]-phase[i])))
        tran=read_data("transient.dat",4)
        if tran is not None:
            t,vin,vout=tran[:,0],tran[:,1],tran[:,2]
            high=(t>1.8e-6)&(t<1.99e-6);low=(t>2.8e-6)&(t<2.99e-6)
            result["metrics"].update(transient_output_min_V=float(vout.min()),transient_output_max_V=float(vout.max()),
                positive_step_final_error_V=float(np.mean(vout[high]-vin[high])) if high.any() else None,
                negative_step_final_error_V=float(np.mean(vout[low]-vin[low])) if low.any() else None)
        dc=read_data("dc.dat",4)
        if dc is not None:
            valid=np.abs(dc[:,2]-dc[:,1])<=.01
            groups=np.split(np.flatnonzero(valid),np.flatnonzero(np.diff(np.flatnonzero(valid))>1)+1)
            groups=[g for g in groups if len(g)]
            if groups:
                best=max(groups,key=len)
                result["metrics"].update(follower_input_min_10mV_V=float(dc[best[0],1]),
                    follower_input_max_10mV_V=float(dc[best[-1],1]),
                    follower_tracking_span_10mV_V=float(dc[best[-1],1]-dc[best[0],1]))
        result["all_waveforms_finite"] = all(x is not None for x in [op,ac,tran,dc])
        result["all_simulators_exited_zero"] = all(v["returncode"]==0 for v in result["analyses"].values())
        record["results"][fidelity][corner] = result
        (out/"measurements.json").write_text(json.dumps(record,indent=2)+"\n")
        print(json.dumps({"fidelity":fidelity,"corner":corner,**result}),flush=True)
record["flow_complete"] = all(r["all_waveforms_finite"] and r["all_simulators_exited_zero"] and r["all_analyses_complete"]
    for corners in record["results"].values() for r in corners.values())
(out/"measurements.json").write_text(json.dumps(record,indent=2)+"\n")
raise SystemExit(0 if record["flow_complete"] else 2)
