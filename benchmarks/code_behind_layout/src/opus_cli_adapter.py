"""Structured Claude decisions through the Claude CLI command line with every tool disabled.

Mirror of GptDecisionAdapter for a second frontier policy. The policy receives only the
task packet and its own visible history; source reads, patch application and physical tools
belong to the caller's gateway. Each decision is one fresh, non-persistent process in an empty
scratch directory outside any project tree, with tools, MCP servers, hooks, plugins, skills and
project instructions disabled (--safe-mode), a fixed system prompt and one turn. Raw output,
usage and cost are retained even when the action is rejected.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from src.model_adapter import (ACTION_SCHEMA, PACKET_FIELDS, check_utc_budget, prompt_token_budget,
                               remaining_utc_budget, validate_action)

BACKEND = "claude_cli"
DEFAULT_EXECUTABLE = os.environ.get("CLAUDE_CLI", "claude")
CWD_ROOT = Path("/tmp/cbl-policy-cwd")
SYSTEM_PROMPT = ("You are the experimental policy for one analog-layout task. Reply with exactly one JSON object "
                 "and nothing else: no prose, no markdown fence. The object has the fields action, path, patch, "
                 "configuration_ids, fidelity and summary. action is one of read_source, propose_patch, "
                 "request_evaluation, finish; fidelity is basic or pex_spice for request_evaluation and empty otherwise. "
                 "Use empty strings or lists for irrelevant fields. A patch is a unified "
                 "diff against the visible source. Source reads, patch application and physical evaluation happen "
                 "only through the action gateway; you have no tools, filesystem, shell or network. Only the supplied "
                 "task packet and visible history belong to this trial.")
SETTINGS_OVERRIDE = json.dumps({"hooks": {}, "enabledPlugins": {}, "env": {}})
PROVIDER_PAUSE_PATTERN = ("rate limit", "rate_limit", "usage limit", "usage_limit", "overloaded", "overloaded_error", "429", "529",
                          "too many requests", "capacity", "try again later", "temporarily unavailable", "server error", "500", "502", "503", "504")
PROVIDER_PAUSE_BACKOFF_S = (60, 120, 240, 480, 900, 900)
FIXED_FLAGS = ["-p", "--output-format", "json", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
               "--max-turns", "3", "--permission-mode", "default", "--safe-mode", "--disable-slash-commands",
               "--exclude-dynamic-system-prompt-sections"]


def provider_pause(text):
    """True when a provider error names a rate, usage or capacity limit that is expected to clear."""
    lowered = (text or "").lower()
    return any(token in lowered for token in PROVIDER_PAUSE_PATTERN)


def strip_single_fence(text):
    """Remove one outer ```json ... ``` fence if present; record whether it happened."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        body = stripped[3:-3].strip()
        if body.lower().startswith("json"):
            body = body[4:].strip()
        return body, True
    return stripped, False


