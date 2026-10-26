"""Claude CLI policy adapter with format guidance in its fixed system prompt (amendment A6, cohort E1-C2).

Everything else is inherited unchanged from ClaudeCLIDecisionAdapter: the same flags, the same
schema enforcement, the same records. Only the system prompt text differs, and the cohort's frozen
model_config names this prompt version so no session can run with the other prompt by mistake.
"""
import json

from src.opus_cli_adapter import FIXED_FLAGS, SETTINGS_OVERRIDE, SYSTEM_PROMPT, ClaudeCLIDecisionAdapter
from src.model_adapter import ACTION_SCHEMA

SYSTEM_PROMPT_VERSION = "format_guidance_v2"
SYSTEM_PROMPT_V2 = SYSTEM_PROMPT + (
    " Format rules: the whole action must fit within 1,024 tokens of the shared tokenizer, and a longer action is "
    "rejected without execution, so keep summary to one short sentence and keep each patch minimal, one focused change "
    "per decision. A patch is a strict unified diff that git apply accepts: every hunk header counts lines exactly, every "
    "hunk keeps three unchanged context lines before and after the change unless the file begins or ends there, and the "
    "context lines match the visible source character for character.")


class ClaudeCLIDecisionAdapterV2(ClaudeCLIDecisionAdapter):
    def start(self, task_packet, model_config):
        if model_config.get("system_prompt_version") != SYSTEM_PROMPT_VERSION:
            raise ValueError("Model config does not name the format-guidance system prompt of cohort E1-C2")
        return super().start(task_packet, model_config)

    def command(self, config, work):
        argv = [self.executable, *FIXED_FLAGS, "--model", config["model"],
                "--settings", SETTINGS_OVERRIDE, "--system-prompt", SYSTEM_PROMPT_V2,
                "--json-schema", json.dumps(ACTION_SCHEMA, separators=(",", ":"))]
        effort = config.get("reasoning_effort")
        if effort and effort != "default":
            argv += ["--effort", str(effort)]
        return argv
