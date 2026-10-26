#!/usr/bin/env python3
"""Remote development-only 25-point MOS domain preparation/execution/reporting."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import random
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def prepare():
    import gdstk
    from gdsfactory.components.rectangle import rectangle
    from glayout import sky130
    from glayout.primitives.fet import nmos
    from glayout.util.comp_utils import align_comp_to_port
    out=Path.cwd()
    dimensions=[(w,l) for w in [2.,2.5,3.,3.5,4.] for l in [.4,.5,.6,.7,.8]]
    anchor=(3.,.5);dimensions.remove(anchor);random.SystemRandom().shuffle(dimensions)
    dimensions=[anchor]+dimensions
    points=[]
    for index,(width,length) in enumerate(dimensions):
        name="point_%02d"%index;directory=out/"pcells"/name;directory.mkdir(parents=True)
        c=nmos(sky130,width=width,length=length,fingers=2,with_dummy=False,with_tie=True,with_dnwell=False).copy()
        c=c.remove_layers([v for k,v in sky130.glayers.items() if k.endswith(("_label","_pin"))])
        c.name="device4"
        for label,port_name in {"D":"multiplier_0_drain_N","G":"multiplier_0_gate_W",
                "S":"multiplier_0_source_S","B":"tie_W_top_met_W"}.items():
            port=c.ports[port_name];glayer=sky130.layer_to_glayer(port.layer)
            pin=rectangle(size=(.2,.2),layer=sky130.get_glayer(glayer+"_pin"),centered=True).copy()
            pin.add_label(label,layer=sky130.get_glayer(glayer+"_label"))
            c.add(align_comp_to_port(pin,port,("c","c")))
        c=c.remove_layers([(64,44)],include_labels=True);c.name="device4"
        c.write_gds(directory/"cell.gds")
        top,=gdstk.read_gds(directory/"cell.gds").top_level()
        top.flatten();top.name="device4";lib=gdstk.Library();lib.add(top);lib.write_gds(directory/"cell.gds")
        points.append({"configuration_id":name,"role":"anchor" if index==0 else ("development" if index<9 else "hidden"),
            "parameters":{"width":width,"length":length,"fingers":2}})
    (out/"private_points.json").write_text(json.dumps(points,indent=2)+"\n")
    (out/"preparation_summary.json").write_text(json.dumps({"phase":"development_domain_pilot",
        "prepared_cells":25,"roles":{"anchor":1,"development":8,"hidden":16},
        "physical_domain_validation":"pending","formal_trials":0,"training_examples":0},indent=2)+"\n")
    print(json.dumps({"prepared_cells":25,"parameters_file":"private_points.json","formal_trials":0}),flush=True)


def task_bundle(preparation,root):
    from scripts.executor_smoke import EVALUATOR
    old='artifacts["spice"][corner]={"data":corner+"/op.dat","log":corner+"/ngspice.log"}'
    new='artifacts["spice"][corner]={"analyses":{"OP":{"data":corner+"/op.dat","log":corner+"/ngspice.log","returncode":sim.returncode}}}'
    if old not in EVALUATOR:raise ValueError("Trusted MOS evaluator interface changed; update the development adapter explicitly")
    files={"evaluate.py":EVALUATOR.replace(old,new),"src/__init__.py":""}
    for name in ["measurement.py","physical_drc.py","report_parsers.py"]:
        files["src/"+name]=(root/"src"/name).read_text()
    points=json.loads((preparation/"private_points.json").read_text())
    for point in points:
        width=point["parameters"]["width"];length=point["parameters"]["length"]
        reference="\n".join([".subckt device4 D G S B",
            f"XMAIN1 D G S B sky130_fd_pr__nfet_01v8 l={length:g} w={width:g}",
            f"XMAIN2 D G S B sky130_fd_pr__nfet_01v8 l={length:g} w={width:g}",".ends device4",""])
        point["reference_netlist"]=reference
        point["contract"]={"task_id":"development_25_point_mos","configuration_id":point["configuration_id"],
            "reference_id":f"two_finger_nmos_w{width:g}_l{length:g}","required_corners":["tt","ss","ff"],
            "specifications":[{"name":"drain_current","unit":"A","min":1e-6,"max":1e-3}],
            "objective":{"metric":"drain_current","direction":"max","corner_aggregation":"worst"},
            "analysis_contracts":{"OP":{"kind":"op","columns":4,"expected_rows":1}}}
    return {"phase":"development_domain_pilot","task_id":"development_25_point_mos",
        "parent_lineage":"development_mos_fixture_not_an_independent_OTA","pdk_revision":"0fe599b2afb6708d281543108caf8310912f54af",
        "source_paths":["generator.py"],"editable_paths":["generator.py"],"entrypoint":"generator.py","representation":"G1",
        "immutable_parameters":["width","length","fingers"],"tunable_layout_parameters":{},
        "trusted_evaluator_files":files,"configurations":points,"library_generation_run":str(preparation),
        "goal":"Development-only fixed-source domain orchestration; no method or training result"}


def run(preparation,root):
    from src.domain_runner import DevelopmentDomainRunner
    from src.candidate_executor import CandidateExecutor
    preparation=preparation.resolve();task=task_bundle(preparation,root)
    directory=root/"runs/development/domain_input"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    source=directory/"source";source.mkdir(parents=True)
    initial='''import argparse,shutil
p=argparse.ArgumentParser()
p.add_argument("--configuration");p.add_argument("--output")
a=p.parse_args()
shutil.copyfile("/library/missing.gds",a.output)
'''
    (source/"generator.py").write_text(initial)
    patch='''--- a/generator.py
+++ b/generator.py
@@ -5 +5 @@
-shutil.copyfile("/library/missing.gds",a.output)
+shutil.copyfile("/library/current.gds",a.output)
'''
    def point_inputs(point,parameters,out):
        trusted=out/"trusted";library=out/"library";trusted.mkdir();library.mkdir()
        files={**task["trusted_evaluator_files"],"reference.spice":point["reference_netlist"],
            "contract.json":json.dumps(point["contract"],indent=2)+"\n"}
        for name,content in files.items():
            path=trusted/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_text(content)
        shutil.copyfile(preparation/"pcells"/point["configuration_id"]/"cell.gds",library/"current.gds")
        return {"trusted_dir":trusted,"trusted_paths":list(files),"library_dir":library,"library_paths":["current.gds"]}
    executor=CandidateExecutor(root/"runtime/GLdev",root/"runs/development/domain_physical",root/"runtime/magic-8.3.685",timeout=300)
    runner=DevelopmentDomainRunner(task,root/"runs/development/domains",executor,point_inputs,workers=2)
    (runner.output/"public/task_packet.json").write_text(json.dumps(runner.visible_packet({"generator.py":initial}),indent=2)+"\n")
    runner.freeze(source,patch=patch)
    print(json.dumps({"domain_directory":str(runner.output),"phase":"development_domain_pilot","status":"VISIBLE_RUNNING"}),flush=True)
    visible=runner.evaluate_visible()
    print(json.dumps({"visible_completed":len(visible),"visible_S2":sum(r["S2"] for r in visible.values())}),flush=True)
    if runner.state["status"]=="PAUSED_INCOMPLETE_EVIDENCE":
        report=runner.report()
    else:
        report=runner.run_hidden()
    # A fresh runner object restores exact recorded state and source bytes. It
    # only reads the sealed hidden report; no hidden measurement is repeated.
    restored=DevelopmentDomainRunner.resume(runner.output,executor,point_inputs,workers=2)
    recovered=restored.report()
    if recovered!=report:raise ValueError("Fresh domain restoration changed recorded evidence")
    summary=public_summary(runner.output)
    print(json.dumps(summary,indent=2),flush=True)
    raise SystemExit(0 if summary["complete_domain_evaluation"] else 2)


def public_summary(directory):
    from src.domain_runner import DevelopmentDomainRunner
    report=DevelopmentDomainRunner.resume(directory,None,None).report()
    wall=cpu=0.;missing=0
    for point in report["point_records"].values():
        if "run_directory" not in point:continue
        run=Path(point["run_directory"])
        for stage in ["candidate","trusted"]:
            invocation=run/(stage+"_stage/invocation.json")
            if not invocation.exists():continue
            wall+=json.loads(invocation.read_text())["wall_seconds"]
            usage=run/(stage+"_stage/resource_usage.json")
            if usage.exists():
                r=json.loads(usage.read_text());cpu+=r["child_user_cpu_seconds"]+r["child_system_cpu_seconds"]
            else:missing+=1
    task=json.loads((directory/"private/task.json").read_text())
    preparation=Path(task["library_generation_run"])
    generation=json.loads((preparation/"resource_usage.json").read_text())
    generation_cpu=sum(generation[k] for k in ["self_user_cpu_seconds","self_system_cpu_seconds","children_user_cpu_seconds","children_system_cpu_seconds"])
    summary={k:report[k] for k in ["phase","mode","complete_domain_evaluation","strict_hidden_transfer","groups","regression","regression_reason","selection_calls","post_freeze_calls","hidden_calls","costs_by_stage","formal_trials","training_examples"]}
    summary.update(domain_directory=str(directory),physical_stage_wall_seconds_sum=wall,
        physical_waited_child_cpu_seconds_sum=cpu,physical_cpu_records_missing=missing,
        pcell_generation_wall_seconds=generation["wall_seconds"],pcell_generation_cpu_seconds=generation_cpu,
        interpretation="One development MOS parameter-domain plumbing pilot; not an independent-lineage or method result",
        cost_scope="Observed container-stage wall/waited-child CPU plus profiled PCell construction; host orchestration CPU is unmeasured")
    (directory/"public/summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode",choices=["prepare","run","report"],required=True)
    p.add_argument("--preparation",type=Path)
    p.add_argument("--directory",type=Path)
    p.add_argument("--root",type=Path,default=ROOT)
    a=p.parse_args()
    if a.mode=="prepare":prepare()
    elif a.mode=="run":
        if a.preparation is None:p.error("--preparation is required")
        run(a.preparation,a.root.resolve())
    else:
        if a.directory is None:p.error("--directory is required")
        print(json.dumps(public_summary(a.directory.resolve()),indent=2),flush=True)


if __name__=="__main__":main()
