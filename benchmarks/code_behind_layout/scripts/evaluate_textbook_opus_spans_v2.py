"""Independent physical acceptance of Claude literal-span teacher proposals over multi-state textbook parents (E4 stage 2).

v2 of scripts/evaluate_textbook_opus_spans.py. Differences: parents may hold several declared initial states (natural
plan/order variants or injected fault states) and may be baseline-only v2 collections; the number of fresh trials per
context comes from the frozen proposal bundle; and the equivalent-best SFT representative rule is bound to the actual
Claude trial order (field trial_id) instead of the parent rule collection's rule_id order, which v1 bound by mistake.

No model calls. Adapted from scripts/evaluate_train_span_proposals.py for the Claude producer identity
(src/train_span_opus_cli.py), N parent rule collections (one natural initial state each) and a configurable
number of concurrent two-CPU point calls. Preparation and baseline control dispatch no physical jobs; every
proposal's raw response is re-verified, deterministically recompiled and screened against the student budget
before any of its nine points is reserved. Unknowns stop new dispatch and are never retried automatically.

    --prepare --proposal <bundle>/collection.json --folder <acceptance dir> --output-root runs/train_collection/<id>_physical [--workers 4 --hours 12]
    --freeze --plan <acceptance dir>/acceptance.json
    --execute --plan <acceptance dir>/acceptance.json
"""
import argparse
import ast
from collections import Counter
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import evaluate_matched_t0_proposals as physical
from scripts.collect_planning_trajectories import workspace
from scripts.derive_training_selection_v2 import frozen_base_selection
from scripts.prepare_student_data import bound_registry
from scripts.run_frozen_training_collection import load_definition, frozen_module
from scripts import collect_training_v2
import copy
from scripts.train_collection_queue import resource_sample
from src.model_adapter import prompt_token_budget
from src.student_interface import CONTEXT_VERSION, canonical_action, derive_matched_samples, encode_policy_action, student_request, PolicyBudgetError
from src.train_span_proposer import MODE, VERSION, compile_proposal, mapping_proof, proposal_prompt, source_identity, validate_proposal
from src.train_span_opus_cli import ROLE as PRODUCER_ROLE, MODEL, BACKEND, SETTINGS
from src.training import TrustedPhysicalStore, admit_candidates, sample_identity
from src.training_selection_v2 import VERSION as SELECTION_VERSION

ROLE = 'literal_span_Claude_physical_followup_train_only_v2'
CODE = tuple(dict.fromkeys((*physical.CODE, 'scripts/evaluate_textbook_opus_spans_v2.py', 'scripts/collect_textbook_opus_spans.py',
    'scripts/prepare_textbook_opus_span_collection_v2.py', 'scripts/prepare_textbook_opus_span_collection.py', 'scripts/collect_training_v2.py', 'src/train_span_opus_cli.py', 'src/train_span_proposer.py', 'src/opus_cli_adapter.py',
    'src/student_interface.py', 'src/training.py', 'src/training_selection_v2.py', 'src/model_adapter.py')))
read, save, now, module = physical.read, physical.save, physical.now, physical.module


def running_containers():
    import subprocess
    return subprocess.run(['docker', 'ps', '-q'], capture_output=True, text=True).stdout.count('\n')


def load_parent(path):
    manifest = read(path)
    return collect_training_v2.load(Path(path).resolve()) if manifest.get('collector') == 'scripts/collect_training_v2.py' else load_definition(path)


def span_rule(parent_rule, trials):
    if parent_rule.get('status') != 'frozen' or not parent_rule.get('version'): raise ValueError('Start from the real frozen parent label rule')
    if 'sft_selection' in parent_rule: raise ValueError('Start from the original unique-best v1 rule')
    if not trials or list(trials) != list(range(1, len(trials) + 1)): raise ValueError('Declare the actual fresh trial order')
    return {**copy.deepcopy(parent_rule), 'version': parent_rule['version'] + '__' + SELECTION_VERSION, 'parent_rule_version': parent_rule['version'],
            'sft_selection': {'version': SELECTION_VERSION, 'actual_trial_field': 'trial_id', 'declared_trial_order': list(trials),
                              'change_scope': 'Only equivalent-best SFT representative selection (earliest actual Claude trial); original feasibility and comparison thresholds unchanged'}}


def load_bundle(path):
    path = Path(path).resolve(); root = path.parent; manifest = read(path); identity = read(root / 'freeze_identity.json')
    if 'collection.json' not in identity: raise ValueError('Proposal collection is not frozen')
    for name, digest in identity.items():
        file = root / name
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest: raise ValueError('Frozen proposal bundle differs: ' + name)
    if (manifest.get('status') != 'frozen' or manifest.get('role') != 'train_proposal_collection' or manifest.get('source_role') != PRODUCER_ROLE
            or manifest.get('teacher_interface_version') != VERSION or manifest['sampling'].get('backend') != BACKEND or manifest['sampling'].get('model') != MODEL
            or not manifest['sampling'].get('trials') or manifest['sampling']['trials'] != list(range(1, len(manifest['sampling']['trials']) + 1))
            or manifest.get('planned_proposals') != len(manifest['sampling']['trials']) * len(manifest['contexts'])):
        raise ValueError('Only the frozen Claude textbook span collection is supported')
    return manifest