class ClaudeCLIDecisionAdapter:
    def __init__(self, output_root, executable=None, tokenizer=None):
        self.output_root = Path(output_root).resolve()
        self.executable = executable or DEFAULT_EXECUTABLE
        self.tokenizer = tokenizer
        if not Path(self.executable).is_file():
            raise RuntimeError("Claude CLI executable is unavailable: " + str(self.executable))

    def start(self, task_packet, model_config):
        if set(task_packet) != PACKET_FIELDS:
            raise ValueError("Task packet contains missing or undeclared context fields")
        if model_config.get("backend") != BACKEND:
            raise ValueError("Model config does not declare the Claude CLI backend")
        context = model_config.get("max_context_tokens")
        if (self.tokenizer is None or type(context) is not int or context <= 1024
                or model_config.get("max_new_tokens") != 1024):
            raise ValueError("The bounded Claude policy requires the shared tokenizer, declared context, and 1024 output budget")
        if (task_packet["budget"].get("maximum_output_tokens") != 1024
                or task_packet["budget"].get("maximum_context_tokens") != context):
            raise ValueError("The complete policy packet must disclose the shared context and output budgets")
        session_id = str(uuid.uuid4())
        out = self.output_root / session_id
        out.mkdir(parents=True)
        session = {"session_id": session_id, "output": str(out), "packet": task_packet,
                   "config": model_config, "history": [], "usage": [], "closed": False}
        (out / "task_packet.json").write_text(json.dumps(task_packet, indent=2) + "\n")
        (out / "model_config.json").write_text(json.dumps(model_config, indent=2) + "\n")
        return session

    def command(self, config, work):
        argv = [self.executable, *FIXED_FLAGS, "--model", config["model"],
                "--settings", SETTINGS_OVERRIDE, "--system-prompt", SYSTEM_PROMPT,
                "--json-schema", json.dumps(ACTION_SCHEMA, separators=(",", ":"))]
        effort = config.get("reasoning_effort")
        if effort and effort != "default":
            argv += ["--effort", str(effort)]
        return argv

    def step(self, session, observation, current_sources=None):
        if session["closed"]:
            raise ValueError("Session is closed")
        if len(session["history"]) >= session["packet"]["budget"]["decisions"]:
            raise ValueError("Decision budget exhausted")
        check_utc_budget(session["packet"])
        config = session["config"]
        index = len(session["history"])
        work = Path(session["output"]) / f"decision_{index:03d}"
        work.mkdir()
        session["history"].append({"observation": observation})
        request = {"task_packet": session["packet"], "visible_history": session["history"]}
        if config.get("visible_history_policy"):
            from src.policy_state import VERSION, current_state_request
            if config["visible_history_policy"] != VERSION:
                raise ValueError("Unknown visible history policy")
            request = current_state_request(session["packet"], session["history"], current_sources or {})
        from src.local_model_adapter import decision_prompt
        prompt = decision_prompt(request)
        (work / "request.json").write_text(json.dumps(request, indent=2) + "\n")
        token_budget = prompt_token_budget(self.tokenizer, prompt, config)
        (work / "token_budget.json").write_text(json.dumps(token_budget, indent=2) + "\n")
        if not token_budget["fits_with_full_output_reserve"]:
            raise ValueError("Complete source/history exceeds the shared context budget; no inference issued")
        (work / "action_schema.json").write_text(json.dumps(ACTION_SCHEMA, indent=2) + "\n")
        argv = self.command(config, work)
        attempts = []
        for attempt in range(len(PROVIDER_PAUSE_BACKOFF_S) + 1):
            record, result_text = self.invoke(session, config, work, argv, prompt, attempt)
            attempts.append({"attempt": attempt, "status": record["status"], "pid": record.get("pid"),
                             "wall_seconds": record.get("wall_seconds"), "provider_result": record.get("provider_result")})
            if record["status"] != "PROVIDER_ERROR" or not provider_pause(record.get("provider_result")):
                break
            remaining = remaining_utc_budget(session["packet"])
            pause = PROVIDER_PAUSE_BACKOFF_S[min(attempt, len(PROVIDER_PAUSE_BACKOFF_S) - 1)]
            if attempt >= len(PROVIDER_PAUSE_BACKOFF_S) or (remaining is not None and remaining <= pause + 60):
                break
            record["provider_pause_retry_in_seconds"] = pause
            (work / f"attempt_{attempt:02d}_provider_pause.json").write_text(json.dumps(record, indent=2) + "\n")
            time.sleep(pause)
        if len(attempts) > 1:
            record["provider_pause_attempts"] = attempts
            (work / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
        if record["status"] != "COMPLETED" or not isinstance(result_text, str):
            raise RuntimeError("Experimental decision failed; inspect " + str(work))
        check_utc_budget(session["packet"])
        (work / "raw_result.txt").write_text(result_text)
        body, fenced = strip_single_fence(result_text)
        record["fence_stripped"] = fenced
        completion = len(self.tokenizer(result_text, add_special_tokens=False)["input_ids"]) + 1
        token_budget.update(completion_tokens_including_EOS=completion,
                            actual_total_tokens=token_budget["prompt_tokens"] + completion,
                            output_within_budget=completion <= config["max_new_tokens"],
                            public_provider_usage_scope="Provider token and cost accounting are retained separately; this count uses the common policy tokenizer")
        (work / "token_budget.json").write_text(json.dumps(token_budget, indent=2) + "\n")
        if not token_budget["output_within_budget"]:
            record["status"] = "REJECTED_SHARED_OUTPUT_BUDGET"
            (work / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
            raise ValueError("Claude output exceeds the shared action budget; raw output and public cost retained, action not applied")
        try:
            parsed = json.loads(body)
        except ValueError as error:
            record["status"] = "REJECTED_NON_JSON_ACTION"
            (work / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
            raise ValueError("Claude output is not a single JSON action: " + str(error))
        try:
            action = validate_action(parsed, session["packet"])
        except ValueError:
            record["status"] = "REJECTED_INVALID_ACTION"
            (work / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
            raise
        (work / "action.json").write_text(json.dumps(action) + "\n")
        (work / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
        session["history"][-1]["action"] = action
        return action

    def invoke(self, session, config, work, argv, prompt, attempt):
        """One CLI process for one decision; a retried attempt keeps the earlier attempt's record on disk."""
        CWD_ROOT.mkdir(parents=True, exist_ok=True)
        index = len(session["history"]) - 1
        cwd = Path(tempfile.mkdtemp(prefix=f"{session['session_id'][:8]}_{index:03d}_{attempt:02d}_", dir=CWD_ROOT))
        began_utc = datetime.now(timezone.utc)
        remaining = check_utc_budget(session["packet"])
        timeout = config["timeout_seconds_per_decision"] if remaining is None else min(config["timeout_seconds_per_decision"], remaining)
        record = {"argv": argv, "cwd": str(cwd), "attempt": attempt, "started_at_utc": began_utc.isoformat(),
                  "deadline_utc": session["packet"]["budget"].get("deadline_utc"), "timeout_seconds": timeout,
                  "requested_model": config["model"], "requested_effort": config.get("reasoning_effort"),
                  "backend": BACKEND, "status": "RUNNING"}
        (work / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
        started = time.monotonic()
        suffix = "" if attempt == 0 else f"_attempt{attempt:02d}"
        stdout_path, stderr_path = work / f"stdout{suffix}.json", work / f"stderr{suffix}.log"
        with stdout_path.open("w") as out, stderr_path.open("w") as err:
            try:
                process = subprocess.Popen(argv, stdin=subprocess.PIPE, text=True, stdout=out, stderr=err, cwd=str(cwd))
                record["pid"] = process.pid
                (work / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
                process.communicate(prompt, timeout=timeout)
                record.update(returncode=process.returncode, status="COMPLETED" if process.returncode == 0 else "FAILED")
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                record.update(returncode=None, status="TIMEOUT")
        record["wall_seconds"] = time.monotonic() - started
        ended_utc = datetime.now(timezone.utc)
        record["ended_at_utc"] = ended_utc.isoformat()
        record["utc_elapsed_seconds"] = (ended_utc - began_utc).total_seconds()
        record["cwd_entries_after"] = sorted(p.name for p in cwd.iterdir())
        shutil.rmtree(cwd, ignore_errors=True)
        result_text = None
        try:
            envelope = json.loads(stdout_path.read_text() or "null")
        except ValueError:
            envelope = None
        if isinstance(envelope, dict):
            session["usage"].append({"usage": envelope.get("usage"), "modelUsage": envelope.get("modelUsage"),
                                     "total_cost_usd": envelope.get("total_cost_usd"), "duration_api_ms": envelope.get("duration_api_ms"),
                                     "num_turns": envelope.get("num_turns"), "is_error": envelope.get("is_error"),
                                     "stop_reason": envelope.get("stop_reason"), "terminal_reason": envelope.get("terminal_reason"),
                                     "attempt": attempt})
            record["actual_models"] = sorted((envelope.get("modelUsage") or {}).keys())
            record["num_turns"] = envelope.get("num_turns")
            record["permission_denials"] = envelope.get("permission_denials")
            record["subagents_spawned"] = ((envelope.get("subagent_stats") or {}).get("spawned"))
            structured = envelope.get("structured_output")
            record["structured_output_present"] = isinstance(structured, dict)
            turns = envelope.get("num_turns") or 1
            # --json-schema delivers the object through the CLI's internal StructuredOutput turn (num_turns 2 when the
            # model calls it at once, 3 when the CLI has to ask once more); --max-turns 3 bounds that. Every built-in tool
            # is disabled, so only permission requests, subagents or turns beyond the structured exchange indicate tool use.
            record["terminal_reason"] = envelope.get("terminal_reason")
            tool_turns = turns > 3 or bool(record.get("subagents_spawned")) or bool(envelope.get("permission_denials"))
            record["native_item_types"] = ["multi_turn_tool_use"] if tool_turns else []
            if envelope.get("is_error"):
                record["status"] = "PROVIDER_ERROR"
                record["provider_result"] = str(envelope.get("result"))[:500]
                if envelope.get("terminal_reason") == "max_turns" and not isinstance(structured, dict):
                    record["status"] = "REJECTED_UNSTRUCTURED_OUTPUT"
                    record["provider_result"] = "model ended its turns without the structured action"
            if tool_turns:
                record["status"] = "REJECTED_NATIVE_TOOL_USE"
            result_text = json.dumps(structured) if isinstance(structured, dict) else envelope.get("result")
        elif record["status"] == "COMPLETED":
            record["status"] = "PROVIDER_ERROR"
            record["provider_result"] = "no JSON envelope on stdout; stderr: " + stderr_path.read_text()[:300]
        remaining = remaining_utc_budget(session["packet"])
        record["utc_deadline_exceeded"] = remaining is not None and remaining <= 0
        if record["utc_deadline_exceeded"]:
            record["status"] = "UTC_BUDGET_EXCEEDED"
        (work / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
        return record, result_text

    def finish(self, session):
        session["closed"] = True
        (Path(session["output"]) / "session.json").write_text(json.dumps(session, indent=2) + "\n")
        return {"output": session["output"], "public_usage_metadata": session["usage"]}
