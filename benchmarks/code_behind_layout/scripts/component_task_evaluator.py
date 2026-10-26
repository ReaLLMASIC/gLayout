"""Trusted pair/TG/FVF evaluator using unchanged frozen characterization benches."""
import argparse
import json
import math
from pathlib import Path
import subprocess

import gdstk
import numpy as np
from src.measurement import assess
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
from src.spice_validation import validate_analysis

p=argparse.ArgumentParser();p.add_argument("--gds");p.add_argument("--output");p.add_argument("--fidelity");a=p.parse_args()
out=Path(a.output);gds=Path(a.gds);definition=json.loads(Path("/trusted/bench.json").read_text())
contract=json.loads(Path("/trusted/contract.json").read_text());kind=definition["kind"];top_name=definition["top"];ports=definition["ports"]
top,=gdstk.read_gds(gds).top_level()
if top.name!=top_name:raise ValueError("Candidate top differs from the fixed circuit")
observation={key:contract[key] for key in ("task_id","configuration_id","reference_id")}
observation.update(executed=True,gds_emitted=True,checks={},corners={});artifacts={"spice":{}}


def save_validation(point_complete=False,analysis_complete=False):
    tiers=assess(contract,observation)
    result={"contract":contract,"observation":observation,"artifacts":artifacts,"assessment":tiers,
        "analysis_complete":analysis_complete,"point_evaluation_complete":point_complete,"complete_domain_evaluation":False,
        "execution_integrity":"valid" if point_complete else "incomplete","failure_class":None if tiers["S2"] else "candidate" if point_complete else "unknown",
        "scope":"development_independent_trusted_component_point"}
    (out/"validation.json").write_text(json.dumps(result,indent=2)+"\n");return result


def magic(commands,stem):
    text="\n".join(commands+["puts stdout EXTRACTION_COMPLETE","quit -noprompt",""])
    (out/(stem+".tcl")).write_text(text)
    with (out/(stem+".log")).open("w") as log:
        result=subprocess.run(["magic","-rcfile","/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc","-noconsole","-dnull"],
            input=text,text=True,stdout=log,stderr=subprocess.STDOUT,cwd=out,timeout=180)
    if result.returncode:raise RuntimeError("Magic extraction failed")


drc=check_gds(gds,out/"drc",timeout=180)
(out/"drc/metadata.json").write_text(json.dumps(drc,indent=2)+"\n")
artifacts["drc"]={"report":"drc/direct_drc.rpt","metadata":"drc/metadata.json"};observation["checks"]["drc"]=drc["is_clean"]
save_validation(drc["completed"] and not drc["is_clean"])
if not drc["completed"]:raise RuntimeError("Full-rule DRC did not complete")
if not drc["is_clean"]:raise SystemExit(2)
magic(["drc off","gds read {"+str(gds)+"}","load "+top_name,"select top cell","flatten "+top_name+"_lvs","load "+top_name+"_lvs","select top cell",
    "extract all","ext2spice lvs","ext2spice -o extracted_lvs.spice"],"lvs_extract")
with (out/"netgen.log").open("w") as log:
    lvs_process=subprocess.run(["netgen","-batch","lvs",str(out/"extracted_lvs.spice")+" "+top_name+"_lvs","/trusted/reference.spice "+top_name,
        "/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",str(out/"lvs.rpt")],stdout=log,stderr=subprocess.STDOUT,timeout=180)
lvs=netgen_lvs_report((out/"lvs.rpt").read_text() if (out/"lvs.rpt").is_file() else "")
clean=lvs_process.returncode==0 and lvs["is_clean"]
for key in ("lvs","devices","ports","intent"):observation["checks"][key]=clean
artifacts["lvs"]={"report":"lvs.rpt"};save_validation(not clean and (out/"lvs.rpt").is_file())
if not clean:raise SystemExit(2)
if a.fidelity!="pex_spice":raise ValueError("This full baseline requires physical RC and complete analyses")
magic(["drc off","gds read {"+str(gds)+"}","load "+top_name,"select top cell","flatten "+top_name+"_rc","load "+top_name+"_rc","select top cell",
    "extract do local","extract all","feedback save extraction_feedback.tcl","ext2sim labels on","ext2sim","extresist simplify off","extresist all",
    "ext2spice lvs","ext2spice cthresh 0","ext2spice extresist on","ext2spice -o "+top_name+"_pex.spice"],"rc_extract")