def proposal_definition(path):
    path = Path(path).resolve(); bundle = path.parent; plan = load_bundle(path)
    parents = {}; contexts = []
    for entry in plan['contexts']:
        parent_path = ROOT / 'runtime/train_collections' / entry['parent_collection_id'] / 'collection.json'
        manifest, frozen, states, files = load_parent(parent_path)
        if manifest != read(bundle / entry['parent_collection']): raise ValueError('Parent physical collection identity changed')
        state = read(bundle / entry['initial_state'])
        actual, = [s for s in states if s['initial_state_id'] == state['initial_state_id']]
        if actual != state or state['origin'] not in ('natural', 'injected'): raise ValueError('Retain the real complete declared initial state')
        effective = bound_registry(frozen, read(bundle / entry['effective_registry']))
        original = read(bundle / entry['original_request']); teacher = read(bundle / entry['teacher_request'])
        mapping_proof(original, teacher)
        # Rule collections run the plain collector (no frozen interface entrypoint); bind the exact collector snapshot that produced the baselines.
        collector = frozen_module(parent_path) if manifest.get('frozen_collector_entrypoint') else module(Path(manifest['output_root']) / 'collector_snapshot.py', 'parent_collector_' + entry['parent_collection_id'])
        parents[entry['parent_collection_id']] = {'manifest': manifest, 'registry': effective, 'states': states, 'files': files, 'collector': collector}
        contexts.append({**entry, 'parent_collection': entry['parent_collection_id'], 'state': state, 'base_source': state['base_source'],
                         'original_request_value': original, 'teacher_request_value': teacher})
    registry = physical.merge_registries([p['registry'] for p in parents.values()])
    if len(registry['configurations']) != 9 * len(parents): raise ValueError('Preserve one complete nine-point domain per parent')
    return plan, parents, contexts, registry


def prepare(proposal, folder, output_root, hours=12, workers=6):
    plan, parents, contexts, _ = proposal_definition(proposal)
    if type(hours) not in (int, float) or not math.isfinite(hours) or hours <= 0: raise ValueError('Declare one finite dispatch window')
    folder = Path(folder).resolve(); folder.mkdir(parents=True, exist_ok=False)
    output_root = Path(output_root).resolve(); output_root.relative_to(ROOT / 'runs/train_collection')
    for name in CODE:
        target = folder / 'interface' / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
    (folder / 'interface/base_selection.py').write_text(frozen_base_selection((ROOT / 'src/training.py').read_text()))
    for name, parent in parents.items():
        save(folder / 'rules' / (name + '.json'), span_rule(read(parent['manifest']['label_rule_path']), plan['sampling']['trials']))
    for context in contexts:
        work = folder / 'contexts' / context['initial_state_id']
        save(work / 'task_packet.json', context['original_request_value']['task_packet'])
        save(work / 'visible_history.json', context['original_request_value']['visible_history'])
    n = len(contexts); trials = list(plan['sampling']['trials'])
    definition = {'status': 'DRAFT', 'role': ROLE, 'proposal_collection': str(Path(proposal).resolve()),
                  'proposal_collection_sha256': hashlib.sha256(Path(proposal).read_bytes()).hexdigest(), 'created_at_utc': now(), 'evidence_root': str(ROOT),
                  'output_root': str(output_root), 'contexts': [{'initial_state_id': c['initial_state_id'], 'parent_collection': c['parent_collection']} for c in contexts],
                  'context_origins': {c['initial_state_id']: c['state']['origin'] for c in contexts},
                  'trials': trials, 'declared_proposals': len(trials) * n, 'independent_contexts': n, 'source_lineages': 1,
                  'physical': {'workers': int(workers), 'cpus_per_job': 2, 'memory_GiB_per_job': 8, 'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720,
                               'maximum_dispatch_hours': hours, 'maximum_new_candidate_points': 9 * len(trials) * n, 'maximum_new_baseline_points': 0,
                               'actual_busy_cores_plus_new_limit': 24, 'RAM_used_GiB_limit': 190, 'minimum_free_disk_GiB': 4, 'max_running_containers_before_dispatch': 13},
                  'implementation_files': list(CODE), 'producer': {'backend': BACKEND, 'model': MODEL, 'source_role': PRODUCER_ROLE, 'settings': SETTINGS},
                  'raw_input_policy': 'Only this frozen Claude proposal cohort; no other candidate pools.',
                  'selection': 'Unchanged Point/Family scopes, baseline minimum effect, numerical ties and v2 earliest equivalent-best actual trial.',
                  'student': {'version': CONTEXT_VERSION, 'max_context_tokens': 16384, 'max_new_tokens': 1024},
                  'baseline_policy': 'The parent rule collection\'s actual nine-point original-source baseline per context; ROOT evidence paths, no fresh baseline calls.',
                  'failure_policy': 'Durable point reservation, unknown stops new dispatch, no automatic retry; the full denominator/NOT_RUN and costs are retained.',
                  'task_identity_mapping': 'Retain raw teacher task_id; use frozen physical contract.task_id for backend admission.'}
    save(folder / 'acceptance.json', definition); return definition


