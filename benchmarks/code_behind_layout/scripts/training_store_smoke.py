#!/usr/bin/env python3
"""Real development admission predicate: C01 binary capsule and sampled syntax failure."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.candidate_executor import CandidateExecutor
from src.training import TrustedPhysicalStore


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--capsule",type=Path,required=True)
    p.add_argument("--failed-run",type=Path)
    p.add_argument("--recheck-directory",type=Path,help="Re-read completed raw evidence without rerunning physical tools")
    a=p.parse_args()
    capsule=a.capsule.resolve();preparation=json.loads((capsule/"preparation.json").read_text())
    pack=capsule/"source_pack";trusted=capsule/"trusted";editable=preparation["editable_paths"]
    files=preparation["source_files"];trusted_files=preparation["trusted_files"]
    anchor=next(row for row in preparation["configurations"] if row["configuration_id"]=="anchor")
    point={**anchor,"trusted_evaluator_files":{name:(trusted/name).read_text() for name in trusted_files},
        "editable_paths":editable,"lineage_editable_paths":editable,
        "frozen_source_pack":str(pack),"frozen_source_files":[name for name in files if name not in editable]}
    if a.recheck_directory:
        original=json.loads((a.recheck_directory/"calibration.json").read_text())
        gold=original["gold_control"]["run_directory"];candidate=original["candidate_failure"]["run_directory"]
        base={name:(pack/name).read_text() for name in editable}
        failed={name:(Path(candidate)/"source"/name).read_text() for name in editable}
        control=TrustedPhysicalStore.inspect_development_run(gold,point,base)
        point["gold_control"]={"run_directory":gold}
        negative=TrustedPhysicalStore.inspect_development_run(candidate,point,failed)
        result={"phase":"development_training_store_calibration_recheck","gold_control_S2":control["S2"],
            "candidate":{key:negative[key] for key in ("S0","S1","S2","failure_class","execution_integrity","objective","point_evaluation_complete")},
            "candidate_run":candidate,"gold_run":gold,"formal_training_rows":0,"physical_calls":0}
        (a.recheck_directory/"fresh_recheck.json").write_text(json.dumps(result,indent=2)+"\n")
        print(json.dumps(result,indent=2),flush=True);return
    if not a.failed_run:p.error("--failed-run is required unless rechecking existing evidence")
    out=ROOT/"runs/development/training_store_smoke"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ");out.mkdir(parents=True)
    bad=out/"actual_sampled_failure_source";shutil.copytree(pack,bad)
    layout="textbook_sharing/layout.py";(bad/layout).chmod(0o644)
    shutil.copyfile(a.failed_run/"source"/layout,bad/layout)
    base={name:(pack/name).read_text() for name in editable};failed={name:(bad/name).read_text() for name in editable}
    context={"phase":"development_training_store_calibration","initial_state_id":"development_C01_original",
        "parent_lineage":preparation["parent_lineage"],"configuration_id":"anchor","reference_id":anchor["reference_id"],
        "pdk_revision":"0fe599b2afb6708d281543108caf8310912f54af"}
    executor=CandidateExecutor(ROOT/"runtime/GLdev",out/"physical",ROOT/"runtime/magic-8.3.685",timeout=360)
    arguments={"source_paths":files,"entrypoint":"generator.py","representation":"G2","configuration":anchor["parameters"],
        "trusted_dir":trusted,"trusted_paths":trusted_files,"fidelity":"pex_spice","phase":"development_training_store_calibration"}
    gold=executor.execute(source_dir=pack,context={**context,"candidate_id":"calibrated_original","source_role":"trusted_evaluator_control"},**arguments)
    control=TrustedPhysicalStore.inspect_development_run(gold["run_directory"],point,base)
    if not control["S2"]:raise ValueError("The new same-version control did not establish actual complete physics")
    result=executor.execute(source_dir=bad,context={**context,"candidate_id":"actual_seed241_reexecution","source_role":"development_candidate_failure_calibration"},**arguments)
    point["gold_control"]={"run_directory":gold["run_directory"]}
    negative=TrustedPhysicalStore.inspect_development_run(result["run_directory"],point,failed)
    without_control={k:v for k,v in point.items() if k!="gold_control"};rejected_without_control=False
    try:TrustedPhysicalStore.inspect_development_run(result["run_directory"],without_control,failed)
    except ValueError:rejected_without_control=True
    binary=[]
    for name in point["frozen_source_files"]:
        try:(pack/name).read_text()
        except UnicodeDecodeError:binary.append(name)
    summary={"phase":"development_training_store_calibration","original_sample_failure":str(a.failed_run),"gold_control":control,
        "candidate_failure":negative,"rejected_without_control":rejected_without_control,"complete_source_files":len(files),
        "editable_text_modules":editable,"frozen_files":len(point["frozen_source_files"]),"binary_frozen_files":binary,
        "no_old_evidence_was_overwritten":True,"formal_training_rows":0,"output":str(out)}
    (out/"calibration.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)


if __name__=="__main__":main()
