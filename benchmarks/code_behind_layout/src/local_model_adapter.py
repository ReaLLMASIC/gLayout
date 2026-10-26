"""Structured local-model decisions using the GPT packet/history/action gateway.

The transport command is configured by the coordinator, never by policy output.
It sends JSON on stdin to a fixed localhost inference endpoint on the GPU host.
"""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import time
import uuid

from src.model_adapter import ACTION_SCHEMA,PACKET_FIELDS,check_utc_budget,remaining_utc_budget,validate_action


DECISION_INSTRUCTIONS=("You are the experimental policy for one analog-layout task. Return one structured action. "
    "All source reads, patch execution and physical evaluation occur through the action gateway. "
    "Use read_source, propose_patch, request_evaluation or finish. Use empty strings/lists for irrelevant fields. "
    "Native shell, filesystem edits, connectors, browsing and delegation are disabled. "
    "Only the supplied packet and visible feedback belong to this trial.\n")

SOURCE_PROPOSAL_SCHEMA={"type":"object","additionalProperties":False,
    "properties":{"source_text":{"type":"string"}},"required":["source_text"]}


def source_proposal_prompt(request):
    """Separate teacher collector format; this is not a tested policy action."""
    if set(request)!={"task_packet","visible_history"} or set(request["task_packet"])!=PACKET_FIELDS:
        raise ValueError("Teacher source proposals require the same visible packet boundary")
    packet=request["task_packet"];paths=packet["allowed_paths"]
    if len(paths)!=1 or set(packet["visible_sources"])!=set(paths):
        raise ValueError("A complete-source proposal must target exactly one complete editable module")
    return ("You are generating one training candidate for the visible analog-layout task. "
        "Return JSON with exactly one field, source_text, containing the complete replacement source of the sole editable module. "
        "Preserve the module's full valid Python structure and public API. Do not return a diff, action, markdown fence or partial snippet. "
        "You may change only the supplied editable module; its common libraries, circuit sizing, references and evaluator are fixed. "
        "This proposal format is used only by the training collector; it does not grant tools, filesystem or command execution. "
        "Only the supplied task packet and visible history belong to this request.\n"+json.dumps(request))


def validate_source_proposal(value):
    if not isinstance(value,dict) or set(value)!={"source_text"} or not isinstance(value["source_text"],str) or not value["source_text"]:
        raise ValueError("A teacher proposal must contain exactly one nonempty complete-source string")
    return value


def decision_prompt(request):
    if set(request)!={"task_packet","visible_history"} or set(request["task_packet"])!=PACKET_FIELDS:
        raise ValueError("Local and GPT policies require the same declared task packet/history")
    return DECISION_INSTRUCTIONS+json.dumps(request)


