"""Structured GPT decisions with native capabilities disabled and an external executor.

The policy receives only a task packet and its own visible history. Source reads,
patch application and physical tools belong to the caller's gateway. Hidden data
and evaluator implementation must remain on the separate execution host.
"""
from datetime import datetime, timezone
from collections.abc import Mapping
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import shlex
import subprocess
import time
import uuid


ACTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["read_source", "propose_patch", "request_evaluation", "finish"]},
        "path": {"type": "string"}, "patch": {"type": "string"},
        "configuration_ids": {"type": "array", "items": {"type": "string"}},
        "fidelity": {"type": "string", "enum": ["", "basic", "pex_spice"]},
        "summary": {"type": "string"}},
    "required": ["action", "path", "patch", "configuration_ids", "fidelity", "summary"]}

PACKET_FIELDS = {"task_id", "goal", "contract", "allowed_paths", "visible_sources",
                 "documents", "visible_configurations", "budget"}


def remaining_utc_budget(packet):
    deadline=packet["budget"].get("deadline_utc")
    if deadline is None:return None
    end=datetime.fromisoformat(deadline.replace("Z","+00:00"))
    if end.tzinfo is None:raise ValueError("Decision deadline must include its UTC offset")
    return (end-datetime.now(timezone.utc)).total_seconds()


def check_utc_budget(packet):
    remaining=remaining_utc_budget(packet)
    if remaining is not None and remaining<=0:raise TimeoutError("Absolute UTC decision budget expired")
    return remaining


def validate_action(action, packet):
    """Reject requests outside the declared visible interface before any execution."""
    if set(action) != set(ACTION_SCHEMA["required"]):
        raise ValueError("Action fields differ from the frozen interface")
    kind = action["action"]
    if kind not in ACTION_SCHEMA["properties"]["action"]["enum"]:
        raise ValueError("Unknown action")
    if not all(isinstance(action[k], str) for k in ["path", "patch", "fidelity", "summary"]):
        raise ValueError("Action text fields must be strings")
    ids = action["configuration_ids"]
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError("Configuration IDs must be strings")
    if len(set(ids)) != len(ids) or not set(ids).issubset(packet["visible_configurations"]):
        raise ValueError("Evaluation request names configurations outside the visible domain")
    if kind == "read_source" and action["path"] not in packet["visible_sources"]:
        raise ValueError("Source read is outside the task packet")
    if kind == "propose_patch":
        allowed = set(packet["allowed_paths"])
        touched = []
        for line in action["patch"].splitlines():
            if line.startswith(("rename from ", "rename to ", "copy from ", "copy to ",
                                "GIT binary patch", "Binary files ", "old mode ", "new mode ", "deleted file mode ")):
                raise ValueError("Only ordinary source-content patches are allowed")
            if line.startswith("new file mode ") and line != "new file mode 100644":
                raise ValueError("New source must be a regular nonexecutable file")
            if line.startswith("diff --git "):
                fields = shlex.split(line)
                if len(fields)!=4 or any(n[2:] not in allowed or not n.startswith(("a/","b/")) for n in fields[2:]):
                    raise ValueError("Diff metadata touches a path outside the action space")
            if line.startswith(("--- ", "+++ ")):
                name = line[4:].split("\t")[0]
                if name == "/dev/null":
                    continue
                if name.startswith(("a/", "b/")):
                    name = name[2:]
                if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or name not in allowed:
                    raise ValueError("Patch touches a path outside the action space")
                touched.append(name)
        if not touched or not action["patch"].strip():
            raise ValueError("No allowed source patch was supplied")
    if kind == "request_evaluation" and (not ids or action["fidelity"] not in ["basic", "pex_spice"]):
        raise ValueError("Evaluation requires visible configurations and declared fidelity")
    return action


