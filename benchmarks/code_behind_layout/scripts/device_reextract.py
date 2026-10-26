"""Diagnose explicit all-net RC extraction on an already LVS-clean MOS layout."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import gdstk

source = Path(os.environ["PROBE_INPUT"])
out = Path.cwd()
top, = gdstk.read_gds(source/"device4.gds").top_level()
top.flatten()
top.remove(*(p for p in top.polygons if (p.layer,p.datatype)==(64,44)))
top.name="device4_input"
lib=gdstk.Library();lib.add(top);lib.write_gds(out/"input.gds")
tcl="\n".join(["drc off","gds read "+str(out/"input.gds"),"load device4_input","select top cell",
    "flatten device4_rc","load device4_rc","select top cell","extract do local","extract all",
    "feedback save extraction_feedback.tcl","ext2sim labels on","ext2sim",
    "extresist simplify off","extresist all","ext2spice lvs","ext2spice cthresh 0",
    "ext2spice extresist on","ext2spice -o device4_pex.spice","quit -noprompt",""])
(out/"extract.tcl").write_text(tcl)
with (out/"magic.log").open("w") as log:
    run=subprocess.run(["magic","-rcfile","/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc","-noconsole","-dnull"],
        input=tcl,text=True,stdout=log,stderr=subprocess.STDOUT,timeout=120)
text=(out/"device4_pex.spice").read_text()
record={"returncode":run.returncode,"subckts":[s for s in text.splitlines() if s.lower().startswith(".subckt")],
    "counts":{k:len(re.findall('^'+k+r'\S*\s',text,re.I|re.M)) for k in ['R','C','X']}}
prior=json.loads((source/"validation.json").read_text())
record.update(scope="development_full_device_flow_with_linked_DRC_LVS",source_directory=str(source),
    DRC=prior["DRC"],LVS=prior["LVS"],corners={})
decl=record["subckts"][0].split()
if set(decl[2:])!={"D","G","S","B"} or len(decl[2:])!=4:
    raise SystemExit("Extracted MOS terminal interface is incomplete")
bindings={"D":"drain","G":"gate","S":"0","B":"0"}
for corner in ["tt","ss","ff"]:
    work=out/corner;work.mkdir()
    (work/".spiceinit").write_text("set ngbehavior=hsa\n")
    deck="\n".join(["All-net RC MOS operating point",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
        ".option scale=1e-6", ".temp 27", ".include "+str(out/"device4_pex.spice"),
        "VGS gate 0 .9","VDS drain 0 .9",
        "XDUT "+" ".join(bindings[n] for n in decl[2:])+" "+decl[1],
        ".control","op","set wr_vecnames","set wr_singlescale",
        "wrdata operating_point.dat v(gate) v(drain) i(vds)","quit",".endc",".end",""])
    (work/"testbench.spice").write_text(deck)
    with (work/"console.log").open("w") as log:
        sim=subprocess.run(["ngspice","-b","-o","ngspice.log","testbench.spice"],cwd=work,
            stdout=log,stderr=subprocess.STDOUT,timeout=60)
    data=work/"operating_point.dat";result={"returncode":sim.returncode,"electrically_valid":False}
    if data.exists():
        row=list(map(float,data.read_text().splitlines()[-1].split()))
        if len(row)==4 and all(map(math.isfinite,row)):
            result.update(gate_V=row[1],drain_V=row[2],drain_source_current_A=row[3],
                electrically_valid=sim.returncode==0 and row[3]<0 and abs(row[1]-.9)<1e-6 and abs(row[2]-.9)<1e-6)
    record["corners"][corner]=result
record["flow_complete"]=(record["DRC"]["is_clean"] and record["LVS"]["is_clean"]
    and run.returncode==0 and record["counts"]["R"]>0 and record["counts"]["C"]>0
    and all(v["electrically_valid"] for v in record["corners"].values()))
(out/"extraction.json").write_text(json.dumps(record,indent=2)+"\n")
print(json.dumps(record,indent=2))
raise SystemExit(0 if record["flow_complete"] else 2)
