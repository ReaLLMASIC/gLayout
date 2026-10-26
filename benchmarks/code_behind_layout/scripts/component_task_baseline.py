#!/usr/bin/env python3
"""Private development full-domain baseline from actual pre-generated task GDS.

First calibrate one mirror anchor, then resume remaining points. No policy or
formal training consumes this private qualification run. Only aggregate counts
and costs are eligible for public export.
"""
import argparse
import ast
from concurrent.futures import FIRST_COMPLETED,ThreadPoolExecutor,wait
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.candidate_executor import CandidateExecutor
from src.domain_runner import inspect_point,source_contents
from scripts.materialize_tasks import TARGETS

COPY_SOURCE='''import argparse,shutil
p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()
shutil.copyfile("/source/input.gds",a.output)
'''


def frozen_post_bench(kind):
    script=ROOT/"scripts"/({"pair":"pair","tg":"tg","follower":"follower"}[kind]+"_characterization.py")
    source=script.read_text();tree=ast.parse(source)
    node=next(node for node in tree.body if isinstance(node,ast.For) and isinstance(node.target,ast.Tuple) and
        [item.id for item in node.target.elts if isinstance(item,ast.Name)]==["fidelity","netlist","cell"])
    loop=ast.get_source_segment(source,node).splitlines(keepends=True)
    loop[0]='for fidelity, netlist, cell in [("post_rc", pex, "'+TARGETS[kind]["top"]+'_rc")]:\n'
    bench="".join(loop)+"\n";compile(bench,"frozen_post_bench.py","exec")
    return source,bench