def verify_code(path, definition):
    for name in definition['implementation_files']:
        if (ROOT / name).read_bytes() != (Path(path).parent / 'interface' / name).read_bytes(): raise ValueError('Acceptance implementation changed: ' + name)
    if (Path(path).parent / 'interface/base_selection.py').read_text() != frozen_base_selection((ROOT / 'src/training.py').read_text()):
        raise ValueError('Inherited complete selection functions changed')


def load_acceptance(path, require_frozen=True):
    path = Path(path).resolve(); definition = read(path)
    if definition.get('role') != ROLE or definition.get('status') != ('frozen' if require_frozen else 'DRAFT'): raise ValueError('Use the reviewed Claude span physical acceptance plan')
    n = definition['independent_contexts']; trials = definition['trials']
    if (not trials or definition['declared_proposals'] != len(trials) * n or trials != list(range(1, len(trials) + 1)) or definition['source_lineages'] != 1
            or definition['implementation_files'] != list(CODE) or definition['evidence_root'] != str(ROOT)): raise ValueError('Keep the declared cohort and private ROOT evidence endpoint')
    phys = definition['physical']; hours = phys['maximum_dispatch_hours']
    if (phys['cpus_per_job'] != 2 or phys['memory_GiB_per_job'] != 8 or phys['generation_timeout_seconds'] != 240 or phys['evaluator_timeout_seconds'] != 720
            or phys['maximum_new_candidate_points'] != 9 * len(trials) * n or phys['maximum_new_baseline_points'] != 0 or not 1 <= phys['workers'] <= 10
            or phys.get('max_running_containers_before_dispatch') != 13
            or type(hours) not in (int, float) or not math.isfinite(hours) or hours <= 0): raise ValueError('Physical resource/window limits changed')
    verify_code(path, definition)
    plan, parents, contexts, registry = proposal_definition(definition['proposal_collection'])
    if hashlib.sha256(Path(definition['proposal_collection']).read_bytes()).hexdigest() != definition['proposal_collection_sha256']: raise ValueError('Original proposal freeze identity changed')
    if definition['contexts'] != [{'initial_state_id': c['initial_state_id'], 'parent_collection': c['parent_collection']} for c in contexts]: raise ValueError('Context assignment changed')
    if list(plan['sampling']['trials']) != trials: raise ValueError('Declared trials differ from the frozen proposal bundle')
    for name, parent in parents.items():
        if read(path.parent / 'rules' / (name + '.json')) != span_rule(read(parent['manifest']['label_rule_path']), trials): raise ValueError('Comparison thresholds changed')
    for context in contexts:
        work = path.parent / 'contexts' / context['initial_state_id']
        context.update(materialized_task_packet=str(work / 'task_packet.json'), materialized_visible_history=str(work / 'visible_history.json'))
        if read(work / 'task_packet.json') != context['original_request_value']['task_packet'] or read(work / 'visible_history.json') != context['original_request_value']['visible_history']:
            raise ValueError('Baseline control must reproduce the exact original packet/history')
    if require_frozen and any(p.stat().st_mode & 0o222 for p in [path.parent, *path.parent.rglob('*')]): raise ValueError('Frozen acceptance files must be read-only')
    return definition, plan, parents, contexts, registry