class LocalDecisionAdapter:
    def __init__(self,output_root,request_command):
        self.output_root=Path(output_root).resolve()
        self.request_command=list(request_command)
        if not self.request_command:raise ValueError("A fixed coordinator-controlled transport is required")

    def start(self,task_packet,model_config):
        if set(task_packet)!=PACKET_FIELDS:raise ValueError("Task packet contains missing or undeclared fields")
        session_id=str(uuid.uuid4());out=self.output_root/session_id;out.mkdir(parents=True)
        session={"session_id":session_id,"output":str(out),"packet":task_packet,"config":model_config,
            "history":[],"usage":[],"closed":False}
        (out/"task_packet.json").write_text(json.dumps(task_packet,indent=2)+"\n")
        (out/"model_config.json").write_text(json.dumps(model_config,indent=2)+"\n")
        return session

    def step(self,session,observation,current_sources=None):
        if session["closed"]:raise ValueError("Session is closed")
        if len(session["history"])>=session["packet"]["budget"]["decisions"]:raise ValueError("Decision budget exhausted")
        check_utc_budget(session["packet"])
        index=len(session["history"]);out=Path(session["output"])/("decision_%03d"%index);out.mkdir()
        session["history"].append({"observation":observation})
        request={"task_packet":session["packet"],"visible_history":session["history"]}
        if session["config"].get("visible_history_policy"):
            from src.policy_state import VERSION,current_state_request
            if session["config"]["visible_history_policy"]!=VERSION:raise ValueError("Unknown visible history policy")
            request=current_state_request(session["packet"],session["history"],current_sources or {})
        decision_prompt(request)
        body={"variant":session["config"]["variant"],"request":request}
        if "sampling" in session["config"]:
            body.update(mode=session["config"].get("sampling_mode","development_corpus"),sampling=session["config"]["sampling"])
        (out/"request.json").write_text(json.dumps(body,indent=2)+"\n")
        began_utc=datetime.now(timezone.utc);remaining=check_utc_budget(session["packet"])
        timeout=session["config"]["timeout_seconds_per_decision"] if remaining is None else min(session["config"]["timeout_seconds_per_decision"],remaining)
        record={"argv":self.request_command,"started_at_utc":began_utc.isoformat(),
            "deadline_utc":session["packet"]["budget"].get("deadline_utc"),"timeout_seconds":timeout,
            "variant":session["config"]["variant"],"status":"RUNNING"}
        (out/"invocation.json").write_text(json.dumps(record,indent=2)+"\n")
        started=time.monotonic()
        with (out/"response.json").open("w") as response,(out/"stderr.log").open("w") as err:
            try:
                process=subprocess.Popen(self.request_command,stdin=subprocess.PIPE,text=True,stdout=response,stderr=err)
                record["pid"]=process.pid;(out/"invocation.json").write_text(json.dumps(record,indent=2)+"\n")
                process.communicate(json.dumps(body),timeout=timeout)
                record.update(returncode=process.returncode,status="COMPLETED" if process.returncode==0 else "FAILED")
            except subprocess.TimeoutExpired:
                process.kill();process.communicate()
                record.update(returncode=None,status="TIMEOUT")
        record["wall_seconds"]=time.monotonic()-started
        ended_utc=datetime.now(timezone.utc);record["ended_at_utc"]=ended_utc.isoformat()
        record["utc_elapsed_seconds"]=(ended_utc-began_utc).total_seconds()
        record["observed_utc_monotonic_gap_seconds"]=record["utc_elapsed_seconds"]-record["wall_seconds"]
        remaining=remaining_utc_budget(session["packet"])
        record["utc_deadline_exceeded"]=remaining is not None and remaining<=0
        if record["utc_deadline_exceeded"]:record["status"]="UTC_BUDGET_EXCEEDED"
        (out/"invocation.json").write_text(json.dumps(record,indent=2)+"\n")
        result=json.loads((out/"response.json").read_text()) if (out/"response.json").stat().st_size else {}
        if result.get("usage"):
            session["usage"].append({**result["usage"],"transport_inclusive_wall_seconds":record["wall_seconds"],
                "model":result["model"],"inference_id":result["inference_id"],"accepted":record["status"]=="COMPLETED"})
        if record["status"]!="COMPLETED":raise RuntimeError("Local policy decision failed: "+result.get("error","transport failure")+"; inspect "+str(out))
        if result.get("error"):raise RuntimeError("Local policy rejected the request: "+result["error"])
        if result["model"]["base_revision"]!=session["config"]["base_revision"] or result["model"]["variant"]!=session["config"]["variant"]:
            raise ValueError("Served weights differ from the configured local policy")
        check_utc_budget(session["packet"])
        action=validate_action(result["action"],session["packet"])
        session["history"][-1]["action"]=action
        (out/"action.json").write_text(json.dumps(action,indent=2)+"\n")
        return action

    def finish(self,session):
        session["closed"]=True
        (Path(session["output"])/"session.json").write_text(json.dumps(session,indent=2)+"\n")
        return {"output":session["output"],"public_usage_metadata":session["usage"]}
