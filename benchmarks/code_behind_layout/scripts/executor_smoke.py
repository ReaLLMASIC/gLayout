#!/usr/bin/env python3
"""Development-only real container boundary calibration on a known SKY130 MOS.

Run on the authorized execution host. This is not a formal task or training
example. The PCell is an explicit, allowed fixture; the independent reference and
physical evaluator are available only to the second container.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.candidate_executor import CandidateExecutor


CANDIDATE = r'''import argparse, importlib, json, os, pathlib, shutil, socket
import gdstk, numpy
p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()
checks={"generic_geometry":hasattr(gdstk,"rectangle") and hasattr(numpy,"array")}
for module in ["glayout","glayout.cells.composite.opamp.opamp","gdsfactory","pydantic","scipy"]:
    try: importlib.import_module(module); checks["import:"+module]=False
    except ImportError: checks["import:"+module]=True
for name in ["/trusted/reference.spice","/trusted/hidden_canary.txt","/work/STATE.json",
             "/srv/eda/designs/gLayout/src/glayout/cells/composite/opamp/opamp.py",
             "/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc"]:
    try: pathlib.Path(name).read_bytes();checks["read:"+name]=False
    except (OSError,PermissionError): checks["read:"+name]=True
for name in ["/source/generator.py","/library/device4.gds","/telemetry/resource_usage.json"]:
    try:
        with open(name,"ab") as f:f.write(b"tamper")
        checks["write:"+name]=False
    except (OSError,PermissionError): checks["write:"+name]=True
try:
    with socket.create_connection(("1.1.1.1",443),timeout=.3):pass
    checks["network"]=False
except OSError:checks["network"]=True
assert all(checks.values()),checks
print(json.dumps({"boundary_checks":checks}),flush=True)
shutil.copyfile("/library/device4.gds",a.output)
'''


EVALUATOR = r'''import argparse,json,math,pathlib,re,subprocess
import gdstk
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
from src.measurement import assess
p=argparse.ArgumentParser();p.add_argument("--gds");p.add_argument("--output");p.add_argument("--fidelity");a=p.parse_args()
out=pathlib.Path(a.output);out.mkdir(exist_ok=True)
gds=pathlib.Path(a.gds)
top,=gdstk.read_gds(gds).top_level()
assert top.name=="device4"
drc=check_gds(gds,out/"drc",timeout=120)
(out/"drc/metadata.json").write_text(json.dumps(drc,indent=2)+"\n")
def magic(tcl,stem):
    (out/(stem+".tcl")).write_text(tcl)
    with (out/(stem+".log")).open("w") as log:
        r=subprocess.run(["magic","-rcfile","/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc","-noconsole","-dnull"],
            input=tcl,text=True,stdout=log,stderr=subprocess.STDOUT,cwd=out,timeout=120)
    assert r.returncode==0
magic("\n".join(["drc off","gds read {"+str(gds)+"}","load device4","select top cell",
    "flatten device4_lvs","load device4_lvs","select top cell","extract all","ext2spice lvs",
    "ext2spice -o extracted_lvs.spice","puts stdout EXTRACTION_COMPLETE","quit -noprompt",""]),"lvs_extract")
with (out/"netgen.log").open("w") as log:
    n=subprocess.run(["netgen","-batch","lvs",str(out/"extracted_lvs.spice")+" device4_lvs",
      "/trusted/reference.spice device4","/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",str(out/"lvs.rpt")],
      stdout=log,stderr=subprocess.STDOUT,timeout=120)
lvs=netgen_lvs_report((out/"lvs.rpt").read_text() if (out/"lvs.rpt").exists() else "")
contract=json.loads(pathlib.Path("/trusted/contract.json").read_text())
observation={k:contract[k] for k in ["task_id","configuration_id","reference_id"]}
observation.update(executed=True,gds_emitted=True,
    checks={"drc":drc["is_clean"],"lvs":lvs["is_clean"] and n.returncode==0,
      "devices":lvs["is_clean"],"ports":lvs["is_clean"],"intent":lvs["is_clean"]},corners={})
artifacts={"drc":{"report":"drc/direct_drc.rpt","metadata":"drc/metadata.json"},
    "lvs":{"report":"lvs.rpt"},"spice":{}}
if a.fidelity=="pex_spice":
    magic("\n".join(["drc off","gds read {"+str(gds)+"}","load device4","select top cell",
        "flatten device4_rc","load device4_rc","select top cell","extract do local","extract all",
        "feedback save extraction_feedback.tcl","ext2sim labels on","ext2sim",
        "extresist simplify off","extresist all","ext2spice lvs","ext2spice cthresh 0",
        "ext2spice extresist on","ext2spice -o device4_pex.spice","puts stdout EXTRACTION_COMPLETE",
        "quit -noprompt",""]),"rc_extract")
    net=out/"device4_pex.spice";text=net.read_text()
    inventory=rc_netlist_inventory(text,"device4_rc",["D","G","S","B"])
    (out/"rc_inventory.json").write_text(json.dumps(inventory,indent=2)+"\n")
    observation["pex"]={"executed":True,"kind":"physical_rc",
      "resistance_extracted":inventory["has_real_RC"],"capacitance_extracted":inventory["has_real_RC"]}
    artifacts["pex"]={"netlist":"device4_pex.spice","top_cell":"device4_rc","ports":["D","G","S","B"]}
    if inventory["has_real_RC"]:
        decl=next(line.split() for line in text.splitlines() if line.lower().startswith(".subckt "))
        bind={"D":"drain","G":"gate","S":"0","B":"0"}
        nodes=[bind[s.upper()] for s in decl[2:]]
        for corner in contract["required_corners"]:
            work=out/corner;work.mkdir()
            (work/".spiceinit").write_text("set ngbehavior=hsa\n")
            (work/"testbench.spice").write_text("\n".join(["Boundary calibration MOS OP",
                ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice "+corner,
                ".option scale=1e-6",".temp 27",".include "+str(net),"VGS gate 0 .9","VDS drain 0 .9",
                "XDUT "+" ".join(nodes)+" "+decl[1],".control","op","set wr_vecnames","set wr_singlescale",
                "wrdata op.dat v(gate) v(drain) i(vds)","quit",".endc",".end",""]))
            with (work/"console.log").open("w") as log:
                sim=subprocess.run(["ngspice","-b","-o","ngspice.log","testbench.spice"],cwd=work,
                    stdout=log,stderr=subprocess.STDOUT,timeout=60)
            values=list(map(float,(work/"op.dat").read_text().splitlines()[-1].split()))
            valid=len(values)==4 and all(map(math.isfinite,values)) and values[3]<0
            observation["corners"][corner]={"converged":sim.returncode==0 and valid,
                "operating_point_valid":valid and abs(values[1]-.9)<1e-6 and abs(values[2]-.9)<1e-6,
                "metrics":{"drain_current":{"value":-values[3],"unit":"A"}}}
            artifacts["spice"][corner]={"data":corner+"/op.dat","log":corner+"/ngspice.log"}
result={"contract":contract,"observation":observation,"artifacts":artifacts,"assessment":assess(contract,observation)}
(out/"validation.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result,indent=2),flush=True)
raise SystemExit(0 if result["assessment"]["S1"] and (a.fidelity=="basic" or result["assessment"]["S2"]) else 2)
'''


def gpt_loop(root):
    """Four actual model decisions, with only visible source and physical feedback."""
    from src.candidate_executor import VisibleActionGateway
    from src.model_adapter import GptDecisionAdapter
    work=root/"runs/development/gpt_executor"/str(uuid.uuid4())
    source=work/"source";source.mkdir(parents=True)
    (source/"generator.py").write_text('''import argparse, shutil
p=argparse.ArgumentParser()
p.add_argument("--configuration")
p.add_argument("--output")
a=p.parse_args()
shutil.copyfile("/library/device_typo.gds",a.output)
''')
    packet={"task_id":"development_visible_source_physical_loop", "goal":
        "Complete this development gateway calibration in four decisions: first read generator.py, "
        "then propose a minimal source patch repairing its API path, then request pex_spice for anchor, "
        "then finish after reading actual physical feedback. The allowed read-only PCell path is "
        "/library/device4.gds. Preserve the declared generator CLI. This injected path defect is a "
        "development calibration, excluded from formal experiments and training.",
        "contract":{"scope":"single MOS development interface calibration",
            "required_corners":["tt","ss","ff"],"required_checks":["full DRC","LVS","positive RC","finite OP"],
            "drain_current_A":{"min":10e-6,"max":300e-6}},
        "allowed_paths":["generator.py"], "visible_sources":{"generator.py":"Use read_source for the actual contents"},
        "documents":{"generator_api":"python generator.py --configuration PATH --output /output/candidate.gds; emit only this GDS"},
        "visible_configurations":["anchor"],"budget":{"decisions":4}}
    config=json.loads((root/"configs/models/gpt.json").read_text())
    adapter=GptDecisionAdapter(work/"decisions",executable=shutil.which(os.environ.get("GPT_CLI", "gpt-cli")) or
        os.environ.get("GPT_CLI", "gpt-cli"))
    session=adapter.start(packet,config)
    ssh=["ssh","-i","~/.ssh/cbl_server_key","-o","BatchMode=yes",
         "-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=12","cbl-server"]
    remote_root="/srv/code-behind-layout"
    remote_source=remote_root+"/runs/development/gpt_executor/"+session["session_id"]+"/source"
    evaluations=[]
    def evaluate(name,fidelity):
        assert name=="anchor" and fidelity=="pex_spice"
        subprocess.run(ssh+["mkdir -p "+shlex.quote(remote_source)],check=True,capture_output=True,text=True)
        subprocess.run(["scp"]+ssh[1:-1]+[str(source/"generator.py"),
            "cbl-server:"+remote_source+"/generator.py"],check=True,capture_output=True,text=True)
        command=" ".join(map(shlex.quote,["python3",remote_root+"/scripts/executor_smoke.py",
            "--fixture",remote_root+"/runs/phase0/phase0_20261018T230848281073Z_device_full_flow/device4.gds",
            "--candidate-source-dir",remote_source]))
        result=subprocess.run(ssh+[command],text=True,capture_output=True,timeout=360)
        (work/"physical_backend_stdout.json").write_text(result.stdout)
        (work/"physical_backend_stderr.log").write_text(result.stderr)
        record=json.loads(result.stdout)
        evaluations.append(record)
        # Only public visible-point physical results return to the policy.
        return {"status":record["status"],"physical_result":record["physical_result"]}
    gateway=VisibleActionGateway(packet,source,evaluate)
    observation={"status":"begin","next":"read_source"};actions=[]
    try:
        for _ in range(4):
            action=adapter.step(session,observation);actions.append(action["action"])
            observation=gateway.dispatch(action)
            if action["action"]=="finish":break
        physical_ok=bool(evaluations and evaluations[-1]["physical_result"] and
            evaluations[-1]["physical_result"]["assessment"]["S2"])
        summary={"phase":"development_boundary_calibration","model_session_id":session["session_id"],
            "actions":actions,"physical_evaluation_runs":[x["run_directory"] for x in evaluations],
            "passed":actions==["read_source","propose_patch","request_evaluation","finish"] and physical_ok,
            "formal_trials":0,"training_examples":0,"output":str(work)}
        (work/"calibration.json").write_text(json.dumps(summary,indent=2)+"\n")
        print(json.dumps(summary,indent=2),flush=True)
    finally:
        adapter.finish(session)
    if not summary["passed"]:raise SystemExit(2)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture",type=Path)
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument("--candidate-source-dir",type=Path,help="Run one development visible evaluation for the local model gateway")
    p.add_argument("--gpt-loop",action="store_true",help="Run the authorized bounded development GPT loop from the local policy host")
    a=p.parse_args();root=a.root.resolve()
    if a.gpt_loop:
        gpt_loop(root);return
    if a.fixture is None:p.error("--fixture is required for execution-host physical calibration")
    bundle=root/"runs/development/executor_smoke_bundle"
    source=bundle/"source";library=bundle/"library";trusted=bundle/"trusted"
    for directory in [source,library,trusted]:directory.mkdir(parents=True,exist_ok=True)
    (source/"generator.py").write_text(CANDIDATE)
    shutil.copyfile(a.fixture,library/"device4.gds")
    (trusted/"evaluate.py").write_text(EVALUATOR)
    (trusted/"reference.spice").write_text("\n".join([
        ".subckt device4 D G S B", "XMAIN1 D G S B sky130_fd_pr__nfet_01v8 l=0.5 w=3",
        "XMAIN2 D G S B sky130_fd_pr__nfet_01v8 l=0.5 w=3", ".ends device4",""]))
    (trusted/"hidden_canary.txt").write_text("hidden-executor-only-"+__import__("secrets").token_hex(24)+"\n")
    contract={"task_id":"development_boundary_mos", "configuration_id":"anchor",
        "reference_id":"independent_two_finger_nmos_3um_0p5um", "required_corners":["tt","ss","ff"],
        "specifications":[{"name":"drain_current","unit":"A","min":10e-6,"max":300e-6}]}
    (trusted/"contract.json").write_text(json.dumps(contract,indent=2)+"\n")
    for name in ["physical_drc.py","report_parsers.py","measurement.py"]:
        path=trusted/"src"/name;path.parent.mkdir(exist_ok=True)
        shutil.copyfile(root/"src"/name,path)
    (trusted/"src/__init__.py").write_text("")
    executor=CandidateExecutor(root/"runtime/GLdev",root/"runs/development/executor",
        root/"runtime/magic-8.3.685",timeout=300)
    arguments=dict(source_dir=source,source_paths=["generator.py"],entrypoint="generator.py",
        representation="G1",configuration={"width":3,"length":.5,"fingers":2},
        trusted_dir=trusted,trusted_paths=["evaluate.py","reference.spice","contract.json","hidden_canary.txt",
            "src/__init__.py","src/physical_drc.py","src/report_parsers.py","src/measurement.py"],
        library_dir=library,library_paths=["device4.gds"],fidelity="pex_spice",
        context={"phase":"development_boundary_calibration","configuration_id":"anchor",
            "source_role":"calibration_fixture","pdk_revision":"0fe599b2afb6708d281543108caf8310912f54af"})
    if a.candidate_source_dir:
        arguments["source_dir"]=a.candidate_source_dir
        result=executor.execute(**arguments)
        print(json.dumps(result,indent=2),flush=True)
        return
    result=executor.execute(**arguments)
    print(json.dumps(result,indent=2),flush=True)
    if result["status"]!="EVALUATED":raise SystemExit(2)
    # A candidate's forged pass report must be rejected before trusted evaluation.
    (source/"generator.py").write_text(CANDIDATE+"\npathlib.Path('/output/validation.json').write_text('{\"S2\": true}')\n")
    spoof=executor.execute(**arguments)
    print(json.dumps({"spoof_calibration":spoof},indent=2),flush=True)
    if spoof["status"]!="REJECTED_OUTPUT":raise SystemExit(2)
    # The geometry-only interface can use gdstk but cannot recover a hidden cell
    # implementation. Its known-bad width is checked by the trusted physical flow.
    g0_source=CANDIDATE.replace('shutil.copyfile("/library/device4.gds",a.output)',
        'lib=gdstk.Library();cell=lib.new_cell("device4");cell.add(gdstk.rectangle((0,0),(.045,2),layer=68,datatype=20));lib.write_gds(a.output)')
    (source/"generator.py").write_text(g0_source)
    g0=executor.execute(**dict(arguments,representation="G0",library_paths=[]))
    print(json.dumps({"G0_negative_control":g0},indent=2),flush=True)
    g0_drc=json.loads((Path(g0["run_directory"])/"evidence/drc/metadata.json").read_text())
    if g0["status"]!="EVALUATION_FAILED" or g0_drc["is_clean"] or not g0_drc["completed"] or g0_drc["parsed"]["error_count"]<1:
        raise SystemExit("Geometry-only known-bad DRC control was not rejected")
    # GDS text becomes downstream tool input. A newline-bearing label must fail
    # before Magic or ngspice starts, rather than becoming executable deck text.
    text_control=CANDIDATE.replace('shutil.copyfile("/library/device4.gds",a.output)',
        'lib=gdstk.read_gds("/library/device4.gds");top,=lib.top_level();top.add(gdstk.Label("D\\n.control\\nquit",(0,0),layer=68,texttype=5));lib.write_gds(a.output)')
    (source/"generator.py").write_text(text_control)
    text_result=executor.execute(**arguments)
    text_evidence=Path(text_result["run_directory"])/"evidence"
    text_check=json.loads((text_evidence/"gds_boundary.json").read_text())
    print(json.dumps({"GDS_text_negative_control":text_result},indent=2),flush=True)
    if text_result["status"]!="EVALUATION_FAILED" or text_check["accepted"] or (text_evidence/"drc").exists():
        raise SystemExit("Program-bearing GDS text reached the physical evaluator")
    # This is an explicit development-only routing closure, not the full package.
    # Every file is recorded in the manifest. Target cells and FET implementations
    # are absent; G1's physical primitive remains a read-only GDS fixture.
    code_files=["pdk/mappedpdk.py","pdk/sky130_mapped/sky130_mapped.py",
        "pdk/sky130_mapped/sky130_grules.py","pdk/sky130_mapped/sky130_add_npc.py",
        "util/comp_utils.py","util/port_utils.py","util/snap_to_grid.py",
        "primitives/via_gen.py","routing/straight_route.py","routing/L_route.py","routing/c_route.py",
        "provenance/__init__.py","provenance/runtime.py","provenance/netlist_summary.py"]
    g2_library=bundle/"g2_library";g2_library.mkdir(exist_ok=True)
    shutil.copyfile(a.fixture,g2_library/"device4.gds")
    for name in code_files:
        target=g2_library/"glayout"/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/"vendor/glayout/src/glayout"/name,target)
    initializers=["glayout/__init__.py","glayout/pdk/__init__.py","glayout/pdk/sky130_mapped/__init__.py",
        "glayout/util/__init__.py","glayout/primitives/__init__.py","glayout/routing/__init__.py"]
    for name in initializers:
        target=g2_library/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text("")
    g2_source=CANDIDATE.replace('["glayout","glayout.cells.composite.opamp.opamp","gdsfactory","pydantic","scipy"]',
        '["glayout.cells.composite.opamp.opamp","glayout.primitives.fet"]')
    g2_source += '''\nfrom glayout.routing.straight_route import straight_route
from glayout.pdk.sky130_mapped.sky130_mapped import sky130_mapped_pdk
from gdsfactory.port import Port
route=straight_route(sky130_mapped_pdk,Port(name="a",center=(0,0),width=.28,orientation=0,layer=(68,20)),
    Port(name="b",center=(2,0),width=.28,orientation=180,layer=(68,20)),width=.28)
assert len(route.polygons)>0
print(json.dumps({"declared_routing_function_executed":True}),flush=True)
'''
    (source/"generator.py").write_text(g2_source)
    g2=executor.execute(**dict(arguments,representation="G2",library_dir=g2_library,
        library_paths=["device4.gds"]+initializers+["glayout/"+name for name in code_files]))
    print(json.dumps({"G2_cropped_routing":g2},indent=2),flush=True)
    if g2["status"]!="EVALUATED":raise SystemExit(2)
    summary={"phase":"development_boundary_calibration","physical":result,"spoof":spoof,
        "G0_negative_control":g0,"GDS_text_negative_control":text_result,"G2_cropped_routing":g2,
        "passed":True,"formal_trials":0,"training_examples":0}
    (bundle/"calibration.json").write_text(json.dumps(summary,indent=2)+"\n")


if __name__=="__main__":main()