def freeze(path):
    path = Path(path).resolve(); load_acceptance(path, False); definition = read(path)
    definition.update(status='frozen', frozen_at_utc=now()); save(path, definition)
    for p in sorted(path.parent.rglob('*'), key=lambda p: len(p.parts), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    path.parent.chmod(0o555)
    return {'status': 'FROZEN_CLAUDE_SPAN_PHYSICAL_ACCEPTANCE_NO_CALLS', 'new_model_calls': 0, 'new_physical_calls': 0}


def verify_raw(plan, context, trial, directory, tokenizer, proposal_sha):
    directory = Path(directory); attempt = read(directory / 'attempt.json'); body = read(directory / 'request.json')
    expected = {'mode': MODE, 'initial_state_id': context['initial_state_id'], 'trial_id': trial, 'request': context['teacher_request_value']}
    if json.dumps(body) != json.dumps(expected) or (attempt['initial_state_id'], attempt['trial_id']) != (context['initial_state_id'], trial):
        raise ValueError('Raw trial/context/full request serialization differs from the prospective freeze')
    if not (directory / 'response.json').exists(): raise ValueError('Returned trial lacks its actual raw response; unknown, never a negative')
    response = read(directory / 'response.json'); usage = response.get('usage') or {}; model = response.get('model') or {}
    if (attempt.get('inference_id') != response.get('inference_id') or not response.get('inference_id') or attempt.get('usage') != response.get('usage')
            or attempt.get('model') != response.get('model') or response.get('collection_sha256') != proposal_sha): raise ValueError('Raw inference/usage/model/frozen collection identity differs')
    if (response.get('native_tools') != [] or model.get('source_role') != PRODUCER_ROLE or model.get('teacher_interface_version') != VERSION
            or model.get('requested_model') != MODEL or model.get('backend') != BACKEND or model.get('settings') != SETTINGS
            or usage.get('request_mode') != MODE or usage.get('output_format') != 'literal_span_edits_json'): raise ValueError('Actual producer identity, tool boundary or source-format budget changed')
    if response.get('producer_status') in ('TIMEOUT', 'FAILED', 'RUNNING', 'PUBLIC_USAGE_UNAVAILABLE', 'PROVIDER_ERROR'): raise ValueError('Original producer execution/cost is unknown; pause without a negative')
    stages = {'actual_raw_identity_verified': True}
    if attempt.get('http_status') != 200 or response.get('error'): return {'status': 'ORIGINAL_PRODUCER_REJECTED', 'attempt': attempt, 'stages': stages}
    if (not usage.get('public_cli_usage') or not usage.get('model_call_issued') or not 0 < usage.get('server_wall_seconds', float('inf')) <= 240
            or not 0 < attempt.get('client_wall_seconds', float('inf')) <= 240): raise ValueError('Actual public cost or finite producer/client budget is not established')
    flight = prompt_token_budget(tokenizer, proposal_prompt(body['request']), {'max_new_tokens': 3072, 'max_context_tokens': 16384})
    raw = response['raw_proposal_text']; proposal = json.loads(raw); count = len(tokenizer(raw, add_special_tokens=False)['input_ids']) + 1
    if not flight['fits_with_full_output_reserve'] or count > 3072: return {'status': 'ORIGINAL_PRODUCER_TOKEN_BUDGET_REJECTED', 'attempt': attempt, 'stages': stages}
    recorded = usage.get('policy_token_budget', {})
    if (proposal != response.get('proposal') or recorded.get('prompt_tokens') != flight['prompt_tokens'] or recorded.get('completion_tokens_including_EOS') != count
            or recorded.get('actual_total_tokens') != flight['prompt_tokens'] + count): raise ValueError('Exact raw producer JSON or actual tokenizer accounting differs')
    stages['producer_raw_json_and_3072_budget_verified'] = True
    try: compiled = compile_proposal(context['base_source'], validate_proposal(proposal, context['base_source']))
    except ValueError as exc: return {'status': 'LITERAL_EDIT_REJECTED_NO_PHYSICAL_LABEL', 'attempt': attempt, 'reason': str(exc), 'stages': stages}
    if compiled != read(directory / 'compiled.json'): raise ValueError('Stored compiler proof/result differs from independent deterministic replay')
    stages['deterministic_compile_and_actual_git_bytes_verified'] = True
    try:
        for text in compiled['candidate_source'].values(): ast.parse(text)
    except (SyntaxError, ValueError) as exc: return {'status': 'SOURCE_NOT_PARSEABLE_NO_PHYSICAL_LABEL', 'attempt': attempt, 'reason': str(exc), 'stages': stages}
    stages['candidate_AST_parseable'] = True
    if source_identity(compiled['candidate_source']) == source_identity(context['base_source']): return {'status': 'SEMANTIC_NOOP', 'attempt': attempt, 'stages': stages}
    mapped = student_request({'base_source': context['base_source'], 'visible_contract': body['request']['task_packet'], 'visible_feedback': body['request']['visible_history']}, CONTEXT_VERSION, 16384)
    if read(directory / 'student_request.json') != mapped or (directory / 'student_action.json').read_text() != canonical_action(compiled['patch'], mapped) + '\n':
        raise ValueError('Original compiled ordinary ACTION/source mapping changed')
    return {'status': 'ELIGIBLE_UNIQUE_CHECK_PENDING', 'attempt': attempt, 'source': compiled['candidate_source'], 'patch': compiled['patch'],
            'request': body['request'], 'compiled': compiled, 'raw_directory': str(directory), 'stages': stages}


def candidate_row(context, parent, proposal, trial):
    state = context['state']; task = proposal['request']['task_packet']
    ids = task['visible_configurations']; points = [p for p in parent['registry']['configurations'] if p['configuration_id'] in ids]
    task_ids = {p['contract']['task_id'] for p in points}
    if len(points) != 9 or len(task_ids) != 1: raise ValueError('Preserve the complete independent nine-point physical task')
    visible = {k: v for k, v in task.items() if k != 'visible_sources'}
    visible.update(task_id=next(iter(task_ids)), editable_paths=list(state['base_source']))
    return {'candidate_id': 'literal_span_Claude__' + state['initial_state_id'] + '__trial_' + str(trial), 'initial_state_id': state['initial_state_id'],
            'parent_lineage': state['parent_lineage'], 'split': 'train', 'source_role': 'formal_train', 'origin': state['origin'], 'ancestry': state['ancestry'],
            'pdk_revision': parent['manifest']['pdk_revision'], 'base_source': state['base_source'], 'candidate_source': proposal['source'],
            'candidate_patch': proposal['patch'], 'visible_contract': visible, 'visible_feedback': proposal['request']['visible_history'],
            'proposal_generation': {**proposal['attempt'], 'trial_id': trial, 'proposer_cohort': 'literal_span_Claude_fresh_trials_v2', 'teacher_mode': MODE,
                                    'raw_directory': proposal.get('raw_directory'), 'model_seed_available': False}, 'outcomes': []}


def student_identity_proof(context, row, raw_directory=None):
    raw_request = context['teacher_request_value']
    ordinary = student_request({'base_source': context['base_source'], 'visible_contract': raw_request['task_packet'], 'visible_feedback': raw_request['visible_history']}, CONTEXT_VERSION, 16384)
    final = student_request({k: row[k] for k in ('base_source', 'visible_contract', 'visible_feedback')}, CONTEXT_VERSION, 16384)
    normalized = json.loads(json.dumps(ordinary)); normalized['task_packet']['task_id'] = row['visible_contract']['task_id']
    if normalized != final: raise ValueError('Source/physical contract/history changed beyond the declared backend task_id mapping')
    action = canonical_action(row['candidate_patch'], final) if row['candidate_patch'] else None
    if action is not None and canonical_action(row['candidate_patch'], ordinary) != action: raise ValueError('Backend task identity altered the actual ordinary ACTION')
    return {'raw_teacher_task_id': raw_request['task_packet']['task_id'], 'physical_contract_task_id': row['visible_contract']['task_id'],
            'ordinary_student_request': final, 'ordinary_action_text': action, 'original_raw_directory': raw_directory}


def raw_matrix(plan):
    rows = read(Path(plan['output_root']) / 'matrix.json')
    expected = [(c['initial_state_id'], trial) for c in plan['contexts'] for trial in plan['sampling']['trials']]
    actual = [(r['initial_state_id'], r['trial_id']) for r in rows]
    if actual != expected: raise ValueError('Preserve all proposal slots, order and NOT_RUN cells')
    return {key: row for key, row in zip(actual, rows)}


def scan_returned(definition, plan, parents, contexts, registry, state, output, tokenizer):
    matrix = raw_matrix(plan); save(output / 'original_matrix_snapshot.json', list(matrix.values()))
    save(output / 'effective_registry.json', registry); lookup = {c['initial_state_id']: c for c in contexts}
    seen = {name: {source_identity(c['base_source']): 'initial_source'} for name, c in lookup.items()}
    for cell in state['cells']:
        if cell.get('candidate_file'):
            row = read(output / cell['candidate_file']); seen[cell['initial_state_id']][source_identity(row['candidate_source'])] = row['candidate_id']
    for cell in state['cells']:
        raw = matrix[(cell['initial_state_id'], cell['trial_id'])]; cell['original_proposal_status'] = raw['status']
        if cell['status'] != 'NOT_RUN' or raw['status'] in ('NOT_RUN', 'DISPATCHED'): continue
        context = lookup[cell['initial_state_id']]; parent = parents[context['parent_collection']]
        directory = Path(plan['output_root']) / cell['initial_state_id'] / ('trial_' + str(cell['trial_id']))
        if raw.get('attempt_directory') and Path(raw['attempt_directory']).name != directory.name: raise ValueError('Raw attempt directory changed')
        proposal = verify_raw(plan, context, cell['trial_id'], directory, tokenizer, definition['proposal_collection_sha256'])
        cell['proposal_audit'] = {k: v for k, v in proposal.items() if k not in ('source', 'patch', 'request', 'compiled')}
        if proposal['status'] != 'ELIGIBLE_UNIQUE_CHECK_PENDING': cell['status'] = proposal['status']; continue
        key = source_identity(proposal['source'])
        if key in seen[cell['initial_state_id']]: cell.update(status='SEMANTIC_DUPLICATE_NOT_NEW_SAMPLE', duplicate_of=seen[cell['initial_state_id']][key]); continue
        cell['unique_candidate_AST_verified'] = True
        row = candidate_row(context, parent, proposal, cell['trial_id'])
        proof = student_identity_proof(context, row, str(directory))
        try: encoded = encode_policy_action(tokenizer, proof['ordinary_student_request'], row['candidate_patch'], 16384, 1024)
        except PolicyBudgetError as exc: cell.update(status='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS', student_budget=exc.details); continue
        cell['final_student_1024_16k_verified'] = True
        baselines = physical.baseline_bindings(context, parent, registry, row)
        folder = output / 'candidates' / row['candidate_id']; folder.mkdir(parents=True, exist_ok=False)
        workspace(Path(parent['manifest']['source_pack']), parent['files'], row['candidate_source'], folder / 'source')
        save(folder / 'baseline_adoption.json', baselines); save(folder / 'candidate.json', row); save(folder / 'student_identity_proof.json', proof)
        originals = folder / 'original_proposal'; originals.mkdir()
        for name in ('request.json', 'response.json', 'attempt.json', 'compiled.json', 'student_request.json', 'student_action.json', 'student_budget.json'):
            if (directory / name).exists(): shutil.copyfile(directory / name, originals / name)
        cell.update(status='PHYSICAL_PENDING', candidate_file=str((folder / 'candidate.json').relative_to(output)), parent_collection=context['parent_collection'],
                    baseline_adoption=str((folder / 'baseline_adoption.json').relative_to(output)),
                    student_budget={'prompt_tokens': encoded.prompt_tokens, 'completion_tokens_including_EOS': encoded.completion_tokens, 'total_tokens': len(encoded.input_ids)},
                    points=[{'configuration_id': name, 'status': 'NOT_RUN'} for name in baselines])
        seen[cell['initial_state_id']][key] = row['candidate_id']


def physical_pass(definition, parents, registry, state, output, check_implementation=lambda: None):
    """Up to definition.physical.workers two-CPU point calls under the shared host gate; reservations are never retried."""
    store = TrustedPhysicalStore(ROOT, registry); active = {}; limit = definition['physical']['workers']
    with ThreadPoolExecutor(max_workers=limit) as workers:
        while active or physical.pending_points(state):
            dispatched = False
            for future in list(active):
                if not future.done(): continue
                cell, job = active.pop(future); row = read(output / cell['candidate_file'])
                try:
                    result = future.result(); run = Path(result['run_directory']).resolve()
                    job['evidence_path'] = str((run / 'manifest.json').relative_to(ROOT))
                    baseline = read(output / cell['baseline_adoption'])[job['configuration_id']]
                    point = store._configuration(row, job['configuration_id'])
                    row['outcomes'].append({'configuration_id': job['configuration_id'], 'role': point['domain_role'], 'evidence_path': job['evidence_path'],
                                            'baseline_evidence_path': baseline['evidence_path'], 'baseline_candidate_id': baseline['baseline_candidate_id']})
                    save(output / cell['candidate_file'], row)
                    job['checked'] = store._read_run(job['evidence_path'], row, job['configuration_id'], row['candidate_source'], row['candidate_id'])
                    job.update(status='COMPLETE', returned_at_utc=now())
                except Exception as error:
                    job.update(status='UNKNOWN_NO_RETRY', error=type(error).__name__ + ': ' + str(error), returned_at_utc=now())
                    cell['status'] = 'QUARANTINED_UNKNOWN'; state['status'] = 'PAUSED_UNKNOWN'
                save(output / 'state.json', state)
            if state['status'].startswith('PAUSED'):
                if active: wait(active, return_when=FIRST_COMPLETED, timeout=5); continue
                break
            if datetime.now(timezone.utc) >= datetime.fromisoformat(state['deadline_utc']):
                state['dispatch_window_ended'] = True
                if active: wait(active, return_when=FIRST_COMPLETED, timeout=5); continue
                break
            pending = physical.pending_points(state)
            if pending and len(active) < limit:
                resource = resource_sample(); resource['running_containers'] = running_containers(); state['resource_samples'].append(resource)
                if resource['available_disk_GiB'] < 4:
                    state['status'] = 'PAUSED_STORAGE'
                    if active: wait(active, return_when=FIRST_COMPLETED, timeout=5); continue
                    break
                if resource['actual_busy_cores'] + 2 <= 24 and resource['RAM_used_GiB'] <= 190 and resource['running_containers'] < definition['physical']['max_running_containers_before_dispatch']:
                    check_implementation()
                    cell, job = pending[0]; row = read(output / cell['candidate_file'])
                    point = store._configuration(row, job['configuration_id']); parent = parents[cell['parent_collection']]
                    folder = output / 'candidates' / row['candidate_id'] / 'points' / job['configuration_id']
                    if folder.exists(): job.update(status='UNRESOLVED_EXISTING_POINT_NO_RETRY'); state['status'] = 'PAUSED_UNKNOWN'; continue
                    job.update(status='DISPATCH_RESERVED', reserved_at_utc=now(), resources_before_dispatch=resource)
                    cell['physical_point_reservations'] = cell.get('physical_point_reservations', 0) + 1
                    save(output / 'state.json', state)
                    future = workers.submit(physical.point_call, parent, point, row, (output / cell['candidate_file']).parent / 'source', folder, state['deadline_utc'])
                    active[future] = (cell, job); dispatched = True
            if dispatched: continue
            if active: wait(active, return_when=FIRST_COMPLETED, timeout=5)
            elif pending: time.sleep(5)
    return state


def derive(definition, parents, registry, state, output, tokenizer, plan_folder):
    rows = []; admitted = []; rejections = []; store = TrustedPhysicalStore(ROOT, registry)
    for cell in state['cells']:
        if not cell.get('candidate_file'): continue
        row = read(output / cell['candidate_file']); rows.append(row)
        if not cell.get('points') or not all(p['status'] == 'COMPLETE' for p in cell['points']): continue
        try: admitted.extend(admit_candidates([row], registry, store)); cell['status'] = 'ADMITTED_COMPLETE_DOMAIN'
        except (ValueError, OSError, KeyError) as exc:
            cell['status'] = 'QUARANTINED_ADMISSION'; state['status'] = 'PAUSED_UNKNOWN'; rejections.append({'candidate_id': row['candidate_id'], 'error': str(exc)})
    (output / 'candidates.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    save(output / 'physical_readmission.json', {'status': 'QUARANTINED' if rejections or state['status'] == 'PAUSED_UNKNOWN' else 'READMITTED_ACTUAL_COMPLETE_DOMAINS',
                                                'raw_candidates': len(rows), 'admitted_candidates': len(admitted), 'rejections': rejections, 'unknowns_used_as_negatives': False,
                                                'new_baseline_calls': 0, 'evidence_root': str(ROOT)})
    if state['status'] == 'PAUSED_UNKNOWN': physical.invalidate_derivation(output); return
    unfinished = ('NOT_RUN', 'PHYSICAL_PENDING')
    closed = {c['initial_state_id'] for c in state['cells'] if all(o['status'] not in unfinished for o in state['cells'] if o['initial_state_id'] == c['initial_state_id'])}
    implementation = module(plan_folder / 'interface/src/training_selection_v2.py', '_claude_span_frozen_v2')
    legacy = module(plan_folder / 'interface/base_selection.py', '_claude_span_frozen_original_selection')
    datasets = {name: [] for name in ('T1', 'T2', 'T3', 'T4')}; reports = []
    for name in parents:
        ids = {c['initial_state_id'] for c in state['cells'] if c['parent_collection'] == name} & closed
        pool = [row for row in admitted if row['initial_state_id'] in ids]
        if not pool: continue
        groups, selection = implementation.build_matched_samples_v2(pool, read(plan_folder / 'rules' / (name + '.json')), legacy)
        mapped, budgets = derive_matched_samples(groups, tokenizer, 16384, interface_version=CONTEXT_VERSION)
        for method in datasets: datasets[method].extend(mapped[method])
        reports.append({'parent_collection': name, 'physical_selection': selection, 'student_budget_selection': budgets})
    for method, values in datasets.items():
        (output / (method + '.jsonl')).write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in values))
    samples = [row['raw_sample'] for values in datasets.values() for row in values]
    save(output / 'trusted_evidence_manifest.json', {'status': 'admitted', 'role': 'formal_train', 'readmission_report': 'physical_readmission.json', 'evidence_root': str(ROOT),
                                                      'admitted_sample_ids': [row['sample_id'] for row in samples], 'sample_sha256': {row['sample_id']: sample_identity(row) for row in samples}})
    sft_states = {row['raw_sample']['initial_state_id'] for row in datasets['T1']}; dpo_states = {row['raw_sample']['initial_state_id'] for row in datasets['T3']}
    save(output / 'student_selection.json', {'status': 'DERIVED_REQUIRES_TRAINING_MANIFEST_FREEZE', 'proposer_cohort': 'literal_span_Claude_fresh_trials_only_v2',
                                              'raw_collection_root': str(output), 'planned_proposals': definition['declared_proposals'], 'closed_initial_states': sorted(closed),
                                              'effective_samples_by_method': {name: len(values) for name, values in datasets.items()}, 'unique_useful_SFT_contexts': len(sft_states),
                                              'unique_DPO_contexts': len(dpo_states), 'unique_admitted_terminal_ASTs': len({source_identity(row['candidate_source']) for row in admitted}),
                                              'effective_registry_path': str(output / 'effective_registry.json'), 'evidence_root': str(ROOT), 'reports': reports, 'formal_training_started': False})
    state['selection_funnel'] = {'student_effective_rows': {name: len(values) for name, values in datasets.items()}, 'unique_useful_SFT_contexts': len(sft_states), 'unique_DPO_contexts': len(dpo_states),
                                 'physical_state_groups': sum(r['physical_selection']['initial_states'] for r in reports) if reports else 0}


