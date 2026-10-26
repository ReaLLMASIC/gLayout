"""Actual development corpus-yield pilot; never emits formal training rows.

Every candidate starts from the same original cropped compiler. The eight
transparent heuristic edits are proposal sources, not eight independent
lineages or evidence of model-generated diversity. Physical results are fresh.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

EDITABLE = "textbook_sharing/layout.py"
REVISION = "1f90e33913208e572744b7c5a144a7da8c073235"
CROP_RUN = "phase0_20261018T234220871091Z_fvf_textbook_cropped_source_smoke"


def variants(text):
    plan = 'plan = nm.get(mode) or nm["independent"]'
    reverse = text.replace('    return out\n', '    return list(reversed(out))\n', 1)
    def sharing(source, mode):
        if source.count(plan) != 1: raise ValueError("Original selected compiler revision changed")
        return source.replace(plan, f'plan = nm.get("{mode}") or nm["independent"]')
    ports = text.replace('assemble(pdk, row_specs, circuit.ports, name=top)',
                         'assemble(pdk, row_specs, list(reversed(circuit.ports)), name=top)')
    choices = {
        "diffusion_plan": sharing(text, "diffusion_only"),
        "gate_plan": sharing(text, "gate_only"),
        "combined_plan": sharing(text, "combined"),
        "reverse_device_order": reverse,
        "gate_order": text.replace('    return out\n', '    return sorted(out, key=lambda d: (d.g, d.d, d.logical_id))\n', 1),
        "reverse_port_track_order": ports,
        "reverse_devices_combined": sharing(reverse, "combined"),
        "reverse_ports_combined": sharing(ports, "combined")}
    if len(set(choices.values())) != 8 or any(value == text for value in choices.values()):
        raise ValueError("Pilot proposal templates are duplicated or no-op at source level")
    return choices


def dump(path, data):
    Path(path).write_text(json.dumps(data, indent=2)+"\n")


def prepare(out, circuit, configuration=None):
    # This private engineering export reads only declarations and nominal input
    # code, never old outcomes. The emitted policy pack excludes these modules.
    export = '''import json,sys
from pathlib import Path
root=Path("/work/vendor/textbook-sharing-readonly")
sys.path[:0]=[str(root/"src"),str(root/"benchmarks/textbook_sharing")]
from textbook_sharing.circuits import CIRCUITS
from textbook_sharing.nominal import nominal
cid=sys.argv[1];out=Path(sys.argv[2]);case=nominal(cid,"sky130")
(out/"circuit_input.json").write_text(json.dumps(CIRCUITS[cid].to_json(),indent=2)+"\\n")
(out/"sizing_input.json").write_text(json.dumps(case.sizing,indent=2)+"\\n")
'''
    subprocess.run([sys.executable, "-c", export, circuit, str(out)], check=True)
    if configuration is not None:
        dump(out/"sizing_input.json",configuration["parameters"]["sizing"])
        dump(out/"configuration_input.json",configuration)
    base = out / "base_source"
    source = Path(os.environ["PROBE_INPUT"]) / "source_pack"
    if not source.is_dir():
        source = Path(os.environ["PROBE_INPUT"]) / "base_source"
    shutil.copytree(source, base)
    for name in ["circuit_input.json", "sizing_input.json"]:
        shutil.copy2(out/name, base/name)
    if any((base/path).exists() for path in ["glayout/cells", "glayout/blocks", "textbook_sharing/circuits.py"]):
        raise ValueError("Evaluation target or full topology declarations entered pilot source pack")
    return base


def worker(work):
    import gdstk
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(work/"source"), "/work"]
    os.environ["GLAYOUT_BACKEND"] = "gdsfactory"
    from glayout import sky130
    from textbook_sharing.layout import build
    from textbook_sharing.netlist import Circuit, emit_subckt
    circuit = Circuit.from_json(json.loads((work/"source/circuit_input.json").read_text()))
    sizes = json.loads((work/"source/sizing_input.json").read_text())
    name = "corpus_"+circuit.circuit_id.lower()
    gold=work/"target.spice"
    gold_text=emit_subckt("sky130",circuit,sizes,name,per_finger=True,lvs=True)
    if (work/"expected_reference.spice").exists() and gold_text!=(work/"expected_reference.spice").read_text():
        raise ValueError("Public immutable emitter differs from independent per-configuration gold")
    gold.write_text(gold_text)
    result=build(sky130,circuit,sizes,mode="independent",name=name)
    gds=work/"candidate.gds";result["component"].write_gds(gds)
    top,=gdstk.read_gds(gds).top_level();top.flatten();top.name=name
    lib=gdstk.Library();lib.add(top);lib.write_gds(gds)
    loaded={key:str(Path(module.__file__).resolve()) for key,module in sys.modules.items() if key.startswith(("glayout","textbook_sharing")) and getattr(module,"__file__",None)}
    if not all(Path(value).is_relative_to(work/"source") for value in loaded.values()):
        raise ValueError("A compiler module escaped the cropped pack")
    record=evaluate_gds(work,circuit,sizes,name,gds,gold,Path("/work/vendor/glayout/src/glayout/verification/run_pex.sh"))
    record.update(applied_plans=result["applied_plans"],assembly_stats=result["assembly_stats"],loaded_source_modules=loaded)
    dump(work/"physical.json",record)
    return record


def evaluate_gds(work,circuit,sizes,name,gds,gold,pex_script):
    """Trusted physical stage: takes GDS/configuration/gold, never source code."""
    import numpy as np
    import gdstk
    from src.physical_drc import check_gds
    from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
    from src.spice_validation import validate_analysis
    from src.corpus_metrics import mirror_dc_metrics,frequency_3db
    top,=gdstk.read_gds(gds).top_level()
    if top.name!=name:raise ValueError("Accepted GDS top differs from immutable reference")
    record={"scope":"development_corpus_yield_not_formal_or_training","candidate_id":work.name,
            "circuit_id":circuit.circuit_id,"source_revision":REVISION,"formal_admissible":False}
    def save():dump(work/"physical.json",record)
    record["area_um2"]=float((top.bounding_box()[1][0]-top.bounding_box()[0][0])*(top.bounding_box()[1][1]-top.bounding_box()[0][1]))
    record["DRC"]=check_gds(gds,work/"drc_full");save()
    tcl="\n".join(["gds read {"+str(gds)+"}","load "+name,"select top cell","extract all","ext2spice lvs",
                      "ext2spice -o layout_lvs.spice","quit -noprompt",""])
    (work/"lvs_extract.tcl").write_text(tcl)
    with (work/"lvs_magic.log").open("w") as log:
        extracted=subprocess.run(["magic","-rcfile","/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc","-noconsole","-dnull"],
            input=tcl,text=True,stdout=log,stderr=subprocess.STDOUT,cwd=work,timeout=120)
    with (work/"netgen.log").open("w") as log:
        lvs=subprocess.run(["netgen","-batch","lvs",str(work/"layout_lvs.spice")+" "+name,str(gold)+" "+name,
            "/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",str(work/"netgen_lvs.rpt")],stdout=log,stderr=subprocess.STDOUT,cwd=work,timeout=120)
    record["LVS"]=netgen_lvs_report((work/"netgen_lvs.rpt").read_text());save()
    if not(record["DRC"]["is_clean"] and record["LVS"]["is_clean"]): return record
    with (work/"pex.log").open("w") as log:
        pex=subprocess.run(["bash",str(pex_script),str(gds),name],
            stdout=log,stderr=subprocess.STDOUT,cwd=work,timeout=180)
    netlist=work/(name+"_pex.spice")
    record["pex_returncode"]=pex.returncode
    record["RC"]=rc_netlist_inventory(netlist.read_text(),name+"_rc",circuit.ports);save()
    if pex.returncode or not record["RC"]["has_real_RC"]: return record
    binding={"VDD":"vdd","VSS":"0","IB1":"bias","IOUT1":"out","VIN1":"vin","VIN2":"vn","VB1":"bias","VOUT1":"out"}
    nodes=" ".join(binding[p.upper()] for p in record["RC"]["ports"])
    record["corners"]={}
    for corner in ["tt","ss","ff"]:
        bench=work/corner;bench.mkdir();(bench/".spiceinit").write_text("set ngbehavior=hsa\n")
        common=["Development corpus actual full-RC yield", ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
          ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16", ".temp 27", ".include "+str(netlist),
          "VSUPPLY vdd 0 1.8", "XDUT "+nodes+" "+name+"_rc"]
        if circuit.circuit_id=="C01":
            common += ["IBIAS vdd bias 20u"]
            bodies={"ac":["VOUT out 0 .9 ac 1",".control","op","wrdata op.dat v(out) v(bias) i(vout)","ac dec 20 10 1G","wrdata ac.dat real(i(vout)) imag(i(vout))"],
                    "tran":["VOUT out 0 pulse(.85 .95 1u 10n 10n 1u 2u)",".control","tran 5n 4u","wrdata tran.dat v(out) i(vout)"],
                    "dc":["VOUT out 0 .9",".control","dc VOUT 0 1.8 .1","wrdata dc.dat v(out) i(vout)"]}
            opcols=4;dcpoints=19;dcstart=0;dcend=1.8
        elif circuit.circuit_id=="C05":
            reference=sizes["M1"]
            common += ["VBIASSUPPLY vddbias 0 1.8","IBIAS vddbias bias 20u",f"XBIAS bias bias 0 0 sky130_fd_pr__nfet_01v8 w={reference['w']/reference['nf']:g} l={reference['l']:g} m={reference['nf']}","RLOAD out 0 20k","CLOAD out 0 1p"]
            bodies={"ac":["VIN vin 0 1.17 ac 1",".control","op","wrdata op.dat v(out) v(bias) i(vsupply)","ac dec 20 10 1G","wrdata ac.dat real(v(out)) imag(v(out))"],
                    "tran":["VIN vin 0 pulse(1.16 1.18 1u 10n 10n 1u 2u)",".control","tran 5n 4u","wrdata tran.dat v(vin) v(out)"],
                    "dc":["VIN vin 0 1.17",".control","dc VIN .8 1.4 .05","wrdata dc.dat v(vin) v(out)"]}
            opcols=4;dcpoints=13;dcstart=.8;dcend=1.4
        elif circuit.circuit_id=="C08":
            reference=sizes["M3"]
            common += ["VBIASSUPPLY vddbias 0 1.8","IBIAS vddbias bias 40u",f"XBIAS bias bias 0 0 sky130_fd_pr__nfet_01v8 w={reference['w']/reference['nf']:g} l={reference['l']:g} m={reference['nf']}","CLOAD out 0 1p"]
            bodies={"ac":["VIN vin 0 .9 ac 1","LSERVO out vn 1G","CAC vn 0 1G",".control","op","wrdata op.dat v(out) v(bias) i(vsupply)","ac dec 30 10 1G","wrdata ac.dat real(v(out)) imag(v(out))"],
                    "tran":["VFB out vn 0","VIN vin 0 pulse(.89 .91 1u 10n 10n 1u 2u)",".control","tran 5n 4u","wrdata tran.dat v(vin) v(out)"],
                    "dc":["VFB out vn 0","VIN vin 0 .9",".control","dc VIN .6 1.2 .1","wrdata dc.dat v(vin) v(out)"]}
            opcols=4;dcpoints=7;dcstart=.6;dcend=1.2
        else: raise ValueError("This bounded pilot has only independently implemented C01/C05/C08 benches")
        analyses={};metrics={}
        for analysis,body in bodies.items():
            control=body.index(".control")
            body=body[:control+1]+["set wr_vecnames","set wr_singlescale"]+body[control+1:]+["quit",".endc",".end",""]
            (bench/(analysis+".spice")).write_text("\n".join(common+body))
            with (bench/(analysis+"_console.log")).open("w") as log:
                ran=subprocess.run(["ngspice","-b","-o",analysis+".log",analysis+".spice"],cwd=bench,stdout=log,stderr=subprocess.STDOUT,timeout=120)
            contract=({"kind":"ac","columns":3,"start":10,"end":1e9,"points":241 if circuit.circuit_id=="C08" else 161,"scale":"log"} if analysis=="ac" else
                      {"kind":"transient","columns":3,"start":0,"end":4e-6,"required_windows":[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]] if circuit.circuit_id=="C08" else [[1.8e-6,1.99e-6]]} if analysis=="tran" else
                      {"kind":"dc","columns":3,"start":dcstart,"end":dcend,"points":dcpoints,"scale":"linear"})
            analyses[analysis]={**validate_analysis(bench/(analysis+".dat"),bench/(analysis+".log"),contract,ran.returncode),"returncode":ran.returncode}
            if analysis=="ac":analyses["op"]={**validate_analysis(bench/"op.dat",bench/"ac.log",{"kind":"op","columns":opcols,"expected_rows":1},ran.returncode),"returncode":ran.returncode}
        complete=all(row["complete"] for row in analyses.values())
        if complete:
            op=np.loadtxt(bench/"op.dat",skiprows=1,ndmin=2);ac=np.loadtxt(bench/"ac.dat",skiprows=1,ndmin=2)
            metrics={"output_bias_V":float(op[-1,1]),"bias_V":float(op[-1,2]),"measured_current_A":float(-op[-1,3])}
            if circuit.circuit_id=="C01":
                metrics["OP_current_A"]=metrics["measured_current_A"]
                metrics.update(mirror_dc_metrics(bench/"dc.dat"))
                metrics["OP_DC_relative_discrepancy"]=abs(metrics["OP_current_A"]/metrics["nominal_current_A"]-1)
            else:
                metrics['DUT_supply_power_W']=1.8*metrics['measured_current_A']
                metrics['external_replica_bias_supply_power_W']=1.8*(20e-6 if circuit.circuit_id=='C05' else 40e-6)
                response=ac[:,1]+1j*ac[:,2];db=20*np.log10(np.abs(response));phase=np.unwrap(np.angle(response))*180/np.pi
                metrics.update(gain_10Hz_dB=float(db[0]),gain_10Hz_real=float(response[0].real))
                if circuit.circuit_id=="C05":metrics["f3db_Hz"]=frequency_3db(bench/"ac.dat")
                crossings=np.flatnonzero((db[:-1]>=0)&(db[1:]<0))
                if len(crossings):
                    j=int(crossings[0]);fraction=-db[j]/(db[j+1]-db[j]);metrics["phase_margin_deg"]=float(180+phase[j]+fraction*(phase[j+1]-phase[j]))
                    metrics["ugb_Hz"]=float(np.exp(np.log(ac[j,0])+fraction*np.log(ac[j+1,0]/ac[j,0])))
                if circuit.circuit_id=="C08":
                    tran=np.loadtxt(bench/"tran.dat",skiprows=1,ndmin=2)
                    windows=[(tran[:,0]>=lo)&(tran[:,0]<=hi) for lo,hi in [(1.8e-6,1.99e-6),(2.8e-6,2.99e-6)]]
                    metrics["settled_tracking_error_V"]=max(float(np.max(np.abs(tran[mask,2]-tran[mask,1]))) for mask in windows)
        record["corners"][corner]={"complete":complete,"analyses":analyses,"metrics":metrics};save()
    record["full_physical_analysis_complete"]=all(row["complete"] for row in record["corners"].values())
    save();return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--circuit",choices=["C01","C05","C08"],default="C01")
    p.add_argument("--limit",type=int,default=8);p.add_argument("--worker",type=Path)
    p.add_argument("--family-table",type=Path);p.add_argument("--configuration-id")
    p.add_argument("--existing-baseline",type=Path,help="Reuse exact completed development baseline; do not simulate it again")
    p.add_argument("--model-pool",help="Raw model pool JSON relative to PROBE_INPUT; do not repair diffs")
    a=p.parse_args()
    if a.worker:
        try:worker(a.worker.resolve())
        except Exception:
            (a.worker/"failure.txt").write_text(traceback.format_exc());raise
        return
    if not 0<=a.limit<=8:raise ValueError("Initial bounded pilot supports 0..8 real source candidates")
    if bool(a.family_table)!=bool(a.configuration_id):raise ValueError("Family table and configuration id are paired")
    configuration=None
    if a.family_table:
        table=json.loads(a.family_table.read_text())
        configuration=next(row for row in table["configurations"] if row["configuration_id"]==a.configuration_id)
    out=Path.cwd();base=prepare(out,a.circuit,configuration);source=(base/EDITABLE).read_text()
    proposals=[{"candidate_id":"baseline","patch":"","proposal_source":"original_baseline"}]
    if a.model_pool:
        raise ValueError("Raw model patches require scripts/corpus_isolated_evaluate.py; this transparent heuristic worker is not a model execution boundary")
    else:
        for proposal,text in list(variants(source).items())[:a.limit]:
            patch="".join(difflib.unified_diff(source.splitlines(keepends=True),text.splitlines(keepends=True),fromfile="a/"+EDITABLE,tofile="b/"+EDITABLE))
            proposals.append({"candidate_id":proposal,"patch":patch,"proposal_source":"declared_heuristic_source_edit"})
    summary={"scope":"development_corpus_yield_not_formal_or_training","source_revision":REVISION,"circuit_id":a.circuit,
             "initial_state":"original_unmodified_public_compiler", "editable_paths":[EDITABLE],"proposals":[],"formal_training_rows":0}
    for item in proposals:
        proposal=item["candidate_id"]
        if not proposal.replace("_","").isalnum():raise ValueError("Unsupported candidate identifier")
        case=out/proposal;case.mkdir();shutil.copytree(base,case/"source")
        if configuration is not None:
            shutil.copyfile(Path("/work")/configuration["reference_file"],case/"expected_reference.spice")
        patch=item["patch"]
        (case/"candidate.patch").write_text(patch)
        dump(case/"proposal.json",item)
        if proposal=="baseline" and a.existing_baseline:
            checked=time.monotonic();previous=a.existing_baseline
            old_configuration=json.loads((previous/"configuration_input.json").read_text())
            if old_configuration!=configuration or (previous/"base_source"/EDITABLE).read_text()!=source:
                raise ValueError("Completed baseline differs in source or geometry")
            prior=json.loads((previous/"baseline/physical.json").read_text())
            if not prior.get("full_physical_analysis_complete") or not all(prior[key]["is_clean"] for key in ["DRC","LVS"]) or not prior["RC"]["has_real_RC"]:
                raise ValueError("Completed baseline physical gates are not established")
            if (previous/"baseline/target.spice").read_text()!=(case/"expected_reference.spice").read_text():
                raise ValueError("Completed baseline reference differs")
            reused={key:prior[key] for key in ["DRC","LVS","RC","area_um2","full_physical_analysis_complete","corners"]}
            summary["proposals"].append({"candidate_id":"baseline","proposal_source":"completed_development_baseline","physical_evaluated":False,"reused_completed_evidence":str(previous),"reuse_check_seconds":time.monotonic()-checked,**reused})
            dump(out/"yield.json",summary);continue
        if patch:
            sys.path.insert(0,"/work");from src.candidate_executor import apply_source_patch
            try:
                apply_source_patch(case/"source",patch,[EDITABLE])
            except (ValueError,subprocess.CalledProcessError) as exc:
                (case/"patch_failure.txt").write_text(str(exc)+"\n"+str(getattr(exc,"stderr","")))
                summary["proposals"].append({"candidate_id":proposal,"proposal_source":item["proposal_source"],"patch_bytes":len(patch.encode()),"failure_class":"candidate_invalid_patch","physical_evaluated":False})
                dump(out/"yield.json",summary);continue
        elif proposal!="baseline":
            summary["proposals"].append({"candidate_id":proposal,"proposal_source":item["proposal_source"],"failure_class":"candidate_no_patch","physical_evaluated":False})
            dump(out/"yield.json",summary);continue
        started=time.monotonic()
        with (case/"worker.log").open("w") as log:
            try:
                run=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--worker",str(case)],stdout=log,stderr=subprocess.STDOUT,timeout=360)
                status={"returncode":run.returncode}
            except subprocess.TimeoutExpired:status={"returncode":None,"timeout":True}
        status.update(candidate_id=proposal,proposal_source=item["proposal_source"],patch_bytes=len(patch.encode()),wall_seconds=time.monotonic()-started,physical_evaluated=True)
        if (case/"physical.json").exists():
            physical=json.loads((case/"physical.json").read_text());status.update({key:physical.get(key) for key in ["DRC","LVS","RC","area_um2","full_physical_analysis_complete","corners"]})
        summary["proposals"].append(status);dump(out/"yield.json",summary)
        print(json.dumps({key:value for key,value in status.items() if key not in ["corners","RC"]}),flush=True)
    summary["physical_complete_candidates"]=sum(bool(row.get("full_physical_analysis_complete")) for row in summary["proposals"] if row["candidate_id"]!="baseline")
    dump(out/"yield.json",summary)


if __name__=="__main__":main()
