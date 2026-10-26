"""Qualify the independently routed validation mirror; no formal results."""
import json
from pathlib import Path
import subprocess
import sys
import numpy as np

sys.path.insert(0,"/work")
from src.generators.validation_mirror import build,PORTS
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
from src.spice_validation import validate_analysis
from glayout import sky130

out=Path.cwd();gds=build(out)
record={"scope":"independent_validation_source_development_qualification","formal":False,
    "source_role":"validation_candidate_not_frozen","required_corners":["tt","ss","ff"],"corners":{}}
def save():
    (out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
record["DRC"]=check_gds(gds,out/"drc_full");save()
sky130.lvs_netgen(gds,"validation_mirror",pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=out/"reference.spice",output_file_path=out/"lvs",copy_intermediate_files=True)
record["LVS"]=netgen_lvs_report(next((out/"lvs").rglob("*_lvs.rpt")).read_text());save()
if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:raise SystemExit(2)
with (out/"pex.log").open("w") as log:
    r=subprocess.run(["bash","/work/vendor/glayout/src/glayout/verification/run_pex.sh",str(gds),"validation_mirror"],
        stdout=log,stderr=subprocess.STDOUT,timeout=120)
record["pex_returncode"]=r.returncode
net=out/"validation_mirror_pex.spice"
record["RC"]=rc_netlist_inventory(net.read_text(),"validation_mirror_rc",PORTS);save()
if r.returncode!=0 or not record["RC"]["has_real_RC"]:raise SystemExit(2)
binding={"REF":"ref","OUT":"out","GND":"0"}
nodes=[binding[p.upper()] for p in record["RC"]["ports"]]
for corner in record["required_corners"]:
    work=out/corner;work.mkdir();(work/".spiceinit").write_text("set ngbehavior=hsa\n")
    deck=["Independent validation current mirror post-RC qualification",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
        ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
        ".temp 27",".include "+str(net),"VSUPPLY vdd 0 1.8","IREF vdd ref 10u","VOUT out 0 .9",
        "XDUT "+" ".join(nodes)+" validation_mirror_rc",".save v(ref) v(out) i(vout)",
        ".control","op","set wr_vecnames","set wr_singlescale",
        "wrdata op.dat v(ref) v(out) i(vout)","dc VOUT .1 1.7 .1",
        "wrdata dc.dat v(ref) v(out) i(vout)","quit",".endc",".end",""]
    (work/"dc.spice").write_text("\n".join(deck))
    with (work/"console.log").open("w") as log:
        try:r=subprocess.run(["ngspice","-b","-o","ngspice.log","dc.spice"],cwd=work,
            stdout=log,stderr=subprocess.STDOUT,timeout=120);rc=r.returncode
        except subprocess.TimeoutExpired:rc=None
    evidence={"op":validate_analysis(work/"op.dat",work/"ngspice.log",{"kind":"op","columns":4},rc),
        "dc":validate_analysis(work/"dc.dat",work/"ngspice.log",{"kind":"dc","columns":4,"start":.1,"end":1.7,"points":17},rc)}
    row={"returncode":rc,"analysis_evidence":evidence,"analyses_complete":all(v["complete"] for v in evidence.values())}
    if row["analyses_complete"]:
        op=np.loadtxt(work/"op.dat",skiprows=1,ndmin=2)[0];data=np.loadtxt(work/"dc.dat",skiprows=1,ndmin=2)
        error=np.abs(-data[:,3]/1e-5-1);valid=error<=.05
        derivative=(-data[9,3]+data[7,3])/(data[9,2]-data[7,2])
        row.update(reference_bias_V=float(op[1]),output_current_A=float(-op[3]),
            current_error_fraction=float(abs(-op[3]/1e-5-1)),output_resistance_ohm=float(1/derivative) if derivative>0 else None,
            observed_compliance_points_5percent_V=list(map(float,data[valid,2])),
            operating_point_valid=bool(0<op[1]<1.8 and -op[3]>0))
    record["corners"][corner]=row;save()
record["flow_complete"]=all(r["analyses_complete"] and r.get("operating_point_valid") for r in record["corners"].values())
save();print(json.dumps(record,indent=2));raise SystemExit(0 if record["flow_complete"] else 2)
