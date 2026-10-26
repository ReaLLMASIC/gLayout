"""Development-only configuration domains on the separate execution host.

This module has no model client. A policy sees visible_packet/visible_feedback;
the complete domain and all hidden evidence remain in the backend run directory.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid

from src.candidate_executor import apply_source_patch, copy_declared_files
from src.measurement import assess, validate_contract
from src.report_parsers import magic_drc_report, netgen_lvs_report, rc_netlist_inventory
from src.spice_validation import validate_analysis


def validate_domain(task):
    if task.get("phase") != "development_domain_pilot":
        raise ValueError("This runner cannot start formal experiments or training")
    points=task.get("configurations",[])
    if {role:sum(p.get("role")==role for p in points) for role in ["anchor","development","hidden"]}!={"anchor":1,"development":8,"hidden":16} or len(points)!=25:
        raise ValueError("A development domain must declare one anchor, eight dev and sixteen hidden points")
    ids=[];parameters=[]
    for point in points:
        name=point.get("configuration_id","")
        if not re.fullmatch(r"[A-Za-z0-9_]+",name):
            raise ValueError("Configuration IDs must be simple identifiers")
        contract=point["contract"];validate_contract(contract)
        if contract["configuration_id"]!=name or contract["task_id"]!=task["task_id"]:
            raise ValueError("A point must bind its own task and circuit contract")
        if not isinstance(point.get("parameters"),dict) or not point["parameters"]:
            raise ValueError("Every point needs its own declared parameters")
        if not contract.get("analysis_contracts"):
            raise ValueError("Physical acceptance requires declared complete analyses")
        if not point.get("reference_netlist") or not task.get("trusted_evaluator_files"):
            raise ValueError("Each point needs an independent frozen reference and evaluator snapshot")
        ids.append(name);parameters.append(json.dumps(point["parameters"],sort_keys=True))
    if len(set(ids))!=25 or len(set(parameters))!=25:
        raise ValueError("Duplicate IDs or parameter points do not create a domain")
    tunable=task.get("tunable_layout_parameters",{})
    if set(tunable)&set(task.get("immutable_parameters",[])):
        raise ValueError("Circuit sizing cannot also be a layout-only search control")
    return task


def source_contents(directory, names, binary=False):
    directory=Path(directory).resolve();result={}
    for name in names:
        path=directory/name
        if Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory):
            raise ValueError("Source snapshots contain only declared ordinary files")
        result[name]=path.read_bytes() if binary else path.read_text()
    return result


def layout_override(task, values):
    bounds=task.get("tunable_layout_parameters",{})
    if not isinstance(values,dict) or not set(values).issubset(bounds):
        raise ValueError("Parameter baseline may change only declared layout controls")
    for key,value in values.items():
        rule=bounds[key]
        if type(value) not in (int,float) or not rule["min"]<=value<=rule["max"]:
            raise ValueError("Layout parameter exceeds its declared domain")
    return dict(values)


def _artifact(root,name):
    relative=Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Artifact must remain inside trusted evidence")
    path=root/relative
    if any((root/Path(*relative.parts[:i])).is_symlink() for i in range(1,len(relative.parts)+1)) or not path.is_file() or path.stat().st_size==0:
        raise ValueError("Required trusted artifact is missing, empty or a symlink: "+name)
    return path


def _analysis_path(root,name):
    """An incomplete simulator may legitimately have no data file yet."""
    relative=Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Analysis artifacts must stay inside trusted evidence")
    if any((root/Path(*relative.parts[:i])).is_symlink() for i in range(1,len(relative.parts)+1)):
        raise ValueError("Analysis artifacts cannot be symlinks")
    return root/relative


def inspect_gold_control(candidate_run,point,expected_configuration):
    """Resolve a backend-declared control, never a candidate supplied S2 flag."""
    declared=point.get("gold_control")
    if not declared:return {"status":"unavailable","run_directory":None}
    directory=declared.get("run_directory")
    result={"status":"invalid","run_directory":directory}
    try:
        current=Path(candidate_run);gold=Path(directory)
        candidate=json.loads(_artifact(current,"manifest.json").read_text())
        manifest=json.loads(_artifact(gold,"manifest.json").read_text())
        expected=point["contract"]
        context=manifest.get("context",{});candidate_context=candidate.get("context",{})
        if context.get("source_role")!="trusted_evaluator_control":
            if not (manifest.get("phase")=="formal_train" and context.get("source_role")=="formal_train" and
                    "trusted_evaluator_control" in context.get("evidence_roles",[])):
                raise ValueError("Control was not executed in the trusted gold role")
            original_names=set(point.get("frozen_source_files",[]))|set(point.get("lineage_editable_paths",point.get("editable_paths",[])))
            if not original_names or set(manifest["source_files"])!=original_names or not point.get("frozen_source_pack"):
                raise ValueError("A dual-role baseline must bind the complete original source capsule")
            if source_contents(gold/"source",manifest["source_files"],binary=True)!=source_contents(
                    point["frozen_source_pack"],manifest["source_files"],binary=True):
                raise ValueError("A mutated baseline cannot serve as the original gold control")
        for key,value in [("configuration_id",point["configuration_id"]),("reference_id",expected["reference_id"]),
                          ("pdk_revision",candidate_context.get("pdk_revision"))]:
            if not value or context.get(key)!=value:raise ValueError("Gold control binding differs: "+key)
        if json.loads(_artifact(gold,"configuration.json").read_text())!=expected_configuration:
            raise ValueError("Gold control uses another configuration")
        names=candidate["trusted_files"]
        if set(names)!=set(manifest["trusted_files"]) or source_contents(current/"trusted",names)!=source_contents(gold/"trusted",names):
            raise ValueError("Gold control uses another evaluator, contract or reference")
        def tools(record,stage):
            argv=record[stage]["argv"]
            mounts=[argv[i+1] for i,v in enumerate(argv[:-1]) if v=="-v" and
                    (":/headless/conda-env/miniconda3/envs/GLdev:ro" in argv[i+1] or ":/work/runtime/magic-8.3.685:ro" in argv[i+1])]
            return {"image":argv[argv.index("--entrypoint")+2],"runtime_mounts":mounts,
                    "path":[v for v in argv if v.startswith("PATH=")]}
        stage="trusted" if "trusted" in candidate else "candidate"
        if stage=="candidate":
            if candidate.get("representation")!=manifest.get("representation"):
                raise ValueError("Generation control used another declared candidate interface")
            if set(candidate["source_files"])!=set(manifest["source_files"]):
                raise ValueError("Generation control used another source capsule")
            for name in point.get("frozen_source_files",[]):
                if (current/"source"/name).read_bytes()!=(gold/"source"/name).read_bytes():
                    raise ValueError("Generation control changed a frozen source dependency")
            libraries=candidate.get("library_files",[])
            if set(libraries)!=set(manifest.get("library_files",[])) or source_contents(current/"library",libraries,binary=True)!=source_contents(gold/"library",libraries,binary=True):
                raise ValueError("Generation control used another frozen library")
        if tools(candidate,stage)!=tools(manifest,stage):raise ValueError("Gold control used another physical tool runtime")
        checked=inspect_point({"run_directory":str(gold)},point,source_contents(gold/"source",manifest["source_files"],binary=True),
                              expected_configuration,gold_control_check=False)
        complete=checked["execution_integrity"]=="valid" and checked["S1"] and bool(checked["analysis_validation"]) and all(
            r["complete"] for corner in checked["analysis_validation"].values() for r in corner.values())
        result.update(status="complete" if complete else "failed",reference_id=expected["reference_id"],
            configuration_id=point["configuration_id"],pdk_revision=context["pdk_revision"],
            execution_integrity=checked["execution_integrity"],analysis_validation=checked["analysis_validation"],reason=checked.get("reason"))
    except (KeyError,TypeError,ValueError,OSError) as exc:result["reason"]=str(exc)
    return result


def classify_analysis_failure(validations,raw_records,evidence,gold_control):
    """A known numerical failure needs a same-configuration working control."""
    numerical=[];environment=[]
    for corner,records in validations.items():
        for name,validation in records.items():
            if validation["complete"]:continue
            raw=raw_records[corner][name]
            log_path=_analysis_path(evidence,raw["log"])
            log=log_path.read_text(errors="replace") if log_path.exists() else ""
            if re.search(r"(?i)(command not found|error while loading shared libraries|cannot open shared object file)",log):
                environment.append(corner+":"+name)
            if ((raw.get("timeout") is True and raw.get("returncode") is None) or
                re.search(r"(?i)(no convergence|failed to converge|convergence failed|timestep too small|iteration limit|singular matrix)",log)):
                numerical.append(corner+":"+name)
    if environment or gold_control["status"]=="failed":
        return {"execution_integrity":"incomplete","failure_class":"infrastructure","numerical_failure_established":False,
                "reason":"The trusted tool environment or same-configuration gold control also failed"}
    if numerical and gold_control["status"]=="complete":
        return {"execution_integrity":"valid","failure_class":"candidate","numerical_failure_established":True,
                "failed_numerical_analyses":numerical,"reason":"Candidate numerical failure under a completed same-configuration gold control"}
    return {"execution_integrity":"incomplete","failure_class":"unknown","numerical_failure_established":False,
            "reason":"Incomplete analysis has no established numerical failure with a completed same-configuration gold control"}


def inspect_point(result,point,expected_source,expected_configuration,gold_control_check=True):
    """Read host-owned reports and required analysis coverage before assigning S2."""
    run=Path(result["run_directory"])
    manifest=json.loads(_artifact(run,"manifest.json").read_text())
    binary=not gold_control_check or bool(expected_source) and all(isinstance(v,bytes) for v in expected_source.values())
    if source_contents(run/"source",manifest["source_files"],binary=binary)!=expected_source:
        raise ValueError("Executed source differs from the fixed source snapshot")
    if json.loads(_artifact(run,"configuration.json").read_text())!=expected_configuration:
        raise ValueError("Executed parameters differ from this domain point")
    status=manifest["status"]
    common={"run_directory":str(run),"status":status,"S0":False,"S1":False,"S2":False,
            "execution_integrity":"valid","failure_class":None,"analysis_validation":{},"analysis_complete":False,
            "numerical_failure_established":False,
            "gold_control":inspect_gold_control(run,point,expected_configuration) if gold_control_check else {"status":"not_requested","run_directory":None}}
    candidate=manifest["candidate"]
    if candidate["container_state"].get("Running") is not False:
        raise ValueError("A candidate process is still alive")
    if status in ["CANDIDATE_FAILED","REJECTED_OUTPUT"]:
        if candidate["status"]=="TIMEOUT":
            return {**common,"failure_class":"candidate","reason":"candidate exceeded its declared generation time budget"}
        if candidate["container_state"].get("Error") or (not candidate.get("resource_usage_available") and not candidate["container_state"].get("OOMKilled")):
            return {**common,"execution_integrity":"incomplete","failure_class":"infrastructure",
                    "reason":"generation did not complete under a calibrated execution environment"}
        return {**common,"failure_class":"candidate","reason":"candidate generation or artifact contract failed"}
    boundary=run/"evidence/gds_boundary.json"
    if boundary.exists() and json.loads(boundary.read_text()).get("accepted") is False:
        parsed=json.loads(boundary.read_text()).get("gds_parse_complete") is True
        return {**common,"S0":parsed,"failure_class":"candidate",
                "reason":"GDS text violates the declared identifier interface" if parsed else "Candidate GDS cannot be parsed"}
    evidence=run/"evidence"
    provenance=json.loads(_artifact(evidence,"provenance.json").read_text())
    if provenance.get("producer")!="trusted_container" or provenance.get("candidate_container_stopped") is not True:
        raise ValueError("Trusted physical provenance is missing")
    if manifest.get("context",{}).get("configuration_id")!=point["configuration_id"] or provenance.get("context")!=manifest.get("context"):
        raise ValueError("Trusted physical evidence belongs to another configuration")
    record=json.loads(_artifact(evidence,"validation.json").read_text())
    if record["contract"]!=point["contract"]:
        raise ValueError("The evaluator changed this point's independent contract")
    observation=record["observation"];artifacts=record["artifacts"]
    tiers=assess(point["contract"],observation)
    if record["assessment"]!=tiers:
        raise ValueError("Trusted summary contradicts contract assessment")
    drc=artifacts["drc"]
    metadata=json.loads(_artifact(evidence,drc["metadata"]).read_text())
    drc_clean=metadata.get("completed") is True and metadata.get("style")=="drc(full)" and magic_drc_report(_artifact(evidence,drc["report"]).read_text())["is_clean"]
    if metadata.get("completed") is not True:
        return {**common,"execution_integrity":"incomplete","failure_class":"infrastructure","reason":"DRC did not finish"}
    if observation["checks"]["drc"]!=drc_clean:
        raise ValueError("DRC observation contradicts completed full-rule evidence")
    if not drc_clean:
        return {**common,"S0":tiers["S0"],"failure_class":"candidate","reason":"completed full-rule DRC rejection"}
    lvs_name=artifacts["lvs"]["report"]
    lvs_path=evidence/lvs_name
    if not lvs_path.exists():
        return {**common,"execution_integrity":"incomplete","failure_class":"infrastructure","reason":"LVS has no completed report"}
    lvs_clean=netgen_lvs_report(_artifact(evidence,lvs_name).read_text())["is_clean"]
    if observation["checks"]["lvs"]!=lvs_clean:
        raise ValueError("LVS observation contradicts its independent report")
    if not tiers["S1"]:
        return {**common,**tiers,"failure_class":"candidate","reason":"completed physical correctness rejection"}
    pex=artifacts["pex"]
    inventory=rc_netlist_inventory(_artifact(evidence,pex["netlist"]).read_text(),pex["top_cell"],pex["ports"])
    if not inventory["has_real_RC"]:
        return {**common,"S0":tiers["S0"],"S1":tiers["S1"],"execution_integrity":"incomplete",
                "failure_class":"infrastructure","reason":"No accepted physical RC model"}
    validations={};raw_records={}
    for corner in point["contract"]["required_corners"]:
        validations[corner]={}
        raw_records[corner]={}
        for name,requirement in point["contract"]["analysis_contracts"].items():
            raw=artifacts["spice"][corner]["analyses"][name]
            if "returncode" not in raw:
                raise ValueError("An analysis must retain its actual process return code")
            raw_records[corner][name]=raw
            validations[corner][name]=validate_analysis(_analysis_path(evidence,raw["data"]),
                _analysis_path(evidence,raw["log"]),requirement,returncode=raw["returncode"])
    complete=all(r["complete"] for corner in validations.values() for r in corner.values())
    if not complete:
        failure=classify_analysis_failure(validations,raw_records,evidence,common["gold_control"])
        return {**common,"S0":tiers["S0"],"S1":tiers["S1"],"analysis_validation":validations,**failure}
    return {**common,**tiers,"analysis_validation":validations,"analysis_complete":True,
            "failure_class":None if tiers["S2"] else "candidate",
            "reason":None if tiers["S2"] else "completed electrical specification rejection"}


class DevelopmentDomainRunner:
    def __init__(self,task,output_root,executor,prepare_point,workers=2):
        self.task=deepcopy(validate_domain(task))
        if workers not in [1,2]:raise ValueError("At most two 2-CPU containers are allowed")
        self.workers=workers;self.executor=executor;self.prepare_point=prepare_point
        self.output=Path(output_root)/("domain_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ_")+uuid.uuid4().hex[:8])
        self.output.mkdir(parents=True);self.output.chmod(0o700)
        (self.output/"private").mkdir();(self.output/"public").mkdir()
        (self.output/"private/task.json").write_text(json.dumps(task,indent=2)+"\n")
        self.points={p["configuration_id"]:p for p in self.task["configurations"]}
        self.state={"phase":"development_domain_pilot","status":"CREATED","mode":None,"hidden_started":False,
                    "points":{},"formal_trials":0,"training_examples":0}
        self._save()

    @classmethod
    def resume(cls,directory,executor,prepare_point,workers=2):
        """Restore a recorded run; completed points and hidden seal are retained."""
        if workers not in [1,2]:raise ValueError("At most two 2-CPU containers are allowed")
        self=cls.__new__(cls);self.output=Path(directory).resolve()
        self.task=validate_domain(json.loads((self.output/"private/task.json").read_text()))
        self.state=json.loads((self.output/"private/state.json").read_text())
        self.points={p["configuration_id"]:p for p in self.task["configurations"]}
        self.workers=workers;self.executor=executor;self.prepare_point=prepare_point
        if self.state["status"]!="CREATED":
            self.source_dir=self.output/"private/frozen_source"
            self.frozen=json.loads((self.output/"private/source_snapshot.json").read_text())
            self._check_source()
        return self

    def _save(self):
        (self.output/"private/state.json").write_text(json.dumps(self.state,indent=2)+"\n")

    def visible_packet(self,source):
        visible=[p for p in self.task["configurations"] if p["role"]!="hidden"]
        return deepcopy({"task_id":self.task["task_id"],"goal":self.task.get("goal","Development shared-source calibration"),
            "contract":{"configurations":[{"configuration_id":p["configuration_id"],"parameters":p["parameters"],"contract":p["contract"]} for p in visible]},
            "allowed_paths":self.task["editable_paths"],"visible_sources":dict(source),
            "documents":self.task.get("policy_documents",{}),"visible_configurations":[p["configuration_id"] for p in visible],
            "budget":self.task.get("budget",{"decisions":4})})

    def freeze(self,source_dir,patch="",mode="shared",parameter_values=None):
        if self.state["status"]!="CREATED" or mode not in ["shared","parameter","instance"]:
            raise ValueError("A source plan is fixed exactly once before evaluating a domain")
        if mode=="parameter" and patch.strip():raise ValueError("Parameter baseline cannot change generator source")
        values=layout_override(self.task,parameter_values or {})
        frozen=self.output/"private/frozen_source";frozen.mkdir()
        copy_declared_files(source_dir,self.task["source_paths"],frozen)
        if patch.strip():apply_source_patch(frozen,patch,self.task["editable_paths"])
        self.frozen=source_contents(frozen,self.task["source_paths"])
        self.source_dir=frozen
        for name in self.frozen:(frozen/name).chmod(0o444)
        (self.output/"private/source_snapshot.json").write_text(json.dumps(self.frozen,indent=2)+"\n")
        (self.output/"private/accepted_patch.diff").write_text(patch)
        self.state.update(mode=mode,status="SOURCE_FIXED",parameter_values=values)
        self._save()
        return {"mode":mode,"source_fixed":True}

    def _check_source(self):
        if source_contents(self.source_dir,self.task["source_paths"])!=self.frozen:
            raise ValueError("A fixed source snapshot changed after evaluation began")

    def _point(self,point,source_dir=None,expected_source=None):
        self._check_source()
        parameters={**point["parameters"],**self.state["parameter_values"]}
        directory=self.output/"private/points"/point["configuration_id"];directory.mkdir(parents=True)
        args=self.prepare_point(deepcopy(point),dict(parameters),directory)
        if json.loads((Path(args["trusted_dir"])/"contract.json").read_text())!=point["contract"]:
            raise ValueError("Point preparation cannot alter its independent contract")
        trusted={**self.task["trusted_evaluator_files"],"reference.spice":point["reference_netlist"],
                 "contract.json":json.dumps(point["contract"],indent=2)+"\n"}
        if set(args["trusted_paths"])!=set(trusted) or source_contents(args["trusted_dir"],args["trusted_paths"])!=trusted:
            raise ValueError("Point preparation changed the declared evaluator or independent N(z)")
        context={"phase":"development_domain_pilot","task_id":self.task["task_id"],"candidate_id":self.output.name,
            "configuration_id":point["configuration_id"],"reference_id":point["contract"]["reference_id"],
            "parent_lineage":self.task["parent_lineage"],"pdk_revision":self.task["pdk_revision"],"source_role":"development_domain_pilot"}
        result=self.executor.execute(source_dir=source_dir or self.source_dir,source_paths=self.task["source_paths"],
            entrypoint=self.task["entrypoint"],representation=self.task["representation"],configuration=parameters,
            fidelity="pex_spice",context=context,**args)
        try:
            record=inspect_point(result,point,expected_source or self.frozen,parameters)
        except (KeyError,ValueError,OSError) as exc:
            record={"run_directory":result["run_directory"],"S0":False,"S1":False,"S2":False,
                "execution_integrity":"incomplete","failure_class":"unknown","analysis_complete":False,
                "numerical_failure_established":False,"gold_control":inspect_gold_control(result["run_directory"],point,parameters),"reason":str(exc)}
        record["configuration_id"]=point["configuration_id"]
        (directory/"domain_point.json").write_text(json.dumps(record,indent=2)+"\n")
        return record

    def _evaluate(self,points,evaluation_stage="selection"):
        pending={};iterator=iter(points);halt=False
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for _ in range(self.workers):
                point=next(iterator,None)
                if point is not None:pending[pool.submit(self._point,point)]=point
            while pending:
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    point=pending.pop(future)
                    try:record=future.result()
                    except Exception as exc:
                        record={"configuration_id":point["configuration_id"],"S0":False,"S1":False,"S2":False,
                            "execution_integrity":"incomplete","failure_class":"infrastructure","reason":str(exc)}
                    record["evaluation_stage"]=evaluation_stage
                    directory=self.output/"private/points"/point["configuration_id"]
                    directory.mkdir(parents=True,exist_ok=True)
                    (directory/"domain_point.json").write_text(json.dumps(record,indent=2)+"\n")
                    self.state["points"][point["configuration_id"]]=record
                    halt=halt or record["execution_integrity"]!="valid"
                if not halt:
                    while len(pending)<self.workers:
                        point=next(iterator,None)
                        if point is None:break
                        pending[pool.submit(self._point,point)]=point
                self._save()
        if halt:self.state["status"]="PAUSED_INCOMPLETE_EVIDENCE"
        self._save()

    def evaluate_visible(self,configuration_ids=None):
        if self.state["mode"]=="instance" or self.state["hidden_started"] or self.state["status"] in ["CREATED","PAUSED_INCOMPLETE_EVIDENCE"]:
            raise ValueError("Visible shared-source evaluation is unavailable in this state")
        names=configuration_ids or [p["configuration_id"] for p in self.task["configurations"] if p["role"]!="hidden" and p["configuration_id"] not in self.state["points"]]
        if any(name not in self.points or self.points[name]["role"]=="hidden" for name in names):
            raise ValueError("Policy requests cannot name hidden configurations")
        if len(set(names))!=len(names):raise ValueError("A configuration cannot be submitted twice in one domain request")
        if any(name in self.state["points"] for name in names):raise ValueError("A completed point cannot be silently rerun")
        self._evaluate([self.points[name] for name in names])
        visible={name:self.state["points"][name] for name in names if name in self.state["points"]}
        feedback={name:{k:r.get(k) for k in ["S0","S1","S2","execution_integrity","failure_class","reason"]} for name,r in visible.items()}
        observed={name:{k:r.get(k) for k in ["S0","S1","S2","execution_integrity","failure_class","reason"]}
                  for name,r in self.state["points"].items() if self.points[name]["role"]!="hidden"}
        (self.output/"public/visible_feedback.json").write_text(json.dumps(observed,indent=2)+"\n")
        return feedback

    def run_hidden(self):
        if self.state["mode"] not in ["shared","parameter"] or self.state["hidden_started"]:
            raise ValueError("Hidden transfer runs once with a fixed shared source or layout-parameter plan")
        if self.state["status"]=="PAUSED_INCOMPLETE_EVIDENCE":raise ValueError("Resolve infrastructure failure in a new explicit run before hidden evaluation")
        anchor=[p["configuration_id"] for p in self.task["configurations"] if p["role"]=="anchor"]
        if any(name not in self.state["points"] for name in anchor):raise ValueError("The anchor must be observed before sealing hidden transfer")
        self._check_source();self.state["hidden_started"]=True;self.state["status"]="HIDDEN_RUNNING";self._save()
        unseen=[p for p in self.task["configurations"] if p["role"]=="development" and p["configuration_id"] not in self.state["points"]]
        self._evaluate(unseen,evaluation_stage="post_freeze_diagnostic")
        if self.state["status"]!="PAUSED_INCOMPLETE_EVIDENCE":
            self._evaluate([p for p in self.task["configurations"] if p["role"]=="hidden"],evaluation_stage="hidden_oracle")
        self.state["status"]="COMPLETE" if len(self.state["points"])==25 and all(p["execution_integrity"]=="valid" for p in self.state["points"].values()) else "PAUSED_INCOMPLETE_EVIDENCE"
        self._save()
        return self.report()

    def next_instance(self):
        if self.state["mode"]!="instance":raise ValueError("This is not an instance-arrival stream")
        if self.state["status"]=="PAUSED_INCOMPLETE_EVIDENCE":raise ValueError("Infrastructure evidence is incomplete; later arrivals remain sealed")
        index=len(self.state["points"])
        if index==25:return None
        point=self.task["configurations"][index]
        return deepcopy({"arrival_index":index,"configuration_id":point["configuration_id"],"parameters":point["parameters"],"contract":point["contract"]})

    def evaluate_instance(self,source_dir):
        point=self.next_instance()
        if point is None:raise ValueError("All arrivals already completed")
        name=point["configuration_id"]
        snapshot=self.output/"private/instance_sources"/name;snapshot.mkdir(parents=True)
        copy_declared_files(source_dir,self.task["source_paths"],snapshot)
        record=self._point(self.points[name],snapshot,source_contents(snapshot,self.task["source_paths"]))
        record["evaluation_stage"]="instance_arrival"
        self.state["points"][name]=record
        self.state["status"]="PAUSED_INCOMPLETE_EVIDENCE" if record["execution_integrity"]!="valid" else ("COMPLETE" if len(self.state["points"])==25 else "ARRIVAL_STREAM")
        self._save();return {k:record.get(k) for k in ["configuration_id","S0","S1","S2","execution_integrity","reason"]}

    def report(self,baseline=None):
        self._check_source()
        complete=len(self.state["points"])==25 and all(p["execution_integrity"]=="valid" for p in self.state["points"].values())
        groups={}
        for role in ["anchor","development","hidden"]:
            names=[p["configuration_id"] for p in self.task["configurations"] if p["role"]==role]
            results=[self.state["points"].get(name) for name in names]
            ready=all(r and r["execution_integrity"]=="valid" for r in results)
            passed=sum(bool(r and r["S2"]) for r in results)
            groups[role]={"passed":passed,"declared":len(names),"evaluated":sum(r is not None for r in results),
                "S2_coverage":passed/len(names) if ready else None}
        regression=None
        if baseline is not None:
            if set(baseline)!=set(self.points) or not complete:raise ValueError("Regression requires matched complete baseline and candidate domains")
            passed=[name for name,r in baseline.items() if r["execution_integrity"]=="valid" and r["S2"]]
            if any(r["execution_integrity"]!="valid" for r in baseline.values()):raise ValueError("Incomplete baseline cannot define regressions")
            regression=sum(not self.state["points"][name]["S2"] for name in passed)/len(passed) if passed else None
        costs={name:{"point_attempts":0,"observed_stage_wall_seconds":0.,"observed_waited_child_cpu_seconds":0.,
                     "missing_resource_records":0,"missing_invocation_records":0}
               for name in ["selection","post_freeze_diagnostic","hidden_oracle","instance_arrival"]}
        for name,record in self.state["points"].items():
            default="instance_arrival" if self.state["mode"]=="instance" else ("hidden_oracle" if self.points[name]["role"]=="hidden" else "selection")
            bucket=costs[record.get("evaluation_stage",default)];bucket["point_attempts"]+=1
            run=Path(record["run_directory"]) if "run_directory" in record else None
            if run is None:
                bucket["missing_invocation_records"]+=1;continue
            for stage in ["candidate","trusted"]:
                invocation=run/(stage+"_stage/invocation.json")
                if not invocation.exists():continue
                bucket["observed_stage_wall_seconds"]+=json.loads(invocation.read_text())["wall_seconds"]
                usage=run/(stage+"_stage/resource_usage.json")
                if usage.exists():
                    data=json.loads(usage.read_text())
                    bucket["observed_waited_child_cpu_seconds"]+=data["child_user_cpu_seconds"]+data["child_system_cpu_seconds"]
                else:bucket["missing_resource_records"]+=1
        report={"phase":"development_domain_pilot","mode":self.state["mode"],"complete_domain_evaluation":complete,
            "strict_hidden_transfer":self.state["mode"] in ["shared","parameter"],"groups":groups,
            "regression":regression,"regression_reason":"baseline_not_fully_evaluated" if baseline is None else None,
            "selection_calls":costs["selection"]["point_attempts"],
            "post_freeze_calls":costs["post_freeze_diagnostic"]["point_attempts"],
            "hidden_calls":costs["hidden_oracle"]["point_attempts"],"costs_by_stage":costs,
            "formal_trials":0,"training_examples":0,"point_records":self.state["points"]}
        (self.output/"private/domain_report.json").write_text(json.dumps(report,indent=2)+"\n")
        return deepcopy(report)