class Baseline:
    def __init__(self,directory):
        self.directory=Path(directory).resolve();self.lock=threading.Lock()
        self.task=json.loads((self.directory/"private/task.json").read_text())
        self.state=json.loads((self.directory/"private/state.json").read_text())
        self.executor=CandidateExecutor(ROOT/"runtime/GLdev",self.directory/"private/physical",ROOT/"runtime/magic-8.3.685",timeout=720)

    @classmethod
    def create(cls,preparation,kind):
        if kind not in TARGETS:raise ValueError("Unknown materialized component target")
        private=Path(preparation)/"private"/kind
        task=json.loads((private/"task.json").read_text())
        if task["formal_admission"] or len(task["configurations"])!=25:raise ValueError("Expected an unfrozen complete development task")
        directory=ROOT/"runs/development/component_baselines"/(kind+"_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ_")+uuid.uuid4().hex[:8])
        directory.mkdir(parents=True,mode=0o700);(directory/"private").mkdir();(directory/"public").mkdir()
        references=directory/"private/references";references.mkdir();inputs=directory/"private/inputs";inputs.mkdir()
        trusted=directory/"private/trusted_common";trusted.mkdir();(trusted/"src").mkdir()
        if kind=="mirror":shutil.copyfile(ROOT/"scripts/mirror_task_evaluator.py",trusted/"evaluate.py")
        else:
            shutil.copyfile(ROOT/"scripts/component_task_evaluator.py",trusted/"evaluate.py")
            original,bench=frozen_post_bench(kind)
            (trusted/"characterization_original.py").write_text(original);(trusted/"bench.py").write_text(bench)
            (trusted/"bench.json").write_text(json.dumps({"kind":kind,"top":TARGETS[kind]["top"],"ports":TARGETS[kind]["ports"],"bench_transform":"Only select the original post_rc branch; loop body, stimuli, metrics, solver settings and analysis contracts preserved verbatim"},indent=2)+"\n")
        (trusted/"src/__init__.py").write_text("")
        for name in ("physical_drc.py","report_parsers.py","measurement.py","spice_validation.py"):
            shutil.copyfile(ROOT/"src"/name,trusted/"src"/name)
        records=[(path,json.loads(path.read_text())) for path in sorted(private.glob("preflight_attempt_*/generation/generation.json"))]
        for point in task["configurations"]:
            ident=point["configuration_id"]
            source=next((path.parent/(ident+".gds") for path,record in reversed(records)
                if any(row["configuration_id"]==ident and row["generation_passed"] for row in record["rows"])),None)
            if source is None:raise ValueError("A task point has no actual generated GDS: "+ident)
            shutil.copyfile(source,inputs/(ident+".gds"));shutil.copyfile(point["reference_file"],references/(ident+".spice"))
            point["generation_gds_origin"]=str(source);point["reference_file"]=str(references/(ident+".spice"))
        task["preparation_origin"]=str(Path(preparation).resolve())
        (directory/"private/task.json").write_text(json.dumps(task,indent=2)+"\n")
        state={"phase":"development_component_domain_baseline","created_at_utc":datetime.now(timezone.utc).isoformat(),"status":"CREATED","points":{},"formal_trials":0,"training_examples":0}
        (directory/"private/state.json").write_text(json.dumps(state,indent=2)+"\n")
        for p in inputs.iterdir():p.chmod(0o444)
        return cls(directory)

    def save(self):
        (self.directory/"private/state.json").write_text(json.dumps(self.state,indent=2)+"\n")
        summary=self.summary()
        (self.directory/"public/summary.json").write_text(json.dumps(summary,indent=2)+"\n")

    def summary(self):
        records=list(self.state["points"].values());complete=len(records)==25 and all(row.get("point_evaluation_complete") for row in records)
        wall=sum(row["cost"]["stage_wall_seconds"] for row in records)
        cpu=sum(row["cost"]["waited_child_CPU_seconds"] for row in records)
        groups={}
        for role in ("anchor","development","hidden"):
            declared=[p for p in self.task["configurations"] if p["role"]==role]
            got=[self.state["points"][p["configuration_id"]] for p in declared if p["configuration_id"] in self.state["points"]]
            groups[role]={"declared":len(declared),"evaluated":len(got),"S0":sum(r["S0"] for r in got),"S1":sum(r["S1"] for r in got),"S2":sum(r["S2"] for r in got),"unknown_or_infrastructure":sum(not r["point_evaluation_complete"] for r in got)}
        return {"phase":self.state["phase"],"directory":str(self.directory),"status":self.state["status"],"groups":groups,"complete_domain_evaluation":complete,
            "stage_wall_seconds":wall,"waited_child_CPU_seconds":cpu,"missing_CPU_records":sum(r["cost"]["missing_CPU_records"] for r in records),
            "source_generation_charged_separately_in":"results/derived/component_task_materialization.json","physical_calls":len(records),"formal_trials":0,"training_examples":0,"hidden_details_exported":False}

    def evaluate(self,point):
        ident=point["configuration_id"];work=self.directory/"private/point_inputs"/ident;work.mkdir(parents=True)
        source=work/"source";source.mkdir();(source/"generator.py").write_text(COPY_SOURCE)
        shutil.copyfile(self.directory/"private/inputs"/(ident+".gds"),source/"input.gds")
        trusted=work/"trusted";shutil.copytree(self.directory/"private/trusted_common",trusted)
        shutil.copyfile(point["reference_file"],trusted/"reference.spice")
        (trusted/"contract.json").write_text(json.dumps(point["contract"],indent=2)+"\n")
        files=sorted(str(p.relative_to(trusted)) for p in trusted.rglob("*") if p.is_file())
        context={"source_role":"trusted_evaluator_control","initial_state_id":"unmodified_materialized_source","parent_lineage":self.task["parent_lineage"],
            "configuration_id":ident,"reference_id":point["reference_id"],"pdk_revision":self.task["pdk_revision"],"candidate_id":"baseline_"+ident,
            "source_generation_origin":point["generation_gds_origin"],"preparation_origin":self.task["preparation_origin"],"GDS_reuse":"actual pre-generated initial-source GDS; generation cost accounted separately"}
        result=self.executor.execute(source_dir=source,source_paths=["generator.py","input.gds"],entrypoint="generator.py",representation="G0",configuration=point["parameters"],
            trusted_dir=trusted,trusted_paths=files,fidelity="pex_spice",context=context,phase="development_component_domain_baseline",generation_timeout_seconds=30,evaluator_timeout_seconds=720)
        run=Path(result["run_directory"]);manifest=json.loads((run/"manifest.json").read_text())
        try:
            if (run/"accepted/candidate.gds").read_bytes()!=(self.directory/"private/inputs"/(ident+".gds")).read_bytes():raise ValueError("GDS handoff changed the baseline bytes")
            checked=inspect_point(result,point,source_contents(source,["generator.py","input.gds"],binary=True),point["parameters"],gold_control_check=False)
        except (OSError,KeyError,TypeError,ValueError) as exc:
            checked={"S0":False,"S1":False,"S2":False,"execution_integrity":"incomplete","failure_class":"unknown","reason":type(exc).__name__+": "+str(exc),"run_directory":str(run)}
        complete=checked["execution_integrity"]=="valid" and checked["failure_class"] in (None,"candidate")
        objective=None
        if checked["S2"]:
            observation=manifest["physical_result"]["observation"];definition=point["contract"]["objective"]
            values=[observation["corners"][c]["metrics"][definition["metric"]]["value"] for c in point["contract"]["required_corners"]]
            objective=max(values) if definition["direction"]=="min" else min(values)
        cost={"stage_wall_seconds":0.,"waited_child_CPU_seconds":0.,"missing_CPU_records":0}
        for stage in ("candidate","trusted"):
            if stage not in manifest:continue
            cost["stage_wall_seconds"]+=manifest[stage]["wall_seconds"]
            path=run/(stage+"_stage/resource_usage.json")
            if path.is_file():
                usage=json.loads(path.read_text());cost["waited_child_CPU_seconds"]+=usage["child_user_cpu_seconds"]+usage["child_system_cpu_seconds"]
            else:cost["missing_CPU_records"]+=1
        record={**checked,"configuration_id":ident,"role":point["role"],"point_evaluation_complete":complete,"objective":objective,"cost":cost}
        with self.lock:
            self.state["points"][ident]=record
            if not complete:self.state["status"]="PAUSED_UNKNOWN_OR_INFRASTRUCTURE"
            self.save()
        print(json.dumps({"completed_point":ident,"S2":record["S2"],"point_complete":complete,"run_directory":str(run),"stage_wall_seconds":cost["stage_wall_seconds"]}),flush=True)
        return record

    def run(self,mode,workers):
        if workers not in (1,2):raise ValueError("At most two 2CPU workers are configured")
        if self.state["status"]=="PAUSED_UNKNOWN_OR_INFRASTRUCTURE":raise ValueError("Qualification is paused; retain evidence and resolve the actual unknown/infrastructure condition")
        anchor=next(p for p in self.task["configurations"] if p["role"]=="anchor")
        if mode!="anchor" and not self.state["points"].get(anchor["configuration_id"],{}).get("point_evaluation_complete"):
            raise ValueError("An actual complete anchor must calibrate this adapter first")
        points=[anchor] if mode=="anchor" else self.task["configurations"]
        pending=[p for p in points if p["configuration_id"] not in self.state["points"]]
        self.state["status"]="RUNNING";self.save()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            active={}
            while pending or active:
                while pending and len(active)<workers and self.state["status"]!="PAUSED_UNKNOWN_OR_INFRASTRUCTURE":
                    point=pending.pop(0);active[pool.submit(self.evaluate,point)]=point
                if not active:break
                done,_=wait(active,return_when=FIRST_COMPLETED)
                for future in done:
                    future.result();del active[future]
                if self.state["status"]=="PAUSED_UNKNOWN_OR_INFRASTRUCTURE":pending=[]
        if self.state["status"]!="PAUSED_UNKNOWN_OR_INFRASTRUCTURE":self.state["status"]="COMPLETE" if len(self.state["points"])==25 else "ANCHOR_COMPLETE"
        self.save();print(json.dumps(self.summary(),indent=2),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--preparation",type=Path);p.add_argument("--resume",type=Path)
    p.add_argument("--kind",choices=list(TARGETS),default="mirror");p.add_argument("--mode",choices=["anchor","remaining"],default="anchor");p.add_argument("--workers",type=int,default=2);a=p.parse_args()
    if not a.resume and not a.preparation:p.error("--preparation or --resume is required")
    run=Baseline(a.resume) if a.resume else Baseline.create(a.preparation,a.kind)
    run.run(a.mode,a.workers)