def initial_state(definition):
    return {'status': 'RUNNING', 'role': ROLE, 'started_at_utc': now(), 'deadline_utc': (datetime.now(timezone.utc) + timedelta(hours=definition['physical']['maximum_dispatch_hours'])).isoformat(),
            'new_model_calls': 0, 'new_baseline_calls': 0, 'automatic_physical_retry': False, 'resource_samples': [], 'metadata_waits': [],
            'cells': [{'initial_state_id': c['initial_state_id'], 'parent_collection': c['parent_collection'], 'trial_id': trial, 'status': 'NOT_RUN'} for c in definition['contexts'] for trial in definition['trials']]}


def completion(definition, state):
    cells = state['cells']; points = [p for cell in cells for p in cell.get('points', [])]
    return {'status': state['status'], 'planned_proposals': definition['declared_proposals'], 'independent_contexts': definition['independent_contexts'], 'source_lineages': 1,
            'maximum_candidate_points': definition['physical']['maximum_new_candidate_points'],
            'original_proposal_status_counts': dict(Counter(c.get('original_proposal_status', 'NOT_RUN') for c in cells)),
            'followup_status_counts': dict(Counter(c['status'] for c in cells)), 'point_status_counts': dict(Counter(p['status'] for p in points)),
            'physically_complete_nine_domains': sum(len(c.get('points', [])) == 9 and all(p['status'] == 'COMPLETE' for p in c['points']) for c in cells),
            'admitted_nine_domains': sum(c['status'] == 'ADMITTED_COMPLETE_DOMAIN' for c in cells), 'actual_reserved_candidate_points': sum(p['status'] != 'NOT_RUN' for p in points),
            'selection_funnel': state.get('selection_funnel'), 'new_baseline_points': 0, 'new_model_calls': 0, 'automatic_retry': False, 'deadline_utc': state['deadline_utc'], 'at_utc': now()}


