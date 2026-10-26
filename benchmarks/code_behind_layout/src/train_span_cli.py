"""An independent isolated GPT CLI producer with a 3072-token span schema."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

from src.model_adapter import prompt_token_budget
from src.train_span_proposer import MODE, ROLE, SCHEMA, VERSION, proposal_prompt, validate_proposal

DISABLED_FEATURES = ['shell_tool', 'unified_exec', 'apps', 'plugins', 'memories', 'multi_agent',
    'multi_agent_v2', 'computer_use', 'browser_use', 'browser_use_external', 'image_generation',
    'view_image', 'hooks', 'workspace_dependencies', 'tool_suggest', 'in_app_browser',
    'in_app_chat', 'in_app_local_automation', 'code_mode', 'code_mode_host', 'skill_search']


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def command(executable, work):
    work = Path(work).resolve()
    argv = [str(executable), 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
        '--sandbox', 'read-only', '--json', '--color', 'never', '--model', 'gpt-6.1-sol', '-C', str(work),
        '-c', 'approval_policy="never"', '-c', 'web_search="disabled"',
        '-c', 'model_reasoning_effort="high"', '-c', 'model_reasoning_summary="none"',
        '-c', 'show_raw_agent_reasoning=false', '-c', 'project_doc_max_bytes=0', '-c', 'mcp_servers={}',
        '-c', 'skills.bundled.enabled=false', '-c', 'skills.include_instructions=false']
    for feature in DISABLED_FEATURES: argv.extend(['--disable', feature])
    return argv + ['--output-schema', str(work / 'span_schema.json'), '--output-last-message', str(work / 'answer.json'), '-']


def inspect_events(path):
    usages = []; native = []; notices = []; started = False
    for line in Path(path).read_text().splitlines():
        event = json.loads(line)
        if event.get('type') == 'turn.started': started = True
        if event.get('type') == 'turn.completed': usages.append(event.get('usage'))
        if event.get('type', '').startswith('item.'):
            item = event.get('item', {}); kind = item.get('type')
            if (kind == 'error' and not started and item.get('message', '').startswith(
                    'Code Mode is unavailable because code-mode host is disabled.')):
                notices.append(item['message']); continue
            if kind not in ('agent_message', 'reasoning'): native.append(kind)
    return {'all_public_usage_events': usages, 'native_item_types': sorted(set(native), key=str),
            'disabled_capability_notices': notices}


def run_cli(executable, tokenizer, request, work, *, runner=subprocess.Popen):
    """One fresh process. Retain raw output and measured cost even on rejection."""
    work = Path(work); work.mkdir(parents=True, exist_ok=False)
    began = time.monotonic(); record = {'status': 'PREPARING', 'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'requested_model': 'gpt-6.1-sol', 'seed_control_available': False, 'sampling_seed': None,
        'timeout_seconds': 240, 'native_item_types': [], 'model_call_issued': False}
    response = {'native_tools': [], 'model': {'variant': 'GPT_teacher', 'requested_model': 'gpt-6.1-sol',
        'base_model': 'gpt-6.1-sol', 'source_role': ROLE, 'teacher_interface_version': VERSION,
        'model_identity_scope': 'Requested catalog slug; provider checkpoint and sampling seed unavailable',
        'settings': {'reasoning_effort': 'high', 'max_new_tokens': 3072, 'maximum_context_tokens': 16384, 'sampling_seed': None}}}
    usage = {'all_public_usage_events': [], 'public_cli_usage': None, 'request_mode': MODE,
        'output_format': 'literal_span_edits_json', 'max_new_tokens': 3072, 'maximum_context_tokens': 16384,
        'sampling_seed': None, 'child_CPU_accounting_available': False,
        'output_budget_scope': 'Exact raw producer JSON plus EOS uses the pinned policy tokenizer. Provider usage, including reasoning, is retained separately.'}
    try:
        save(work / 'request.json', request); save(work / 'span_schema.json', SCHEMA)
        prompt = proposal_prompt(request)
        budget = prompt_token_budget(tokenizer, prompt, {'max_context_tokens': 16384, 'max_new_tokens': 3072})
        save(work / 'token_budget.json', budget); usage['policy_token_budget'] = budget
        if not budget['fits_with_full_output_reserve']:
            raise ValueError('Complete teacher source/contract/history exceeds 16k with3072reserve; no inference issued')
        argv = command(executable, work); record.update(argv=argv, status='RUNNING')
        save(work / 'invocation.json', record)
        with (work / 'events.jsonl').open('w') as events, (work / 'stderr.log').open('w') as errors:
            process = runner(argv, stdin=subprocess.PIPE, stdout=events, stderr=errors, text=True)
            record.update(pid=process.pid, model_call_issued=True); save(work / 'invocation.json', record)
            try:
                process.communicate(prompt, timeout=max(.01, 240 - (time.monotonic() - began)))
                record.update(returncode=process.returncode, status='COMPLETED' if process.returncode == 0 else 'FAILED')
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate(); record.update(returncode=None, status='TIMEOUT')
        telemetry = inspect_events(work / 'events.jsonl'); record.update(telemetry)
        usage['all_public_usage_events'] = telemetry['all_public_usage_events']
        usage['public_cli_usage'] = telemetry['all_public_usage_events'][-1] if telemetry['all_public_usage_events'] else None
        if telemetry['native_item_types']:
            record['status'] = 'REJECTED_NATIVE_TOOL_USE'; response['native_tools'] = telemetry['native_item_types']
        if record['status'] != 'COMPLETED': raise RuntimeError('Isolated span producer did not complete without native capabilities')
        if usage['public_cli_usage'] is None:
            record['status'] = 'PUBLIC_USAGE_UNAVAILABLE'; raise RuntimeError('Provider cost metadata is unavailable; retain raw response and pause')
        raw = (work / 'answer.json').read_text(); response['raw_proposal_text'] = raw
        count = len(tokenizer(raw, add_special_tokens=False)['input_ids']) + 1
        budget.update(completion_tokens_including_EOS=count, actual_total_tokens=budget['prompt_tokens'] + count,
                      output_within_budget=count <= 3072)
        save(work / 'token_budget.json', budget)
        if count > 3072:
            record['status'] = 'REJECTED_SHARED_PRODUCER_OUTPUT_BUDGET'; raise ValueError('Exact raw span JSON plus EOS exceeds3072; output and public cost retained')
        proposal = validate_proposal(json.loads(raw), request['task_packet']['allowed_paths'])
        if time.monotonic() - began > 240:
            record['status'] = 'LATE_RESPONSE_RETAINED'; raise TimeoutError('Producer240s elapsed; response never compiled')
        response['proposal'] = proposal
    except Exception as exc:
        response['error'] = type(exc).__name__ + ': ' + str(exc)
        if record['status'] in ('PREPARING', 'COMPLETED'): record['status'] = 'REJECTED_PROPOSAL_OR_CONTEXT'
    finally:
        if (work / 'answer.json').is_file(): response['raw_proposal_text'] = (work / 'answer.json').read_text()
        usage['server_wall_seconds'] = time.monotonic() - began
        usage['model_call_issued'] = record['model_call_issued']
        response['usage'] = usage
        response['producer_status'] = record['status']
        record.update(ended_at_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=usage['server_wall_seconds'], response=response)
        save(work / 'invocation.json', record)
    return response