class GptDecisionAdapter:
    def __init__(self, output_root, executable=None, tokenizer=None):
        self.output_root = Path(output_root).resolve()
        self.executable = executable or shutil.which(os.environ.get("GPT_CLI", "gpt-cli"))
        self.tokenizer = tokenizer
        if not self.executable:
            raise RuntimeError("Authenticated GPT CLI is unavailable")

    def start(self, task_packet, model_config):
        if set(task_packet) != PACKET_FIELDS:
            raise ValueError("Task packet contains missing or undeclared context fields")
        if "max_context_tokens" in model_config or "max_new_tokens" in model_config:
            context=model_config.get("max_context_tokens")
            if (self.tokenizer is None or type(context) is not int or context<=1024
                    or model_config.get("max_new_tokens") != 1024):
                raise ValueError("The bounded GPT policy requires the shared tokenizer, declared context, and1024output budget")
            if (task_packet["budget"].get("maximum_output_tokens") != 1024
                    or task_packet["budget"].get("maximum_context_tokens") != context):
                raise ValueError("The complete policy packet must disclose the shared context and output budgets")
        session_id = str(uuid.uuid4())
        out = self.output_root/session_id
        out.mkdir(parents=True)
        session = {"session_id": session_id, "output": str(out), "packet": task_packet,
                   "config": model_config, "history": [], "usage": [], "closed": False}
        (out/"task_packet.json").write_text(json.dumps(task_packet, indent=2)+"\n")
        (out/"model_config.json").write_text(json.dumps(model_config, indent=2)+"\n")
        return session

    def step(self, session, observation, current_sources=None):
        if session["closed"]:
            raise ValueError("Session is closed")
        if len(session["history"]) >= session["packet"]["budget"]["decisions"]:
            raise ValueError("Decision budget exhausted")
        check_utc_budget(session["packet"])
        config = session["config"]
        index = len(session["history"])
        work = Path(session["output"])/f"decision_{index:03d}"
        work.mkdir()
        session["history"].append({"observation": observation})
        request = {"task_packet": session["packet"], "visible_history": session["history"]}
        if session["config"].get("visible_history_policy"):
            from src.policy_state import VERSION, current_state_request
            if session["config"]["visible_history_policy"] != VERSION:
                raise ValueError("Unknown visible history policy")
            request = current_state_request(session["packet"], session["history"], current_sources or {})
        from src.local_model_adapter import decision_prompt
        prompt = decision_prompt(request)
        (work/"request.json").write_text(json.dumps(request, indent=2)+"\n")
        token_budget = None
        if "max_context_tokens" in config:
            token_budget = prompt_token_budget(self.tokenizer, prompt, config)
            (work/"token_budget.json").write_text(json.dumps(token_budget, indent=2)+"\n")
            if not token_budget["fits_with_full_output_reserve"]:
                raise ValueError("Complete GPT source/history exceeds the shared context budget; no inference issued")
        schema = work/"action_schema.json"
        schema.write_text(json.dumps(ACTION_SCHEMA, indent=2)+"\n")
        answer = work/"action.json"
        command = [self.executable, "exec", "--ignore-user-config", "--ephemeral",
            "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--color", "never",
            "--model", config["model"], "-C", str(work),
            "-c", "approval_policy=\"never\"", "-c", "web_search=\"disabled\"",
            "-c", "model_reasoning_effort="+json.dumps(config["reasoning_effort"]),
            "-c", "model_reasoning_summary=\"none\"", "-c", "show_raw_agent_reasoning=false",
            "-c", "project_doc_max_bytes=0", "-c", "mcp_servers={}",
            "-c", "skills.bundled.enabled=false", "-c", "skills.include_instructions=false"]
        for feature in ["shell_tool", "unified_exec", "apps", "plugins", "memories", "multi_agent",
                "multi_agent_v2", "computer_use", "browser_use", "browser_use_external", "image_generation",
                "view_image", "hooks", "workspace_dependencies", "tool_suggest", "in_app_browser",
                "in_app_chat", "in_app_local_automation", "code_mode", "code_mode_host", "skill_search"]:
            command += ["--disable", feature]
        command += ["--output-schema", str(schema), "--output-last-message", str(answer), "-"]
        began_utc=datetime.now(timezone.utc)
        remaining=check_utc_budget(session["packet"])
        timeout=config["timeout_seconds_per_decision"] if remaining is None else min(config["timeout_seconds_per_decision"],remaining)
        record = {"argv": command, "started_at_utc": began_utc.isoformat(),
                  "deadline_utc":session["packet"]["budget"].get("deadline_utc"),"timeout_seconds":timeout,
                  "requested_model": config["model"], "status": "RUNNING"}
        (work/"invocation.json").write_text(json.dumps(record, indent=2)+"\n")
        started = time.monotonic()
        with (work/"events.jsonl").open("w") as events, (work/"stderr.log").open("w") as err:
            try:
                process=subprocess.Popen(command,stdin=subprocess.PIPE,text=True,stdout=events,stderr=err)
                record["pid"]=process.pid
                (work/"invocation.json").write_text(json.dumps(record,indent=2)+"\n")
                process.communicate(prompt,timeout=timeout)
                record.update(returncode=process.returncode, status="COMPLETED" if process.returncode==0 else "FAILED")
            except subprocess.TimeoutExpired:
                process.kill();process.communicate()
                record.update(returncode=None, status="TIMEOUT")
        record["wall_seconds"] = time.monotonic()-started
        ended_utc=datetime.now(timezone.utc);record["ended_at_utc"] = ended_utc.isoformat()
        record["utc_elapsed_seconds"]=(ended_utc-began_utc).total_seconds()
        record["observed_utc_monotonic_gap_seconds"]=record["utc_elapsed_seconds"]-record["wall_seconds"]
        native = []
        prelude_warnings = []
        turn_started = False
        for line in (work/"events.jsonl").read_text().splitlines():
            event = json.loads(line)
            if event.get("type")=="turn.started":
                turn_started=True
            if event.get("type")=="turn.completed":
                session["usage"].append(event.get("usage"))
            if event.get("type", "").startswith("item."):
                kind = event.get("item", {}).get("type")
                if kind == "error" and not turn_started and event["item"].get("message", "").startswith(
                        "Code Mode is unavailable because code-mode host is disabled."):
                    prelude_warnings.append(event["item"]["message"])
                    continue
                if kind not in ["agent_message", "reasoning"]:
                    native.append(kind)
        record["native_item_types"] = sorted(set(native))
        record["disabled_capability_notices"] = prelude_warnings
        if native:
            record["status"] = "REJECTED_NATIVE_TOOL_USE"
        remaining=remaining_utc_budget(session["packet"])
        record["utc_deadline_exceeded"]=remaining is not None and remaining<=0
        if record["utc_deadline_exceeded"]:record["status"]="UTC_BUDGET_EXCEEDED"
        (work/"invocation.json").write_text(json.dumps(record, indent=2)+"\n")
        if record["status"]!="COMPLETED" or not answer.is_file():
            raise RuntimeError("Experimental decision failed; inspect "+str(work))
        check_utc_budget(session["packet"])
        action = validate_action(json.loads(answer.read_text()), session["packet"])
        if token_budget is not None:
            completion = len(self.tokenizer(answer.read_text(), add_special_tokens=False)["input_ids"]) + 1
            token_budget.update(completion_tokens_including_EOS=completion,
                actual_total_tokens=token_budget["prompt_tokens"]+completion,
                output_within_budget=completion <= config["max_new_tokens"],
                public_provider_usage_scope="Provider reasoning and token accounting are retained separately; this count uses the common policy tokenizer")
            (work/"token_budget.json").write_text(json.dumps(token_budget, indent=2)+"\n")
            if not token_budget["output_within_budget"]:
                record["status"] = "REJECTED_SHARED_OUTPUT_BUDGET"
                (work/"invocation.json").write_text(json.dumps(record, indent=2)+"\n")
                raise ValueError("GPT output exceeds the shared action budget; raw output and public cost retained, action not applied")
        session["history"][-1]["action"] = action
        return action

    def finish(self, session):
        session["closed"] = True
        (Path(session["output"])/"session.json").write_text(json.dumps(session, indent=2)+"\n")
        return {"output": session["output"], "public_usage_metadata": session["usage"]}


def prompt_token_budget(tokenizer, prompt, config):
    rendered = tokenizer.apply_chat_template([{"role":"user", "content":prompt}], tokenize=True, add_generation_prompt=True)
    tokens = rendered["input_ids"] if isinstance(rendered, Mapping) else rendered
    return {"prompt_tokens":len(tokens), "output_reserve":config["max_new_tokens"],
        "max_context_tokens":config["max_context_tokens"],
        "fits_with_full_output_reserve":len(tokens)+config["max_new_tokens"] <= config["max_context_tokens"],
        "source_or_history_truncated":False, "native_provider_context_limit_claimed":False}
