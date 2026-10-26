"""Collect the frozen sixteen span proposals, compile and preselect; zero physical runs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


def read(path): return json.loads(Path(path).read_text())
def save(path, value): Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def process_response(response, request, base_source, tokenizer, directory):
    from src.train_span_proposer import ROLE, MODE, validate_proposal, compile_proposal, mapped_student_request
    from src.student_interface import canonical_action, encode_policy_action, PolicyBudgetError
    if (response.get('native_tools') != [] or response.get('model', {}).get('source_role') != ROLE
            or response.get('usage', {}).get('request_mode') != MODE):
        raise RuntimeError('Producer identity/tool isolation was not established')
    if response.get('error'):
        unknown = response.get('producer_status') in ('TIMEOUT', 'FAILED', 'RUNNING', 'PUBLIC_USAGE_UNAVAILABLE')
        return {'status': 'UNKNOWN_PRODUCER_PAUSE' if unknown else 'PRODUCER_FAILED_RAW_AND_COST_RETAINED',
                'error': response['error'], 'dispatch_pause_required': unknown}
    raw = response['raw_proposal_text']; parsed = json.loads(raw)
    if parsed != response.get('proposal') or len(tokenizer(raw, add_special_tokens=False)['input_ids']) + 1 > 3072:
        return {'status': 'RAW_PROPOSAL_FORMAT_OR_PRODUCER_BUDGET_REJECTED'}
    proposal = validate_proposal(parsed, base_source)
    try: compiled = compile_proposal(base_source, proposal)
    except ValueError as exc: return {'status': 'LITERAL_MATCH_REJECTED_NO_PHYSICS', 'error': str(exc)}
    save(directory / 'compiled.json', compiled)
    student = mapped_student_request(request); save(directory / 'student_request.json', student)
    action = canonical_action(compiled['patch'], student); (directory / 'student_action.json').write_text(action + '\n')
    try: encoded = encode_policy_action(tokenizer, student, compiled['patch'], 16384, 1024)
    except PolicyBudgetError as exc:
        save(directory / 'student_budget.json', exc.details)
        return {'status': 'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS', 'student_budget': exc.details}
    counts = {'prompt_tokens': encoded.prompt_tokens, 'completion_tokens_including_EOS': encoded.completion_tokens,
              'total_tokens': len(encoded.input_ids), 'max_new_tokens': 1024, 'maximum_context_tokens': 16384}
    save(directory / 'student_budget.json', counts)
    return {'status': 'COMPILED_STUDENT_FIT_PROPOSAL_ONLY', 'student_budget': counts}


def run(args):
    bundle = args.collection.resolve().parent; sys.path.insert(0, str(bundle / 'interface'))
    from src.train_span_bundle import load_bundle, validate_tokenizer
    from src.train_span_proposer import MODE, VERSION, ROLE, source_identity
    manifest = load_bundle(args.collection)
    if Path(__file__).read_bytes() != (bundle / 'interface/collector.py').read_bytes():
        raise ValueError('Run the exact frozen proposal collector')
    if args.validate_only:
        return {'status': 'VALIDATED_FROZEN_SPAN_COLLECTION_NO_REQUESTS', 'planned_proposals': 16, 'new_model_calls': 0, 'new_physical_calls': 0}
    def get(url):
        with urllib.request.urlopen(url, timeout=10) as response: return json.loads(response.read())
    transport = get('http://127.0.0.1:8116/transport-health')
    health = get('http://127.0.0.1:8116/spans/health')
    expected_sha = hashlib.sha256(args.collection.read_bytes()).hexdigest()
    if (transport.get('status') != 'READY' or transport.get('literal_span_route_enabled') is not True
            or transport.get('global_teacher_slots') != 2 or health.get('status') != 'READY'
            or health.get('collection_sha256') != expected_sha or health.get('teacher_interface_version') != VERSION
            or health.get('source_role') != ROLE or health.get('max_new_tokens') != 3072
            or health.get('max_context_tokens') != 16384 or health.get('native_tools_enabled') is not False):
        raise ValueError('Exact frozen broker and shared two-slot route must be READY before dispatch')
    from transformers import AutoTokenizer
    validate_tokenizer(args.tokenizer, bundle)
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id != 151645: raise ValueError('Unexpected shared tokenizer EOS')
    output = Path(manifest['output_root']); output.mkdir(parents=True, exist_ok=False)
    save(output / 'collection.json', manifest); save(output / 'route_preflight.json', {'transport': transport, 'broker': health})
    contexts = {c['initial_state_id']: c for c in manifest['contexts']}
    seen = {sid: {source_identity(read(bundle / c['initial_state'])['base_source']): 'initial_source'} for sid, c in contexts.items()}
    matrix = [{'initial_state_id': c['initial_state_id'], 'trial_id': trial, 'status': 'NOT_RUN'}
              for c in manifest['contexts'] for trial in manifest['sampling']['trials']]
    save(output / 'matrix.json', matrix)
    deadline = time.monotonic() + manifest['maximum_dispatch_hours'] * 3600
    def proposal(row):
        context = contexts[row['initial_state_id']]; request = read(bundle / context['teacher_request'])
        state = read(bundle / context['initial_state']); directory = output / row['initial_state_id'] / ('trial_' + str(row['trial_id']))
        directory.mkdir(parents=True, exist_ok=False)
        body = {'mode': MODE, 'initial_state_id': row['initial_state_id'], 'trial_id': row['trial_id'], 'request': request}
        save(directory / 'request.json', body); began = time.monotonic()
        record = {**row, 'started_at_utc': datetime.now(timezone.utc).isoformat(), 'attempt_directory': str(directory),
                  'new_physical_calls': 0, 'new_training_examples': 0}
        try:
            rpc = urllib.request.Request(manifest['endpoint'], data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(rpc, timeout=250) as answer: raw = answer.read().decode(); http = answer.status
            except urllib.error.HTTPError as exc: raw = exc.read().decode(); http = exc.code
            (directory / 'response.json').write_text(raw + '\n'); response = json.loads(raw)
            record.update(http_status=http, inference_id=response.get('inference_id'), usage=response.get('usage'), model=response.get('model'))
            if response.get('collection_sha256') != expected_sha:
                raise RuntimeError('Actual broker collection identity is unknown')
            if time.monotonic() - began > 240:
                record.update(status='LATE_PROPOSAL_RETAINED_NO_COMPILATION', dispatch_pause_required=True)
            else: record.update(process_response(response, request, state['base_source'], tokenizer, directory))
        except Exception as exc:
            record.update(status='UNKNOWN_TRANSPORT_OR_COMPILER_PAUSE', error=type(exc).__name__ + ': ' + str(exc), dispatch_pause_required=True)
        record.update(ended_at_utc=datetime.now(timezone.utc).isoformat(), client_wall_seconds=time.monotonic() - began)
        save(directory / 'attempt.json', record); return record
    pending = iter(matrix); active = {}; attempts = []; paused = False; exhausted = False
    with ThreadPoolExecutor(max_workers=2) as workers:
        while active or not exhausted:
            while not paused and not exhausted and len(active) < 2 and time.monotonic() < deadline:
                row = next(pending, None)
                if row is None: exhausted = True; break
                row['status'] = 'DISPATCHED'; active[workers.submit(proposal, dict(row))] = row
            if not active: break
            completed, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in completed:
                row = active.pop(future); record = future.result(); sid = row['initial_state_id']
                if record['status'] == 'COMPILED_STUDENT_FIT_PROPOSAL_ONLY':
                    key = source_identity(read(Path(record['attempt_directory']) / 'compiled.json')['candidate_source'])
                    if key in seen[sid]: record.update(status='SEMANTIC_DUPLICATE_BEFORE_PHYSICS', duplicate_of=seen[sid][key])
                    else: seen[sid][key] = record['trial_id']
                    save(Path(record['attempt_directory']) / 'attempt.json', record)
                row.update(status=record['status'], attempt_directory=record['attempt_directory'])
                paused |= record.get('dispatch_pause_required', False); attempts.append(record)
            save(output / 'matrix.json', matrix); save(output / 'attempts.json', attempts)
            if paused or time.monotonic() >= deadline: exhausted = True
    fit_terminals = {source_identity(read(Path(row['attempt_directory']) / 'compiled.json')['candidate_source'])
        for row in matrix if row['status'] in ('COMPILED_STUDENT_FIT_PROPOSAL_ONLY', 'SEMANTIC_DUPLICATE_BEFORE_PHYSICS')}
    completion = {'status': 'PAUSED_UNKNOWN_OR_LATE' if paused else 'COMPLETED_FIXED_PROPOSAL_MATRIX' if len(attempts) == 16 else 'DISPATCH_WINDOW_ENDED_WITH_NOT_RUN',
        'planned_proposals': 16, 'returned_attempts': len(attempts), 'not_run': sum(r['status'] == 'NOT_RUN' for r in matrix),
        'unique_student_fit_terminal_programs_within_state': sum(r['status'] == 'COMPILED_STUDENT_FIT_PROPOSAL_ONLY' for r in matrix),
        'unique_student_fit_terminal_program_ASTs_across_states': len(fit_terminals),
        'initial_program_ASTs': len({source_identity(read(bundle / c['initial_state'])['base_source']) for c in manifest['contexts']}),
        'source_lineages': 1, 'reported_actual_model_calls': sum((r.get('usage') or {}).get('model_call_issued', False) for r in attempts),
        'initial_contexts_reused': 2, 'independent_contexts_added': 0, 'new_physical_calls': 0,
        'new_training_examples': 0, 'formal_trained_models': 0, 'ended_at_utc': datetime.now(timezone.utc).isoformat()}
    save(output / 'completion.json', completion); return completion


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--collection', type=Path, required=True); p.add_argument('--tokenizer', type=Path)
    g = p.add_mutually_exclusive_group(required=True); g.add_argument('--validate-only', action='store_true'); g.add_argument('--execute', action='store_true')
    print(json.dumps(run(p.parse_args()), indent=2), flush=True)
