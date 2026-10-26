"""Real development qualification for two independent non-OTA assemblies.

Run prelayout first. A post-RC run consumes that complete electrical control and
its independently fixed gold. These are development records, never formal data.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

sys.path.insert(0, "/work")
from src.spice_validation import validate_analysis

p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--circuit",required=True,choices=["cascode_mirror","source_follower"])
p.add_argument("--fidelity",choices=["prelayout","post_rc"],default="prelayout")
p.add_argument("--config-json")
p.add_argument("--analysis-timeout",type=int,default=180)
a=p.parse_args();out=Path.cwd();root=Path("/work");name=a.circuit
ref=importlib.import_module("src.generators."+name+"_reference")
config={**ref.DEFAULT,**(json.loads(Path(a.config_json).read_text())if a.config_json else{})}
gold=out/(name+".spice");gold.write_text(ref.schematic(config))
for suffix in [".py","_reference.py"]:
    shutil.copy2(root/"src/generators"/(name+suffix),out/(name+suffix))
record={"scope":"development_independent_nonOTA_source_qualification_not_formal_or_train",
    "circuit":name,"fidelity":a.fidelity,"configuration":config,"supply_V":1.8,
    "bias_current_A":1e-5,"temperature_C":27,"corners":["tt","ss","ff"],
    "physical_library_dependencies":["glayout.primitives.fet.nmos","glayout.primitives.via_gen.via_stack","SKY130 PDK"],
    "imported_circuit_assemblies":[],"results":{},
    "interpretation":("Separate cascode reference/output branches and diode bias stack; output current is -i(VCLAMP)."
        if name=="cascode_mirror"else"Common-drain buffer has intrinsic level shift; AC gain and output impedance do not assume unity DC tracking."),
    "bench":{"load_F":1e-12 if name=="source_follower"else 0,
        "nominal_input_or_output_V":1.2,"reference_current_A":1e-5,
        "transient_input_range":([8e-6,10e-6]if name=="cascode_mirror"else[1.19,1.21]),
        "transient_input_unit":"A"if name=="cascode_mirror"else"V",
        "numerics":{"reltol":1e-6,"abstol":1e-14,"vntol":1e-8,"chgtol":1e-16}}}
record["metric_definitions"]={
    "bandwidth_3dB_first_sample_Hz":"First AC sample below the magnitude at10Hz divided by sqrt(2),30points/decade; a coarse sampled crossing, not an interpolated bandwidth.",
    "output_resistance_ohm":"Absolute reciprocal central difference of DC Iout at1.1/1.3V around nominal1.2V; finite0.2V span, not an analytic infinitesimal derivative.",
    "current_feed_power_W":"-1.8*i(VSUPPLY), including ideal reference/bias current feeds and excluding the independent output voltage clamp.",
    "power_W":"-1.8*i(VSUPPLY), including the common-drain device and its ideal bias-current feed.",
    "output_impedance_10Hz_ohm":"Magnitude of Vout/1A for an AC current test source at10Hz, with input AC grounded and1pF load retained."}
lock=threading.Lock()
def save():
    (out/"measurements.json").write_text(json.dumps(record,indent=2,allow_nan=False)+"\n")
save()
cell=name
if a.fidelity=="post_rc":
    source=Path(os.environ["PROBE_INPUT"])
    baseline=json.loads((source/"measurements.json").read_text())
    if not(baseline["circuit"]==name and baseline["fidelity"]=="prelayout" and
           baseline.get("electrical_meaning_established") and baseline["configuration"]==config):
        raise SystemExit("Complete meaningful prelayout control for the same configuration required")
    if gold.read_text()!=(source/(name+".spice")).read_text():
        raise SystemExit("Independent circuit intent changed after prelayout control")
    from glayout import sky130
    from src.physical_drc import check_gds
    from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
    generator=importlib.import_module("src.generators."+name)
    start=time.monotonic();gds=generator.build(out,config)
    record["generation_wall_seconds"]=time.monotonic()-start
    record["DRC"]=check_gds(gds,out/"drc_full")
    sky130.lvs_netgen(gds,name,pdk_root="/foss/pdks",
        magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
        lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
        lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
        netlist=gold,output_file_path=out/"lvs",copy_intermediate_files=True)
    record["LVS"]=netgen_lvs_report(next((out/"lvs").rglob("*_lvs.rpt")).read_text());save()
    if not(record["DRC"]["is_clean"]and record["LVS"]["is_clean"]):
        raise SystemExit(2)
    with (out/"pex.log").open("w")as log:
        extracted=subprocess.run(["bash","/work/vendor/glayout/src/glayout/verification/run_pex.sh",str(gds),name],
            stdout=log,stderr=subprocess.STDOUT,timeout=240)
    record["PEX_returncode"]=extracted.returncode
    gold=out/(name+"_pex.spice");cell=name+"_rc"
    record["RC"]=rc_netlist_inventory(gold.read_text(),cell,ref.PORTS);save()
    if extracted.returncode or not record["RC"]["has_real_RC"]:raise SystemExit(2)

decl=next(s.split()for s in gold.read_text().splitlines()if s.lower().startswith(".subckt "+cell.lower()+" "))
binding={"GND":"0","IREF":"ref","IOUT":"out","IBIAS":"bias","VDD":"vdd","VIN":"vin","VOUT":"out"}
nodes=[binding[n.upper()]for n in decl[2:]]

def corner_run(corner):
    work=out/corner;work.mkdir();(work/".spiceinit").write_text("set ngbehavior=hsa\n")
    common=["Independent non-OTA circuit qualification",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
        ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
        ".temp 27",".include "+str(gold),"VSUPPLY vdd 0 1.8","IBIAS vdd bias 10u",
        "XDUT "+" ".join(nodes)+" "+cell]
    if name=="cascode_mirror":
        op_vectors="v(ref) v(bias) v(out) i(vsupply) i(vclamp)";opcols=6
        tails={
            "ac":["IREF vdd ref dc 10u ac 1","VCLAMP out 0 1.2"],
            "dc":["IREF vdd ref dc 10u","VCLAMP out 0 1.2"],
            "transient":["IREF vdd ref pulse(8u 10u 1u 10n 10n 1u 2u)","VCLAMP out 0 1.2"]}
        commands={"ac":["op","wrdata op.dat "+op_vectors,"ac dec 30 10 1G","wrdata ac.dat real(i(vclamp)) imag(i(vclamp))"],
            "dc":["dc VCLAMP .05 1.75 .05","wrdata dc.dat v(out) i(vclamp) v(ref) v(bias)"],
            "transient":["tran 5n 4u","wrdata transient.dat i(vclamp) v(ref) v(bias)"]}
        contracts={"op":{"kind":"op","columns":opcols,"expected_rows":1},
            "ac":{"kind":"ac","columns":3,"points":241,"start":10,"end":1e9,"scale":"log"},
            "dc":{"kind":"dc","columns":5,"points":35,"start":.05,"end":1.75,"scale":"linear"},
            "transient":{"kind":"transient","columns":4,"start":0,"end":4e-6,
                "required_windows":[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]}}
    else:
        common+=["CLOAD out 0 1p"]
        op_vectors="v(vin) v(out) v(bias) i(vsupply)";opcols=5
        tails={"ac":["VIN vin 0 dc 1.2 ac 1"],"dc":["VIN vin 0 1.2"],
            "transient":["VIN vin 0 pulse(1.19 1.21 1u 10n 10n 1u 2u)"],
            "zout":["VIN vin 0 dc 1.2 ac 0","ITEST 0 out dc 0 ac 1"]}
        commands={"ac":["op","wrdata op.dat "+op_vectors,"ac dec 30 10 1G","wrdata ac.dat real(v(out)) imag(v(out))"],
            "dc":["dc VIN .9 1.5 .05","wrdata dc.dat v(vin) v(out) v(bias) i(vsupply)"],
            "transient":["tran 5n 4u","wrdata transient.dat v(vin) v(out) v(bias)"],
            "zout":["ac dec 30 10 1G","wrdata zout.dat real(v(out)) imag(v(out))"]}
        contracts={"op":{"kind":"op","columns":opcols,"expected_rows":1},
            "ac":{"kind":"ac","columns":3,"points":241,"start":10,"end":1e9,"scale":"log"},
            "zout":{"kind":"ac","columns":3,"points":241,"start":10,"end":1e9,"scale":"log"},
            "dc":{"kind":"dc","columns":5,"points":13,"start":.9,"end":1.5,"scale":"linear"},
            "transient":{"kind":"transient","columns":4,"start":0,"end":4e-6,
                "required_windows":[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]}}
    result={"analyses":{},"integrity":{},"metrics":{}}
    for analysis,tail in tails.items():
        path=work/(analysis+".spice")
        path.write_text("\n".join(common+tail+[".control","set wr_vecnames","set wr_singlescale"]+
            commands[analysis]+["quit",".endc",".end",""]))
        started=time.monotonic()
        with (work/(analysis+"_console.log")).open("w")as log:
            try:
                sim=subprocess.run(["ngspice","-b","-o",analysis+".log",path.name],cwd=work,
                    stdout=log,stderr=subprocess.STDOUT,timeout=a.analysis_timeout)
                code=sim.returncode;timeout=False
            except subprocess.TimeoutExpired:code=None;timeout=True
        result["analyses"][analysis]={"returncode":code,"timeout":timeout,"wall_seconds":time.monotonic()-started}
        result["integrity"][analysis]=validate_analysis(work/(analysis+".dat"),work/(analysis+".log"),contracts[analysis],code)
        if analysis=="ac":result["integrity"]["op"]=validate_analysis(work/"op.dat",work/"ac.log",contracts["op"],code)
    complete=all(v["complete"]for v in result["integrity"].values())
    result["complete"]=complete
    if complete:
        op=np.loadtxt(work/"op.dat",skiprows=1,ndmin=2)[0]
        dc=np.loadtxt(work/"dc.dat",skiprows=1,ndmin=2)
        ac=np.loadtxt(work/"ac.dat",skiprows=1,ndmin=2)
        tran=np.loadtxt(work/"transient.dat",skiprows=1,ndmin=2)
        response=ac[:,1]+1j*ac[:,2];amplitude=np.abs(response)
        crossing=np.flatnonzero(amplitude<amplitude[0]/np.sqrt(2))
        high=(tran[:,0]>1.8e-6)&(tran[:,0]<1.99e-6)
        low=(tran[:,0]>2.8e-6)&(tran[:,0]<2.99e-6)
        if name=="cascode_mirror":
            currents=-dc[:,2];at=lambda v:float(currents[np.argmin(abs(dc[:,1]-v))])
            derivative=(at(1.3)-at(1.1))/.2
            result["metrics"]={"nominal_output_current_A":at(1.2),"nominal_relative_current_error":at(1.2)/1e-5-1,
                "output_resistance_ohm":float(1/abs(derivative))if derivative else None,
                "small_signal_current_gain":float(-response[0].real),
                "reference_voltage_V":float(op[1]),"bias_voltage_V":float(op[2]),
                "output_voltage_V":float(op[3]),"current_feed_power_W":float(-1.8*op[4]),
                "sampled_compliance_within_5pct_V":[float(v)for v,i in zip(dc[:,1],currents)if abs(i/1e-5-1)<=.05],
                "positive_plateau_current_A":float(-np.mean(tran[high,1])),
                "negative_plateau_current_A":float(-np.mean(tran[low,1])),
                "transient_current_gain":float((-np.mean(tran[high,1])+np.mean(tran[low,1]))/2e-6),
                "reference_transient_min_V":float(min(tran[:,2])),"reference_transient_max_V":float(max(tran[:,2])),
                "bias_transient_min_V":float(min(tran[:,3])),"bias_transient_max_V":float(max(tran[:,3]))}
            meaning=(abs(result["metrics"]["nominal_relative_current_error"])<.1 and .8<float(-response[0].real)<1.2
                and 0<op[1]<1.8 and 0<op[2]<1.8 and np.all((tran[:,2:]>=0)&(tran[:,2:]<=1.8)))
        else:
            impedance=np.loadtxt(work/"zout.dat",skiprows=1,ndmin=2)
            result["metrics"]={"input_voltage_V":float(op[1]),"output_voltage_V":float(op[2]),
                "level_shift_V":float(op[1]-op[2]),"bias_voltage_V":float(op[3]),"power_W":float(-1.8*op[4]),
                "gain_10Hz_V_per_V":float(response[0].real),
                "output_impedance_10Hz_ohm":float(abs(complex(impedance[0,1],impedance[0,2]))),
                "transient_incremental_gain":float((np.mean(tran[high,2])-np.mean(tran[low,2]))/.02),
                "sampled_dc_transfer":[{"input_V":float(row[1]),"output_V":float(row[2])}for row in dc],
                "output_transient_min_V":float(min(tran[:,2])),"output_transient_max_V":float(max(tran[:,2]))}
            meaning=(.5<float(response[0].real)<1.1 and .1<op[2]<1.2 and .2<op[1]-op[2]<1.0
                and np.all((tran[:,1:]>=0)&(tran[:,1:]<=1.8)))
        result["metrics"]["bandwidth_3dB_first_sample_Hz"]=float(ac[crossing[0],0])if len(crossing)else None
        result["development_electrical_meaning"]=bool(meaning)
    with lock:record["results"][corner]=result;save()
    print(json.dumps({"corner":corner,**result}),flush=True)

with ThreadPoolExecutor(max_workers=2)as pool:list(pool.map(corner_run,["tt","ss","ff"]))
record["simulation_flow_complete"]=len(record["results"])==3 and all(v["complete"]for v in record["results"].values())
record["electrical_meaning_established"]=record["simulation_flow_complete"]and all(v.get("development_electrical_meaning")for v in record["results"].values())
record["physical_flow_complete"]=a.fidelity=="post_rc" and record["electrical_meaning_established"]
record["diagnostic_limits_are_formal_specifications"]=False
save()
raise SystemExit(0 if record["electrical_meaning_established"]else 2)
