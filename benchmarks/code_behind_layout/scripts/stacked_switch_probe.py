"""Independent prelayout and full physical qualification of the new switch."""
import json
from pathlib import Path
import subprocess
import sys
import numpy as np

sys.path.insert(0,"/work")
from src.generators.stacked_switch_reference import schematic, DEFAULT, PORTS
from src.spice_validation import validate_analysis
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
from src.corpus_metrics import frequency_3db

out=Path.cwd()
(out/"gold.spice").write_text(schematic())
record={"scope":"development_new_independent_switch_source_qualification_not_formal_or_training",
        "sizing":DEFAULT,"supply_V":1.8,"temperature_C":27,"load_ohm":100000,"load_F":1e-12,
        "corners":["tt","ss","ff"],"prelayout":{},"post_rc":{}}


def save():
    (out/"validation.json").write_text(json.dumps(record,indent=2,allow_nan=False)+"\n")


def measure(netlist,cell,fidelity,corner,ports=PORTS):
    work=out/fidelity/corner
    work.mkdir(parents=True)
    (work/".spiceinit").write_text("set ngbehavior=hsa\n")
    binding={"IN":"vin","OUT":"out","EN":"en","ENB":"enb","VDD":"vdd","VSS":"0"}
    common=["Independent complementary switch qualification",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
        ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
        ".temp 27",".include "+str(netlist),"VSUPPLY vdd 0 1.8",
        "XDUT "+" ".join(binding[name.upper()] for name in ports)+" "+cell]
    bodies={
        "ac":["VENA en 0 1.8","VENB enb 0 0","VIN vin 0 .9 ac 1","RLOAD out 0 100k","CLOAD out 0 1p",
              ".control","op","wrdata op.dat v(vin) v(out) i(vsupply)",
              "ac dec 20 10 1G","wrdata ac.dat real(v(out)) imag(v(out))"],
        "on":["VENA en 0 1.8","VENB enb 0 0","VIN vin 0 .9","VDELTA out vin .01",
              ".control","dc VIN .05 1.75 .05","wrdata on.dat v(out) i(vdelta)"],
        "off":["VENA en 0 0","VENB enb 0 1.8","VIN vin 0 .9","VDELTA out vin .2",
               ".control","dc VIN .2 1.4 .1","wrdata off.dat v(out) i(vdelta)"],
        "tran":["VENA en 0 1.8","VENB enb 0 0","VIN vin 0 pulse(.2 1.4 1u 10n 10n 1u 2u)",
                "RLOAD out 0 100k","CLOAD out 0 1p",".control","tran 5n 4u","wrdata tran.dat v(vin) v(out)"]}
    contracts={"ac":{"kind":"ac","columns":3,"start":10,"end":1e9,"points":161,"scale":"log"},
        "on":{"kind":"dc","columns":3,"start":.05,"end":1.75,"points":35,"scale":"linear"},
        "off":{"kind":"dc","columns":3,"start":.2,"end":1.4,"points":13,"scale":"linear"},
        "tran":{"kind":"transient","columns":3,"start":0,"end":4e-6,
                "required_windows":[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]}}
    result={"analyses":{}}
    for name,body in bodies.items():
        control=body.index(".control")
        deck=common+body[:control+1]+["set wr_vecnames","set wr_singlescale"]+body[control+1:]+["quit",".endc",".end",""]
        (work/(name+".spice")).write_text("\n".join(deck))
        try:
            with (work/(name+"_console.log")).open("w") as log:
                process=subprocess.run(["ngspice","-b","-o",name+".log",name+".spice"],cwd=work,
                                       stdout=log,stderr=subprocess.STDOUT,timeout=120)
            code=process.returncode
        except subprocess.TimeoutExpired:
            code=None
        result["analyses"][name]={"returncode":code,**validate_analysis(work/(name+".dat"),work/(name+".log"),contracts[name],code)}
        if name=="ac":
            result["analyses"]["op"]={"returncode":code,**validate_analysis(work/"op.dat",work/"ac.log",
                {"kind":"op","columns":4,"expected_rows":1},code)}
    result["complete"]=all(value["complete"] for value in result["analyses"].values())
    if result["complete"]:
        on=np.loadtxt(work/"on.dat",skiprows=1,ndmin=2)
        off=np.loadtxt(work/"off.dat",skiprows=1,ndmin=2)
        ac=np.loadtxt(work/"ac.dat",skiprows=1,ndmin=2)
        tran=np.loadtxt(work/"tran.dat",skiprows=1,ndmin=2)
        op=np.loadtxt(work/"op.dat",skiprows=1,ndmin=2)[0]
        if np.any(on[:,2]==0):
            raise ValueError("On-state current is zero at a declared signal voltage")
        ron=.01/np.abs(on[:,2])
        windows=[(tran[:,0]>=start)&(tran[:,0]<=stop) for start,stop in [(1.8e-6,1.99e-6),(2.8e-6,2.99e-6)]]
        result["metrics"]={"output_bias_V":float(op[2]),"loaded_dc_gain":float(np.hypot(ac[0,1],ac[0,2])),
            "loaded_bandwidth_3db_Hz":frequency_3db(work/"ac.dat"),"maximum_Ron_ohm":float(np.max(ron)),
            "Ron_at_0p9V_ohm":float(ron[np.argmin(abs(on[:,0]-.9))]),
            "maximum_off_leakage_A":float(np.max(abs(off[:,2]))),
            "maximum_loaded_settled_error_V":max(float(np.max(abs(tran[mask,1]-tran[mask,2]))) for mask in windows)}
        result["operating_point_valid"]=bool(0<op[2]<1.8 and result["metrics"]["loaded_dc_gain"]>0)
    return result


# The independent circuit graph must have an actual valid electrical response
# before investing in the new physical generator.
for corner in record["corners"]:
    record["prelayout"][corner]=measure(out/"gold.spice","stacked_switch","prelayout",corner)
    save()
if not all(row["complete"] and row.get("operating_point_valid") for row in record["prelayout"].values()):
    raise SystemExit(2)

from glayout import sky130
from src.generators.stacked_switch import build
gds=build(out)
record["DRC"]=check_gds(gds,out/"drc_full")
save()
sky130.lvs_netgen(gds,"stacked_switch",pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=out/"gold.spice",output_file_path=out/"lvs",copy_intermediate_files=True)
record["LVS"]=netgen_lvs_report(next((out/"lvs").rglob("*_lvs.rpt")).read_text())
save()
if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:
    raise SystemExit(2)
with (out/"pex.log").open("w") as log:
    pex=subprocess.run(["bash","/work/vendor/glayout/src/glayout/verification/run_pex.sh",str(gds),"stacked_switch"],
                       stdout=log,stderr=subprocess.STDOUT,timeout=240)
netlist=out/"stacked_switch_pex.spice"
record["pex_returncode"]=pex.returncode
record["RC"]=rc_netlist_inventory(netlist.read_text(),"stacked_switch_rc",PORTS)
save()
if pex.returncode or not record["RC"]["has_real_RC"]:
    raise SystemExit(2)
for corner in record["corners"]:
    record["post_rc"][corner]=measure(netlist,"stacked_switch_rc","post_rc",corner,record["RC"]["ports"])
    save()
record["flow_complete"]=all(row["complete"] and row.get("operating_point_valid") for row in record["post_rc"].values())
save()
print(json.dumps(record,indent=2),flush=True)
raise SystemExit(0 if record["flow_complete"] else 2)
