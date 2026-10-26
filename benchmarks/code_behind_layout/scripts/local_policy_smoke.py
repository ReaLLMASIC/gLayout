#!/usr/bin/env python3
"""Development-only T0/engineering-adapter decisions and real visible MOS loop."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.candidate_executor import VisibleActionGateway
from src.local_model_adapter import LocalDecisionAdapter

SSH=["ssh","-i","~/.ssh/cbl_server_key","-o","BatchMode=yes",
    "-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=12","cbl-server"]
REMOTE="/srv/code-behind-layout"
INITIAL='''import argparse, shutil
p=argparse.ArgumentParser()
p.add_argument("--configuration")
p.add_argument("--output")
a=p.parse_args()
shutil.copyfile("/library/device_typo.gds",a.output)
'''


def packet(decisions):
    return {"task_id":"development_local_policy_physical_loop","goal":
        ("First return read_source for generator.py. " if decisions==1 else
         "Complete four logical development steps within eight total decisions: read_source generator.py, propose a minimal unified source patch "
         "repairing its wrong PCell path, request_evaluation anchor at pex_spice, then finish after actual physical feedback. "
         "Rejected actions consume a decision; use the actual rejection feedback to correct your next action. ")+
        "The only allowed PCell path is /library/device4.gds. Preserve the generator CLI. "
        "This is an engineering interface calibration, excluded from formal experiments and training.",
        "contract":{"scope":"single MOS development interface calibration","required_corners":["tt","ss","ff"],
            "required_checks":["full DRC","independent LVS","positive physical RC","complete OP"],
            "drain_current_A":{"min":10e-6,"max":300e-6}},"allowed_paths":["generator.py"],
        "visible_sources":{"generator.py":"Use read_source for the actual contents"},
        "documents":{"generator_api":"python generator.py --configuration PATH --output /output/candidate.gds; emit only this GDS",
            "patch_format":"propose_patch.patch must be a full ordinary unified diff, with --- a/generator.py, +++ b/generator.py, an accurate @@ -oldline,count +newline,count @@ hunk header, and -/+ changed lines. A replacement Python line alone is not a source patch. Include the final newline."},
        "visible_configurations":["anchor"],"budget":{"decisions":decisions}}


def run(args):
    root=args.root.resolve();out=root/"runs/development/local_policy_smoke"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex[:6])
    source=out/"source";source.mkdir(parents=True);(source/"generator.py").write_text(INITIAL)
    adapter=LocalDecisionAdapter(out/"decisions",SSH+["python3 "+REMOTE+"/scripts/serve_local_policy.py --request"])
    config={"variant":args.variant,"base_revision":json.loads((root/"configs/training/backbone_cache.json").read_text())["revision"],
        "timeout_seconds_per_decision":600}
    session=adapter.start(packet(8 if args.loop else 1),config)
    remote_source=REMOTE+"/runs/development/local_policy_executor/"+session["session_id"]+"/source"
    physical=[];actions=[];accepted_actions=[];observations=[];rejections=[]
    def evaluate(name,fidelity):
        if name!="anchor" or fidelity!="pex_spice":raise ValueError("This calibration supports only actual anchor pex_spice")
        subprocess.run(SSH+["mkdir -p "+shlex.quote(remote_source)],check=True,capture_output=True,text=True)
        subprocess.run(["scp"]+SSH[1:-1]+[str(source/"generator.py"),"cbl-server:"+remote_source+"/generator.py"],check=True,capture_output=True,text=True)
        command=" ".join(map(shlex.quote,["python3",REMOTE+"/scripts/local_policy_smoke.py","--physical-source",remote_source]))
        result=subprocess.run(SSH+[command],text=True,capture_output=True,timeout=360)
        index=len(physical);(out/("physical_%02d_stdout.json"%index)).write_text(result.stdout)
        (out/("physical_%02d_stderr.log"%index)).write_text(result.stderr)
        record=json.loads(result.stdout);physical.append(record)
        return {"status":record["status"],"physical_result":record["physical_result"],"analysis_complete":record["analysis_complete"]}
    gateway=VisibleActionGateway(session["packet"],source,evaluate)
    observation={"status":"begin","next":"read_source"};error=None
    try:
        for _ in range(session["packet"]["budget"]["decisions"]):
            try:
                action=adapter.step(session,observation);actions.append(action["action"])
                observation=gateway.dispatch(action);observations.append(observation);accepted_actions.append(action["action"])
                if action["action"]=="finish":break
            except (ValueError,RuntimeError,subprocess.CalledProcessError) as exc:
                detail=(exc.stderr or str(exc)) if isinstance(exc,subprocess.CalledProcessError) else str(exc)
                observation={"status":"rejected_action","error":detail};rejections.append(observation)
    except Exception as exc:error=type(exc).__name__+": "+str(exc)
    finally:adapter.finish(session)
    passed=(accepted_actions==["read_source"] if not args.loop else
        accepted_actions==["read_source","propose_patch","request_evaluation","finish"] and bool(physical) and
        physical[-1]["physical_result"]["assessment"]["S2"] and physical[-1]["analysis_complete"])
    summary={"phase":"development_local_policy_calibration","variant":args.variant,"passed":passed and error is None,
        "actions":actions,"accepted_actions":accepted_actions,"rejections":rejections,"physical_evaluation_runs":[x["run_directory"] for x in physical],"error":error,
        "output":str(out),"session_id":session["session_id"],"usage":session["usage"],"formal_trials":0,"training_examples":0}
    (out/"calibration.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)
    if not summary["passed"]:raise SystemExit(2)


def physical(source):
    """Fixed trusted MOS evaluator; all inference outputs remain untrusted."""
    import shutil
    from src.candidate_executor import CandidateExecutor
    from src.spice_validation import validate_analysis
    from scripts.executor_smoke import EVALUATOR
    work=ROOT/"runs/development/local_policy_physical_inputs"/str(uuid.uuid4())
    trusted=work/"trusted";library=work/"library";trusted.mkdir(parents=True);library.mkdir()
    old='artifacts["spice"][corner]={"data":corner+"/op.dat","log":corner+"/ngspice.log"}'
    new='artifacts["spice"][corner]={"analyses":{"OP":{"data":corner+"/op.dat","log":corner+"/ngspice.log","returncode":sim.returncode}}}'
    if old not in EVALUATOR:raise ValueError("Trusted evaluator artifact interface changed")
    (trusted/"evaluate.py").write_text(EVALUATOR.replace(old,new))
    (trusted/"reference.spice").write_text(".subckt device4 D G S B\nX1 D G S B sky130_fd_pr__nfet_01v8 l=.5 w=3\nX2 D G S B sky130_fd_pr__nfet_01v8 l=.5 w=3\n.ends device4\n")
    contract={"task_id":"development_local_policy_mos","configuration_id":"anchor","reference_id":"independent_two_finger_nmos_3um_0p5um",
        "required_corners":["tt","ss","ff"],"specifications":[{"name":"drain_current","unit":"A","min":10e-6,"max":300e-6}],
        "analysis_contracts":{"OP":{"kind":"op","columns":4,"expected_rows":1}}}
    (trusted/"contract.json").write_text(json.dumps(contract,indent=2)+"\n")
    for name in ["physical_drc.py","report_parsers.py","measurement.py"]:
        path=trusted/"src"/name;path.parent.mkdir(exist_ok=True);shutil.copyfile(ROOT/"src"/name,path)
    (trusted/"src/__init__.py").write_text("")
    shutil.copyfile(ROOT/"runs/phase0/phase0_20261018T230848281073Z_device_full_flow/device4.gds",library/"device4.gds")
    executor=CandidateExecutor(ROOT/"runtime/GLdev",ROOT/"runs/development/local_policy_physical",ROOT/"runtime/magic-8.3.685",timeout=300)
    result=executor.execute(source_dir=source,source_paths=["generator.py"],entrypoint="generator.py",representation="G1",
        configuration={"width":3,"length":.5,"fingers":2},trusted_dir=trusted,
        trusted_paths=["evaluate.py","reference.spice","contract.json","src/__init__.py","src/physical_drc.py","src/report_parsers.py","src/measurement.py"],
        library_dir=library,library_paths=["device4.gds"],fidelity="pex_spice",context={"phase":"development_local_policy_calibration",
            "configuration_id":"anchor","source_role":"engineering_interface_calibration","pdk_revision":"0fe599b2afb6708d281543108caf8310912f54af"})
    complete=False
    if result.get("physical_result"):
        validations={};evidence=Path(result["run_directory"])/"evidence"
        for corner in contract["required_corners"]:
            record=result["physical_result"]["artifacts"]["spice"].get(corner,{}).get("analyses",{}).get("OP",{})
            if record:
                validations[corner]=validate_analysis(evidence/record["data"],evidence/record["log"],contract["analysis_contracts"]["OP"],returncode=record["returncode"])
        complete=len(validations)==3 and all(v["complete"] for v in validations.values())
        result["physical_result"]["analysis_validation"]=validations
        if not complete:result["physical_result"]["assessment"]["S2"]=False
        (evidence/"analysis_validation.json").write_text(json.dumps(validations,indent=2)+"\n")
    result["analysis_complete"]=complete
    print(json.dumps(result,indent=2),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",type=Path,default=ROOT)
    p.add_argument("--variant",choices=["T0","development_SFT_calibration"],default="T0")
    p.add_argument("--loop",action="store_true");p.add_argument("--physical-source",type=Path)
    a=p.parse_args()
    if a.physical_source:physical(a.physical_source)
    else:run(a)
