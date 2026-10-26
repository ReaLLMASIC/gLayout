"""Isolated Claude CLI producer for literal-span training proposals (teacher: Claude Opus 5.5).

Mirror of src/train_span_cli.py (the GPT producer) with the same request, response, token-budget and
rejection contract, invoking the Claude CLI command line exactly as src/opus_cli_adapter.py does for the
policy cohorts: one fresh non-persistent process in an empty scratch directory, every tool, MCP server, hook,
plugin, skill and project instruction disabled, a fixed system prompt, the span JSON schema enforced through
--json-schema, and the raw envelope, usage and cost retained even when the proposal is rejected.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from src.opus_cli_adapter import DEFAULT_EXECUTABLE, FIXED_FLAGS, SETTINGS_OVERRIDE, provider_pause, strip_single_fence
from src.model_adapter import prompt_token_budget
from src.train_span_proposer import MODE, SCHEMA, VERSION, proposal_prompt, validate_proposal

BACKEND = 'isolated_claude_cli'
MODEL = 'claude-opus-5-5'
ROLE = 'isolated_Claude_formal_train_literal_span_teacher'
CWD_ROOT = Path('/tmp/cbl-span-teacher-cwd')
SYSTEM_PROMPT = ('You are the train-only literal-span teacher for one analog-layout generator task. Reply with exactly one JSON '
                 'object and nothing else: no prose, no markdown fence. The object has one field, edits: an array of '
                 '{path, old, new} string objects. Each old must be nonempty and occur exactly once in the ORIGINAL full source '
                 'of its allowed path, including whitespace; all old intervals must be disjoint; new may be empty for a deletion. '
                 'Change only what the declared objective and constraints require and preserve every unaffected line. You have no '
                 'tools, filesystem, shell or network; only the supplied task packet and visible history belong to this proposal.')
SETTINGS = {'reasoning_effort': 'high', 'max_new_tokens': 3072, 'maximum_context_tokens': 16384, 'sampling_seed': None}
TIMEOUT_S = 240


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def command(executable):
    return [str(executable), *FIXED_FLAGS, '--model', MODEL, '--settings', SETTINGS_OVERRIDE, '--system-prompt', SYSTEM_PROMPT,
            '--json-schema', json.dumps(SCHEMA, separators=(',', ':')), '--effort', 'high']


def run_cli(executable, tokenizer, request, work, *, runner=subprocess.Popen):
    """One fresh process. Retain raw output and measured cost even on rejection."""
    executable = executable or DEFAULT_EXECUTABLE
    work = Path(work); work.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    record = {'status': 'PREPARING', 'started_at_utc': datetime.now(timezone.utc).isoformat(), 'backend': BACKEND,
              'requested_model': MODEL, 'seed_control_available': False, 'sampling_seed': None, 'timeout_seconds': TIMEOUT_S,
              'native_item_types': [], 'model_call_issued': False}
    response = {'native_tools': [], 'model': {'variant': 'Claude_teacher', 'requested_model': MODEL, 'base_model': MODEL,
                                               'source_role': ROLE, 'teacher_interface_version': VERSION, 'backend': BACKEND,
                                               'model_identity_scope': 'Requested catalog slug through Claude CLI print mode; provider checkpoint and sampling seed unavailable',
                                               'settings': dict(SETTINGS)}}
    usage = {'all_public_usage_events': [], 'public_cli_usage': None, 'request_mode': MODE, 'output_format': 'literal_span_edits_json',
             'max_new_tokens': 3072, 'maximum_context_tokens': 16384, 'sampling_seed': None, 'child_CPU_accounting_available': False,
             'output_budget_scope': 'Exact raw producer JSON plus EOS uses the pinned policy tokenizer. Provider usage and cost are retained separately.'}
    cwd = None
    try:
        save(work / 'request.json', request); save(work / 'span_schema.json', SCHEMA)
        prompt = proposal_prompt(request)
        budget = prompt_token_budget(tokenizer, prompt, {'max_context_tokens': 16384, 'max_new_tokens': 3072})
        save(work / 'token_budget.json', budget); usage['policy_token_budget'] = budget
        if not budget['fits_with_full_output_reserve']:
            raise ValueError('Complete teacher source/contract/history exceeds 16k with 3072 reserve; no inference issued')
        argv = command(executable); record.update(argv=argv, status='RUNNING')
        CWD_ROOT.mkdir(parents=True, exist_ok=True)
        cwd = Path(tempfile.mkdtemp(prefix='span_', dir=CWD_ROOT)); record['cwd'] = str(cwd)
        save(work / 'invocation.json', record)
        with (work / 'stdout.json').open('w') as out, (work / 'stderr.log').open('w') as err:
            process = runner(argv, stdin=subprocess.PIPE, stdout=out, stderr=err, text=True, cwd=str(cwd))
            record.update(pid=process.pid, model_call_issued=True); save(work / 'invocation.json', record)
            try:
                process.communicate(prompt, timeout=max(.01, TIMEOUT_S - (time.monotonic() - began)))
                record.update(returncode=process.returncode, status='COMPLETED' if process.returncode == 0 else 'FAILED')
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate(); record.update(returncode=None, status='TIMEOUT')
        record['cwd_entries_after'] = sorted(p.name for p in cwd.iterdir())
        try: envelope = json.loads((work / 'stdout.json').read_text() or 'null')
        except ValueError: envelope = None
        result_text = None
        if isinstance(envelope, dict):
            event = {'usage': envelope.get('usage'), 'modelUsage': envelope.get('modelUsage'), 'total_cost_usd': envelope.get('total_cost_usd'),
                     'duration_api_ms': envelope.get('duration_api_ms'), 'num_turns': envelope.get('num_turns'), 'is_error': envelope.get('is_error'),
                     'stop_reason': envelope.get('stop_reason'), 'terminal_reason': envelope.get('terminal_reason')}
            usage['all_public_usage_events'] = [event]; usage['public_cli_usage'] = event if envelope.get('usage') else None
            record['actual_models'] = sorted((envelope.get('modelUsage') or {}).keys()); record['num_turns'] = envelope.get('num_turns')
            structured = envelope.get('structured_output'); record['structured_output_present'] = isinstance(structured, dict)
            turns = envelope.get('num_turns') or 1
            tool_turns = turns > 3 or bool((envelope.get('subagent_stats') or {}).get('spawned')) or bool(envelope.get('permission_denials'))
            record['native_item_types'] = ['multi_turn_tool_use'] if tool_turns else []
            if envelope.get('is_error'):
                record['status'] = 'PROVIDER_ERROR'; record['provider_result'] = str(envelope.get('result'))[:500]
                record['provider_pause'] = provider_pause(record['provider_result'])
            if tool_turns:
                record['status'] = 'REJECTED_NATIVE_TOOL_USE'; response['native_tools'] = record['native_item_types']
            result_text = json.dumps(structured) if isinstance(structured, dict) else envelope.get('result')
        if record['status'] != 'COMPLETED': raise RuntimeError('Isolated Claude span producer did not complete without native capabilities: ' + record['status'])
        if usage['public_cli_usage'] is None:
            record['status'] = 'PUBLIC_USAGE_UNAVAILABLE'; raise RuntimeError('Provider cost metadata is unavailable; retain raw response and pause')
        if not isinstance(result_text, str): raise RuntimeError('Claude envelope carries no result text')
        raw, fenced = strip_single_fence(result_text); record['fence_stripped'] = fenced
        (work / 'answer.json').write_text(raw); response['raw_proposal_text'] = raw
        count = len(tokenizer(raw, add_special_tokens=False)['input_ids']) + 1
        budget.update(completion_tokens_including_EOS=count, actual_total_tokens=budget['prompt_tokens'] + count, output_within_budget=count <= 3072)
        save(work / 'token_budget.json', budget)
        if count > 3072:
            record['status'] = 'REJECTED_SHARED_PRODUCER_OUTPUT_BUDGET'; raise ValueError('Exact raw span JSON plus EOS exceeds 3072; output and public cost retained')
        proposal = validate_proposal(json.loads(raw), request['task_packet']['allowed_paths'])
        if time.monotonic() - began > TIMEOUT_S:
            record['status'] = 'LATE_RESPONSE_RETAINED'; raise TimeoutError('Producer 240 s elapsed; response never compiled')
        response['proposal'] = proposal
    except Exception as exc:
        response['error'] = type(exc).__name__ + ': ' + str(exc)
        if record['status'] in ('PREPARING', 'COMPLETED'): record['status'] = 'REJECTED_PROPOSAL_OR_CONTEXT'
    finally:
        if cwd is not None: shutil.rmtree(cwd, ignore_errors=True)
        if (work / 'answer.json').is_file(): response['raw_proposal_text'] = (work / 'answer.json').read_text()
        usage['server_wall_seconds'] = time.monotonic() - began; usage['model_call_issued'] = record['model_call_issued']
        response['usage'] = usage; response['producer_status'] = record['status']
        record.update(ended_at_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=usage['server_wall_seconds'], response=response)
        save(work / 'invocation.json', record)
    return response