def run(path):
    path = Path(path).resolve(); definition, plan, parents, contexts, registry = load_acceptance(path)
    output = Path(definition['output_root']).resolve(); output.relative_to(ROOT / 'runs/train_collection'); output.mkdir(parents=True, exist_ok=True)
    with (output / 'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (output / 'acceptance.json').exists() and read(output / 'acceptance.json') != definition: raise ValueError('Output belongs to another frozen acceptance')
        save(output / 'acceptance.json', definition)
        state = read(output / 'state.json') if (output / 'state.json').exists() else initial_state(definition)
        if state.get('role') != ROLE or [(c['initial_state_id'], c['trial_id']) for c in state['cells']] != [(c['initial_state_id'], trial) for c in definition['contexts'] for trial in definition['trials']]:
            raise ValueError('Resume must retain all cells in frozen order')
        physical.mark_orphaned_reservations(state)
        if state['status'].startswith('PAUSED') or state['status'] in ('COMPLETE', 'WINDOW_ENDED'): save(output / 'state.json', state); return completion(definition, state)
        from transformers import AutoTokenizer
        cache = read(ROOT / 'configs/training/backbone_cache.json')
        tokenizer = AutoTokenizer.from_pretrained(cache['snapshot'], local_files_only=True, trust_remote_code=False)
        while datetime.now(timezone.utc) < datetime.fromisoformat(state['deadline_utc']):
            state.update(status='RUNNING', coordinator_pid=os.getpid())
            try:
                if not (Path(plan['output_root']) / 'matrix.json').exists(): state['status'] = 'WAITING_FOR_FROZEN_PROPOSALS'; save(output / 'state.json', state); time.sleep(15); continue
                scan_returned(definition, plan, parents, contexts, registry, state, output, tokenizer); save(output / 'state.json', state)
                physical_pass(definition, parents, registry, state, output, check_implementation=lambda: verify_code(path, definition))
                derive(definition, parents, registry, state, output, tokenizer, path.parent)
            except json.JSONDecodeError as exc: state['metadata_waits'].append({'at_utc': now(), 'error': str(exc)}); save(output / 'state.json', state); time.sleep(5); continue
            except Exception as exc: state.update(status='PAUSED_UNKNOWN', error=type(exc).__name__ + ': ' + str(exc)); break
            if state['status'].startswith('PAUSED') or state.get('dispatch_window_ended'): break
            if not any(c['status'] in ('NOT_RUN', 'PHYSICAL_PENDING') for c in state['cells']): state['status'] = 'COMPLETE'; break
            if (Path(plan['output_root']) / 'completion.json').exists():
                for cell in state['cells']:
                    if cell['status'] == 'NOT_RUN': cell['status'] = 'ORIGINAL_NOT_RUN_PROPOSAL_WINDOW_ENDED'
                derive(definition, parents, registry, state, output, tokenizer, path.parent)
                if not state['status'].startswith('PAUSED'): state['status'] = 'COMPLETE'
                break
            state['status'] = 'WAITING_FOR_ALREADY_DECLARED_PROPOSALS'; save(output / 'state.json', state); time.sleep(15)
        else: state['status'] = 'WINDOW_ENDED'
        if state.get('dispatch_window_ended') and not state['status'].startswith('PAUSED'): state['status'] = 'WINDOW_ENDED'
        state.update(coordinator_pid=None, ended_at_utc=now()); save(output / 'state.json', state)
        if state['status'] == 'PAUSED_UNKNOWN': physical.invalidate_derivation(output)
        result = completion(definition, state); save(output / 'completion.json', result); return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); group = p.add_mutually_exclusive_group(required=True)
    for action in ('prepare', 'freeze', 'validate-only', 'execute'): group.add_argument('--' + action, action='store_true')
    for name in ('proposal', 'folder', 'output-root', 'plan'): p.add_argument('--' + name, type=Path)
    p.add_argument('--hours', type=float, default=12); p.add_argument('--workers', type=int, default=6); a = p.parse_args()
    if a.prepare: print(json.dumps(prepare(a.proposal, a.folder, a.output_root, a.hours, a.workers), indent=2))
    elif a.freeze: print(json.dumps(freeze(a.plan), indent=2))
    elif a.validate_only: definition, plan, parents, contexts, registry = load_acceptance(a.plan); print(json.dumps({'status': 'VALIDATED', 'contexts': len(contexts), 'points': len(registry['configurations'])}))
    else: print(json.dumps(run(a.plan), indent=2))