pex=out/(top_name+"_pex.spice");inventory=rc_netlist_inventory(pex.read_text(),top_name+"_rc",ports)
(out/"rc_inventory.json").write_text(json.dumps(inventory,indent=2)+"\n")
artifacts["pex"]={"netlist":pex.name,"top_cell":top_name+"_rc","ports":ports}
observation["pex"]={"executed":True,"kind":"physical_rc","resistance_extracted":inventory["has_real_RC"],"capacitance_extracted":inventory["has_real_RC"]}
save_validation()
if not inventory["has_real_RC"]:raise RuntimeError("Extraction did not establish real positive unsimplified RC")

# The actual benchmark loop is frozen separately by the host. It has its own
# namespace so the existing loop's local variable 'contract' cannot replace the
# independent task contract above. Candidate source is never imported here.
record={"results":{}}
def save():
    (out/"characterization_point.json").write_text(json.dumps(record,indent=2,allow_nan=False)+"\n")
namespace={"out":out,"pex":pex,"record":record,"save":save,"np":np,"json":json,"subprocess":subprocess,"validate_analysis":validate_analysis}
bench=Path("/trusted/bench.py").read_text()
exec(compile(bench,"/trusted/bench.py","exec"),namespace)
for corner in contract["required_corners"]:
    row=record["results"]["post_rc"][corner];complete=row["complete"];raw=row["metrics"];metrics={};healthy=False
    if complete:
        if kind=="pair":
            metrics={"absolute_branch_imbalance":{"value":abs(raw["zero_input_relative_branch_imbalance"]),"unit":"1"},
                "loaded_differential_gain":{"value":raw["loaded_differential_gain_10Hz_V_per_V"],"unit":"1"},
                "differential_transconductance":{"value":raw["differential_transconductance_S"],"unit":"S"},
                "loaded_bandwidth":{"value":raw["loaded_bandwidth_3dB_Hz"],"unit":"Hz"}}
            healthy=0<raw["zero_input_tail_V"]<1.2 and raw["tail_current_sum_A"]>0
        elif kind=="tg":
            metrics={"on_resistance_at_0p9V":{"value":raw["on_resistance_ohm"]["at_0p9V"],"unit":"ohm"},
                "absolute_off_current":{"value":raw["max_abs_off_terminal_current_A"],"unit":"A"},
                "high_settled_error":{"value":raw["max_abs_high_settled_error_V"],"unit":"V"},
                "low_settled_error":{"value":raw["max_abs_low_settled_error_V"],"unit":"V"}}
            healthy=0<=raw["output_min_V"]<=raw["output_max_V"]<=1.8 and raw["on_resistance_ohm"]["min"]>0
        elif kind=="follower":
            metrics={"voltage_gain_10Hz":{"value":raw["voltage_gain_10Hz_V_per_V"],"unit":"1"},"output_impedance_10Hz":{"value":raw["output_impedance_10Hz_ohm"],"unit":"ohm"},"bandwidth":{"value":raw["bandwidth_3dB_Hz"],"unit":"Hz"}}
            healthy=0<raw["nominal_output_V"]<1.8 and 0<raw["nominal_bias_V"]<1.8
        else:raise ValueError("Unknown frozen benchmark")
    observation["corners"][corner]={"converged":complete,"operating_point_valid":complete and healthy,"metrics":metrics}
    names={name:name for name in row["analyses"]}
    if kind in ("pair","follower"):names["op"]="differential" if kind=="pair" else "gain"
    artifacts["spice"][corner]={"analyses":{name:{"data":"post_rc/"+corner+"/"+name+".dat","log":"post_rc/"+corner+"/"+analysis+".log",**{key:row["analyses"][analysis][key] for key in ("returncode","timeout") if key in row["analyses"][analysis]}} for name,analysis in names.items()}}
    save_validation()
complete=all(row["complete"] for row in record["results"]["post_rc"].values()) and set(record["results"]["post_rc"])==set(contract["required_corners"])
result=save_validation(complete,complete)
print(json.dumps(result),flush=True)
raise SystemExit(0 if result["assessment"]["S2"] and complete else 2)
