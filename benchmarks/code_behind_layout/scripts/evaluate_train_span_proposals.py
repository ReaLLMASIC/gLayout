"""Independent physical acceptance of the frozen sixteen literal-span proposals.

No model calls. Preparation and baseline control do not dispatch physical jobs.
Point execution reuses the existing durable T0 executor without T0 model identity.
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

ROOT = Path.cwd().resolve(); sys.path.insert(0, str(ROOT))
from scripts import evaluate_matched_t0_proposals as physical
from scripts.collect_planning_trajectories import workspace
from scripts.derive_training_selection_v2 import frozen_base_selection
from scripts.prepare_student_data import bound_registry
from scripts.run_frozen_training_collection import load_definition, frozen_module
from src.model_adapter import prompt_token_budget
from src.student_interface import CONTEXT_VERSION, canonical_action, derive_matched_samples, encode_policy_action, student_request, PolicyBudgetError
from src.train_span_bundle import load_bundle, validate_tokenizer
from src.train_span_proposer import MODE, ROLE as PRODUCER_ROLE, VERSION, compile_proposal, mapping_proof, proposal_prompt, source_identity, validate_proposal
from src.training import TrustedPhysicalStore, admit_candidates, sample_identity
from src.training_selection_v2 import make_rule

ROLE = 'literal_span_GPT_physical_followup_train_only'
CODE = tuple(dict.fromkeys((*physical.CODE, 'scripts/evaluate_train_span_proposals.py',
    'src/train_span_proposer.py', 'src/train_span_bundle.py')))
read, save, now, module = physical.read, physical.save, physical.now, physical.module


def proposal_definition(path):
    path = Path(path).resolve(); bundle = path.parent; plan = load_bundle(path)
    for name in ('train_span_proposer.py', 'train_span_bundle.py', 'student_interface.py'):
        if (ROOT/'src'/name).read_bytes() != (bundle/'interface/src'/name).read_bytes():
            raise ValueError('Acceptance must use the exact frozen compiler/student mapping: ' + name)
    parents = {}; contexts = []
    for entry in plan['contexts']:
        parent_path = ROOT/'runtime/train_collections'/entry['parent_collection_id']/'collection.json'
        manifest, frozen, states, files = load_definition(parent_path)
        if manifest != read(bundle/entry['parent_collection']): raise ValueError('Parent physical collection identity changed')
        state = read(bundle/entry['initial_state'])
        actual, = [s for s in states if s['initial_state_id'] == state['initial_state_id']]
        if actual != state or state['origin'] != 'natural': raise ValueError('Retain the real complete naturally produced initial state')
        effective = bound_registry(frozen, read(bundle/entry['effective_registry']))
        original = read(bundle/entry['original_request']); teacher = read(bundle/entry['teacher_request'])
        mapping_proof(original, teacher)
        parent = {'manifest': manifest, 'registry': effective, 'states': states, 'files': files,
                  'collector': frozen_module(parent_path)}
        parents[entry['parent_collection_id']] = parent
        contexts.append({**entry, 'state': state, 'base_source': state['base_source'],
            'original_request_value': original, 'teacher_request_value': teacher})
    registry = physical.merge_registries([p['registry'] for p in parents.values()])
    if len(registry['configurations']) != 18: raise ValueError('Preserve two distinct complete nine-point domains')
    return plan, parents, contexts, registry


def prepare(proposal, folder, output_root, hours=8):
    plan, parents, contexts, _ = proposal_definition(proposal)
    if type(hours) not in (int, float) or not math.isfinite(hours) or hours <= 0: raise ValueError('Declare one finite dispatch window')
    folder = Path(folder).resolve(); folder.mkdir(parents=True, exist_ok=False)
    output_root = Path(output_root).resolve(); output_root.relative_to(ROOT/'runs/train_collection')
    for name in CODE:
        target = folder/'interface'/name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT/name, target)
    (folder/'interface/base_selection.py').write_text(frozen_base_selection((ROOT/'src/training.py').read_text()))
    for name, parent in parents.items():
        save(folder/'rules'/(name+'.json'), make_rule(read(parent['manifest']['label_rule_path']), parent['manifest']['sampling']))
    for context in contexts:
        work = folder/'contexts'/context['initial_state_id']
        save(work/'task_packet.json', context['original_request_value']['task_packet'])
        save(work/'visible_history.json', context['original_request_value']['visible_history'])
    definition = {'status': 'DRAFT', 'role': ROLE, 'proposal_collection': str(Path(proposal).resolve()),
        'proposal_collection_sha256': hashlib.sha256(Path(proposal).read_bytes()).hexdigest(),
        'created_at_utc': now(), 'evidence_root': str(ROOT), 'output_root': str(output_root),
        'contexts': [{'initial_state_id': c['initial_state_id'], 'parent_collection': c['parent_collection_id']} for c in contexts],
        'trials': list(range(1, 9)), 'declared_proposals': 16, 'additional_independent_contexts': 0, 'source_lineages': 1,
        'physical': {'workers': 2, 'cpus_per_job': 2, 'memory_GiB_per_job': 8,
            'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720, 'maximum_dispatch_hours': hours,
            'maximum_new_candidate_points': 144, 'maximum_new_baseline_points': 0,
            'actual_busy_cores_plus_new_limit': 24, 'RAM_used_GiB_limit': 190, 'minimum_free_disk_GiB': 4},
        'implementation_files': list(CODE), 'raw_input_policy': 'Only this frozen16 proposal cohort; no old40 failed patches or other candidate pools.',
        'selection': 'Unchanged Point/Family scopes, baseline minimum effect, numerical ties and v2 earliest equivalent-best actual trial. Eight trial_id values1..8 match the parent trial-order interface; producer identity remains literal-span GPT.',
        'student': {'version': CONTEXT_VERSION, 'max_context_tokens': 16384, 'max_new_tokens': 1024},
        'baseline_policy': 'Current raw nine-baseline proof per context, same original source/N/spec/trusted image/runtime; ROOT evidence paths, no fresh baseline calls.',
        'failure_policy': 'Durable point reservation, unknown stops new dispatch, no automatic retry; original16 denominator/NOT_RUN and costs retained.',
        'task_identity_mapping': 'Retain raw teacher task_id; use frozen physical contract.task_id for backend admission. Record the mapping and prove ordinary source/contract/history identical except this field. Raw teacher/physical packets are not claimed byte-identical.'}
    save(folder/'acceptance.json', definition); return definition


def load_acceptance(path, require_frozen=True):
    path = Path(path).resolve(); definition = read(path)
    if definition.get('role') != ROLE or definition.get('status') != ('frozen' if require_frozen else 'DRAFT'):
        raise ValueError('Use the independent reviewed span physical acceptance plan')
    if (definition['declared_proposals'] != 16 or definition['trials'] != list(range(1, 9))
            or definition['additional_independent_contexts'] != 0 or definition['source_lineages'] != 1
            or definition['implementation_files'] != list(CODE) or definition['evidence_root'] != str(ROOT)):
        raise ValueError('Keep the original two-context sixteen-trial cohort and private ROOT evidence endpoint')
    expected = {'workers': 2, 'cpus_per_job': 2, 'memory_GiB_per_job': 8,
        'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720,
        'maximum_dispatch_hours': definition['physical']['maximum_dispatch_hours'],
        'maximum_new_candidate_points': 144, 'maximum_new_baseline_points': 0,
        'actual_busy_cores_plus_new_limit': 24, 'RAM_used_GiB_limit': 190, 'minimum_free_disk_GiB': 4}
    hours = expected['maximum_dispatch_hours']
    if definition['physical'] != expected or type(hours) not in (int, float) or not math.isfinite(hours) or hours <= 0:
        raise ValueError('Physical resource/finite-window/144candidate/0baseline limits changed')
    verify_code(path, definition)
    plan, parents, contexts, registry = proposal_definition(definition['proposal_collection'])
    if hashlib.sha256(Path(definition['proposal_collection']).read_bytes()).hexdigest() != definition['proposal_collection_sha256']:
        raise ValueError('Original proposal freeze identity changed')
    if definition['contexts'] != [{'initial_state_id': c['initial_state_id'], 'parent_collection': c['parent_collection_id']} for c in contexts]:
        raise ValueError('Context assignment changed')
    for name, parent in parents.items():
        if read(path.parent/'rules'/(name+'.json')) != make_rule(read(parent['manifest']['label_rule_path']), parent['manifest']['sampling']):
            raise ValueError('Span v2 changed the inherited comparison thresholds or actual trial order')
    for context in contexts:
        work = path.parent/'contexts'/context['initial_state_id']
        context.update(parent_collection=context['parent_collection_id'],
            materialized_task_packet=str(work/'task_packet.json'), materialized_visible_history=str(work/'visible_history.json'))
        if read(work/'task_packet.json') != context['original_request_value']['task_packet'] or read(work/'visible_history.json') != context['original_request_value']['visible_history']:
            raise ValueError('Baseline control must reproduce the exact original packet/history')
    if require_frozen and any(p.stat().st_mode & 0o222 for p in [path.parent, *path.parent.rglob('*')]):
        raise ValueError('Frozen acceptance files/directories must be read-only')
    return definition, plan, parents, contexts, registry


def verify_code(path, definition):
    for name in definition['implementation_files']:
        if (ROOT/name).read_bytes() != (Path(path).parent/'interface'/name).read_bytes():
            raise ValueError('Acceptance implementation changed: '+name)
    if (Path(path).parent/'interface/base_selection.py').read_text() != frozen_base_selection((ROOT/'src/training.py').read_text()):
        raise ValueError('Inherited complete selection functions changed')


def freeze(path):
    path = Path(path).resolve(); definition, _, _, _, _ = load_acceptance(path, False)
    definition.update(status='frozen', frozen_at_utc=now()); save(path, definition)
    for p in sorted(path.parent.rglob('*'), key=lambda p: len(p.parts), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    path.parent.chmod(0o555)
    return {'status': 'FROZEN_SPAN_PHYSICAL_ACCEPTANCE_NO_CALLS', 'new_model_calls': 0, 'new_physical_calls': 0}


def verify_raw(plan, context, trial, directory, tokenizer, proposal_sha):
    directory = Path(directory); attempt = read(directory/'attempt.json'); body = read(directory/'request.json')
    expected = {'mode': MODE, 'initial_state_id': context['initial_state_id'], 'trial_id': trial, 'request': context['teacher_request_value']}
    if json.dumps(body) != json.dumps(expected) or (attempt['initial_state_id'], attempt['trial_id']) != (context['initial_state_id'], trial):
        raise ValueError('Raw trial/context/full request serialization differs from the prospective freeze')
    if not (directory/'response.json').exists(): raise ValueError('Returned trial lacks its actual raw response; unknown, never a negative')
    response = read(directory/'response.json'); usage = response.get('usage') or {}; model = response.get('model') or {}
    if (attempt.get('inference_id') != response.get('inference_id') or not response.get('inference_id')
            or attempt.get('usage') != response.get('usage') or attempt.get('model') != response.get('model')
            or response.get('collection_sha256') != proposal_sha):
        raise ValueError('Raw inference/usage/model/frozen collection identity differs')
    if (response.get('native_tools') != [] or model.get('source_role') != PRODUCER_ROLE
            or model.get('teacher_interface_version') != VERSION or model.get('requested_model') != 'gpt-6.1-sol'
            or model.get('settings') != {'reasoning_effort': 'high', 'max_new_tokens': 3072, 'maximum_context_tokens': 16384, 'sampling_seed': None}
            or usage.get('request_mode') != MODE or usage.get('output_format') != 'literal_span_edits_json'):
        raise ValueError('Actual producer identity, tool boundary or source-format budget changed')
    if response.get('producer_status') in ('TIMEOUT', 'FAILED', 'RUNNING', 'PUBLIC_USAGE_UNAVAILABLE'):
        raise ValueError('Original producer execution/cost is unknown; pause without a negative')
    stages = {'actual_raw_identity_verified': True}
    if attempt.get('http_status') != 200 or response.get('error'):
        return {'status': 'ORIGINAL_PRODUCER_REJECTED', 'attempt': attempt, 'stages': stages}
    if (not usage.get('public_cli_usage') or not usage.get('model_call_issued')
            or not 0 < usage.get('server_wall_seconds', float('inf')) <= 240
            or not 0 < attempt.get('client_wall_seconds', float('inf')) <= 240):
        raise ValueError('Actual public cost or finite producer/client budget is not established')
    flight = prompt_token_budget(tokenizer, proposal_prompt(body['request']), {'max_new_tokens': 3072, 'max_context_tokens': 16384})
    raw = response['raw_proposal_text']; proposal = json.loads(raw); count = len(tokenizer(raw, add_special_tokens=False)['input_ids'])+1
    if not flight['fits_with_full_output_reserve'] or count > 3072:
        return {'status': 'ORIGINAL_PRODUCER_TOKEN_BUDGET_REJECTED', 'attempt': attempt, 'stages': stages}
    recorded = usage.get('policy_token_budget', {})
    if (proposal != response.get('proposal') or recorded.get('prompt_tokens') != flight['prompt_tokens']
            or recorded.get('completion_tokens_including_EOS') != count or recorded.get('actual_total_tokens') != flight['prompt_tokens']+count):
        raise ValueError('Exact raw producer JSON or actual tokenizer accounting differs')
    stages['producer_raw_json_and_3072_budget_verified'] = True
    try: compiled = compile_proposal(context['base_source'], validate_proposal(proposal, context['base_source']))
    except ValueError as exc: return {'status': 'LITERAL_EDIT_REJECTED_NO_PHYSICAL_LABEL', 'attempt': attempt, 'reason': str(exc), 'stages': stages}
    if compiled != read(directory/'compiled.json'): raise ValueError('Stored compiler proof/result differs from independent deterministic replay')
    stages['deterministic_compile_and_actual_git_bytes_verified'] = True
    try:
        for text in compiled['candidate_source'].values(): ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return {'status': 'SOURCE_NOT_PARSEABLE_NO_PHYSICAL_LABEL', 'attempt': attempt, 'reason': str(exc), 'stages': stages}
    stages['candidate_AST_parseable'] = True
    if source_identity(compiled['candidate_source']) == source_identity(context['base_source']):
        return {'status': 'SEMANTIC_NOOP', 'attempt': attempt, 'stages': stages}
    mapped = student_request({'base_source': context['base_source'], 'visible_contract': body['request']['task_packet'],
        'visible_feedback': body['request']['visible_history']}, CONTEXT_VERSION, 16384)
    if (read(directory/'student_request.json') != mapped
            or (directory/'student_action.json').read_text() != canonical_action(compiled['patch'], mapped)+'\n'):
        raise ValueError('Original compiled ordinary ACTION/source mapping changed')
    return {'status': 'ELIGIBLE_UNIQUE_CHECK_PENDING', 'attempt': attempt, 'source': compiled['candidate_source'],
        'patch': compiled['patch'], 'request': body['request'], 'compiled': compiled, 'raw_directory': str(directory), 'stages': stages}


def candidate_row(context, parent, proposal, trial):
    state = context['state']; task = proposal['request']['task_packet']
    ids = task['visible_configurations']; points = [p for p in parent['registry']['configurations'] if p['configuration_id'] in ids]
    task_ids = {p['contract']['task_id'] for p in points}
    if len(points) != 9 or len(task_ids) != 1: raise ValueError('Preserve the complete independent nine-point physical task')
    visible = {k: v for k, v in task.items() if k != 'visible_sources'}
    visible.update(task_id=next(iter(task_ids)), editable_paths=list(state['base_source']))
    row = {'candidate_id': 'literal_span_GPT__'+state['initial_state_id']+'__trial_'+str(trial),
        'initial_state_id': state['initial_state_id'], 'parent_lineage': state['parent_lineage'], 'split': 'train',
        'source_role': 'formal_train', 'origin': state['origin'], 'ancestry': state['ancestry'],
        'pdk_revision': parent['manifest']['pdk_revision'], 'base_source': state['base_source'],
        'candidate_source': proposal['source'], 'candidate_patch': proposal['patch'],
        'visible_contract': visible, 'visible_feedback': proposal['request']['visible_history'],
        'proposal_generation': {**proposal['attempt'], 'trial_id': trial, 'proposer_cohort': 'literal_span_GPT_eight_fresh_trials',
            'teacher_mode': MODE, 'raw_directory': proposal.get('raw_directory'), 'model_seed_available': False}, 'outcomes': []}
    return row


def student_identity_proof(context, row, raw_directory=None):
    raw_request = context['teacher_request_value']; ordinary = student_request({'base_source': context['base_source'],
        'visible_contract': raw_request['task_packet'], 'visible_feedback': raw_request['visible_history']}, CONTEXT_VERSION, 16384)
    final = student_request({k: row[k] for k in ('base_source', 'visible_contract', 'visible_feedback')}, CONTEXT_VERSION, 16384)
    normalized = json.loads(json.dumps(ordinary)); normalized['task_packet']['task_id'] = row['visible_contract']['task_id']
    if normalized != final: raise ValueError('Source/physical contract/history changed beyond the declared backend task_id mapping')
    action = canonical_action(row['candidate_patch'], final) if row['candidate_patch'] else None
    if action is not None and canonical_action(row['candidate_patch'], ordinary) != action: raise ValueError('Backend task identity altered the actual ordinary ACTION')
    return {'raw_teacher_task_id': raw_request['task_packet']['task_id'], 'physical_contract_task_id': row['visible_contract']['task_id'],
        'only_backend_task_id_changes_after_output_instruction_mapping': True, 'raw_and_physical_packets_byte_identical': False,
        'source_physical_contract_and_feedback_equal': True, 'compiled_action_text_unchanged': True if action is not None else None,
        'action_proof_scope': 'Actual compiled candidate' if action is not None else 'Baseline context control; no model proposal or compiled candidate exists yet',
        'ordinary_student_request': final, 'ordinary_action_text': action, 'original_raw_directory': raw_directory}


def baseline_control(path, report):
    definition, _, parents, contexts, registry = load_acceptance(path, False); records = []
    for context in contexts:
        parent = parents[context['parent_collection']]
        proposal = {'request': context['teacher_request_value'], 'source': context['base_source'], 'patch': '', 'attempt': {}}
        row = candidate_row(context, parent, proposal, 1)
        checked = physical.baseline_bindings(context, parent, registry, row)
        records.append({'initial_state_id': context['initial_state_id'], 'points': checked,
            'student_identity_proof': student_identity_proof(context, row), 'new_physical_calls': 0})
    result = {'status': 'ACTUAL_SPAN_BASELINE_AND_TASK_IDENTITY_CONTROL', 'at_utc': now(),
        'contexts': records, 'actual_baseline_points_re_read': 18, 'evidence_root': str(ROOT),
        'new_model_calls': 0, 'new_physical_calls': 0, 'new_training_examples': 0}
    save(report, result); return {k: v for k, v in result.items() if k != 'contexts'}


def raw_matrix(plan):
    rows = read(Path(plan['output_root'])/'matrix.json')
    expected = [(c['initial_state_id'], trial) for c in plan['contexts'] for trial in range(1, 9)]
    actual = [(r['initial_state_id'], r['trial_id']) for r in rows]
    if actual != expected: raise ValueError('Preserve all sixteen proposal slots, order and NOT_RUN cells')
    return {key: row for key, row in zip(actual, rows)}


def scan_returned(definition, plan, parents, contexts, registry, state, output, tokenizer):
    matrix = raw_matrix(plan); save(output/'original_matrix_snapshot.json', list(matrix.values()))
    save(output/'effective_registry.json', registry); lookup = {c['initial_state_id']: c for c in contexts}
    seen = {name: {source_identity(c['base_source']): 'initial_source'} for name, c in lookup.items()}
    for cell in state['cells']:
        if cell.get('candidate_file'):
            row = read(output/cell['candidate_file']); seen[cell['initial_state_id']][source_identity(row['candidate_source'])] = row['candidate_id']
    for cell in state['cells']:
        raw = matrix[(cell['initial_state_id'], cell['trial_id'])]; cell['original_proposal_status'] = raw['status']
        if cell['status'] != 'NOT_RUN' or raw['status'] in ('NOT_RUN', 'DISPATCHED'): continue
        context = lookup[cell['initial_state_id']]; parent = parents[context['parent_collection']]
        directory = Path(plan['output_root'])/cell['initial_state_id']/('trial_'+str(cell['trial_id']))
        if raw.get('attempt_directory') != str(directory): raise ValueError('Raw attempt directory changed')
        proposal = verify_raw(plan, context, cell['trial_id'], directory, tokenizer, definition['proposal_collection_sha256'])
        cell['proposal_audit'] = {k: v for k, v in proposal.items() if k not in ('source', 'patch', 'request', 'compiled')}
        if proposal['status'] != 'ELIGIBLE_UNIQUE_CHECK_PENDING': cell['status'] = proposal['status']; continue
        key = source_identity(proposal['source'])
        if key in seen[cell['initial_state_id']]:
            cell.update(status='SEMANTIC_DUPLICATE_NOT_NEW_SAMPLE', duplicate_of=seen[cell['initial_state_id']][key]); continue
        cell['unique_candidate_AST_verified'] = True
        row = candidate_row(context, parent, proposal, cell['trial_id'])
        proof = student_identity_proof(context, row, str(directory))
        try: encoded = encode_policy_action(tokenizer, proof['ordinary_student_request'], row['candidate_patch'], 16384, 1024)
        except PolicyBudgetError as exc:
            cell.update(status='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS', student_budget=exc.details); continue
        cell['final_student_1024_16k_verified'] = True
        baselines = physical.baseline_bindings(context, parent, registry, row)
        folder = output/'candidates'/row['candidate_id']; folder.mkdir(parents=True, exist_ok=False)
        workspace(Path(parent['manifest']['source_pack']), parent['files'], row['candidate_source'], folder/'source')
        save(folder/'baseline_adoption.json', baselines); save(folder/'candidate.json', row)
        save(folder/'student_identity_proof.json', proof)
        originals = folder/'original_proposal'; originals.mkdir()
        for name in ('request.json', 'response.json', 'attempt.json', 'compiled.json', 'student_request.json', 'student_action.json', 'student_budget.json'):
            shutil.copyfile(directory/name, originals/name)
        cell.update(status='PHYSICAL_PENDING', candidate_file=str((folder/'candidate.json').relative_to(output)),
            parent_collection=context['parent_collection'], baseline_adoption=str((folder/'baseline_adoption.json').relative_to(output)),
            student_budget={'prompt_tokens': encoded.prompt_tokens, 'completion_tokens_including_EOS': encoded.completion_tokens,
                'total_tokens': len(encoded.input_ids), 'source_or_contract_truncated': False},
            points=[{'configuration_id': name, 'status': 'NOT_RUN'} for name in baselines])
        seen[cell['initial_state_id']][key] = row['candidate_id']


def derive(definition, parents, registry, state, output, tokenizer, plan_folder):
    rows = []; admitted = []; rejections = []; store = TrustedPhysicalStore(ROOT, registry)
    for cell in state['cells']:
        if not cell.get('candidate_file'): continue
        row = read(output/cell['candidate_file']); rows.append(row)
        if not cell.get('points') or not all(p['status'] == 'COMPLETE' for p in cell['points']): continue
        try:
            admitted.extend(admit_candidates([row], registry, store)); cell['status'] = 'ADMITTED_COMPLETE_DOMAIN'
        except (ValueError, OSError, KeyError) as exc:
            cell['status'] = 'QUARANTINED_ADMISSION'; state['status'] = 'PAUSED_UNKNOWN'
            rejections.append({'candidate_id': row['candidate_id'], 'error': str(exc)})
    (output/'candidates.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows))
    save(output/'physical_readmission.json', {'status': 'QUARANTINED' if rejections or state['status'] == 'PAUSED_UNKNOWN' else 'READMITTED_ACTUAL_COMPLETE_DOMAINS',
        'raw_candidates': len(rows), 'admitted_candidates': len(admitted), 'rejections': rejections,
        'unknowns_used_as_negatives': False, 'new_baseline_calls': 0, 'evidence_root': str(ROOT), 'old40_patches_or_other_pools_used': False})
    if state['status'] == 'PAUSED_UNKNOWN': physical.invalidate_derivation(output); return
    unfinished = ('NOT_RUN', 'PHYSICAL_PENDING')
    closed = {c['initial_state_id'] for c in state['cells'] if all(other['status'] not in unfinished
        for other in state['cells'] if other['initial_state_id'] == c['initial_state_id'])}
    implementation = module(plan_folder/'interface/src/training_selection_v2.py', '_span_frozen_v2')
    legacy = module(plan_folder/'interface/base_selection.py', '_span_frozen_original_selection')
    datasets = {name: [] for name in ('T1', 'T2', 'T3', 'T4')}; reports = []
    for name in parents:
        ids = {c['initial_state_id'] for c in state['cells'] if c['parent_collection'] == name} & closed
        pool = [row for row in admitted if row['initial_state_id'] in ids]
        if not pool: continue
        groups, selection = implementation.build_matched_samples_v2(pool, read(plan_folder/'rules'/(name+'.json')), legacy)
        mapped, budgets = derive_matched_samples(groups, tokenizer, 16384, interface_version=CONTEXT_VERSION)
        for method in datasets: datasets[method].extend(mapped[method])
        reports.append({'parent_collection': name, 'physical_selection': selection, 'student_budget_selection': budgets})
    for method, values in datasets.items():
        (output/(method+'.jsonl')).write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in values))
    samples = [row['raw_sample'] for values in datasets.values() for row in values]
    save(output/'trusted_evidence_manifest.json', {'status': 'admitted', 'role': 'formal_train',
        'readmission_report': 'physical_readmission.json', 'evidence_root': str(ROOT),
        'admitted_sample_ids': [row['sample_id'] for row in samples],
        'sample_sha256': {row['sample_id']: sample_identity(row) for row in samples}})
    sft_states = {row['raw_sample']['initial_state_id'] for row in datasets['T1']}
    dpo_states = {row['raw_sample']['initial_state_id'] for row in datasets['T3']}
    save(output/'student_selection.json', {'status': 'DERIVED_REQUIRES_TRAINING_MANIFEST_FREEZE',
        'proposer_cohort': 'literal_span_GPT_eight_fresh_trials_only', 'raw_collection_root': str(output),
        'planned_proposals': 16, 'initial_contexts_reused': 2, 'additional_independent_contexts': 0,
        'source_lineages': 1, 'closed_initial_states': sorted(closed), 'old40_failed_patch_pool_used': False,
        'effective_samples_by_method': {name: len(values) for name, values in datasets.items()},
        'unique_useful_SFT_contexts': len(sft_states), 'unique_DPO_contexts': len(dpo_states),
        'unique_admitted_terminal_ASTs': len({source_identity(row['candidate_source']) for row in admitted}),
        'effective_registry_path': str(output/'effective_registry.json'), 'evidence_root': str(ROOT),
        'raw_evidence_re_admitted': True, 'reports': reports, 'formal_training_started': False,
        'counting': 'T1/T2 share contexts and candidate pool; never sum methods or add reused contexts to prior cohorts. No cross-proposer pool or labels are inferred.'})
    state['selection_funnel'] = {'physical_state_groups': sum(r['physical_selection']['initial_states'] for r in reports),
        'ambiguous_preference_pairs': sum(r['physical_selection']['ambiguous_preference_pairs'] for r in reports),
        'point_family_conflicting_pairs': sum(r['physical_selection']['point_family_conflicts'] for r in reports),
        'SFT_baseline_effect_and_equivalent_best_details': [r['physical_selection']['SFT_choices'] for r in reports],
        'student_effective_rows': {name: len(values) for name, values in datasets.items()},
        'unique_useful_SFT_contexts': len(sft_states), 'unique_DPO_contexts': len(dpo_states)}


def initial_state(definition):
    return {'status': 'RUNNING', 'role': ROLE, 'started_at_utc': now(),
        'deadline_utc': (datetime.now(timezone.utc)+timedelta(hours=definition['physical']['maximum_dispatch_hours'])).isoformat(),
        'new_model_calls': 0, 'new_baseline_calls': 0, 'automatic_physical_retry': False, 'resource_samples': [], 'metadata_waits': [],
        'cells': [{'initial_state_id': c['initial_state_id'], 'parent_collection': c['parent_collection'],
            'trial_id': trial, 'status': 'NOT_RUN'} for c in definition['contexts'] for trial in definition['trials']]}


def completion(state):
    cells = state['cells']; points = [p for cell in cells for p in cell.get('points', [])]
    return {'status': state['status'], 'planned_proposals': 16, 'original_contexts_reused': 2,
        'additional_independent_contexts': 0, 'source_lineages': 1, 'maximum_candidate_points': 144,
        'original_proposal_status_counts': dict(Counter(c.get('original_proposal_status', 'NOT_RUN') for c in cells)),
        'followup_status_counts': dict(Counter(c['status'] for c in cells)), 'point_status_counts': dict(Counter(p['status'] for p in points)),
        'stage_funnel': {'declared_raw_slots': 16, 'returned_raw_slots': sum(c.get('original_proposal_status', 'NOT_RUN') not in ('NOT_RUN', 'DISPATCHED') for c in cells),
            'raw_identity_verified': sum(c.get('proposal_audit', {}).get('stages', {}).get('actual_raw_identity_verified', False) for c in cells),
            'producer_3072_budget_verified': sum(c.get('proposal_audit', {}).get('stages', {}).get('producer_raw_json_and_3072_budget_verified', False) for c in cells),
            'deterministic_compiler_git_verified': sum(c.get('proposal_audit', {}).get('stages', {}).get('deterministic_compile_and_actual_git_bytes_verified', False) for c in cells),
            'parseable_AST': sum(c.get('proposal_audit', {}).get('stages', {}).get('candidate_AST_parseable', False) for c in cells),
            'raw_audits_eligible': sum(c.get('proposal_audit', {}).get('status') == 'ELIGIBLE_UNIQUE_CHECK_PENDING' for c in cells),
            'unique_candidate_AST': sum(c.get('unique_candidate_AST_verified', False) for c in cells),
            'final_student_1024_16k_verified': sum(c.get('final_student_1024_16k_verified', False) for c in cells),
            'unique_student_fit_candidate_programs_by_context': sum('candidate_file' in c for c in cells),
            'physically_complete_nine_domains': sum(len(c.get('points', [])) == 9 and all(p['status'] == 'COMPLETE' for p in c['points']) for c in cells),
            'current_gate_admitted_nine_domains': sum(c['status'] == 'ADMITTED_COMPLETE_DOMAIN' for c in cells)},
        'actual_reserved_candidate_points': sum(p['status'] != 'NOT_RUN' for p in points),
        'actual_returned_point_records': sum('evidence_path' in p for p in points), 'new_baseline_points': 0, 'new_model_calls': 0,
        'selection_funnel': state.get('selection_funnel'),
        'automatic_retry': False, 'deadline_utc': state['deadline_utc'], 'formal_model_training_runs': 0,
        'raw_teacher_cost_scope': 'Original response usage and client/server wall retained per proposal; not recharged as new inference cost', 'at_utc': now()}


def run(path):
    path = Path(path).resolve(); definition, plan, parents, contexts, registry = load_acceptance(path)
    output = Path(definition['output_root']).resolve(); output.relative_to(ROOT/'runs/train_collection'); output.mkdir(parents=True, exist_ok=True)
    with (output/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (output/'acceptance.json').exists() and read(output/'acceptance.json') != definition: raise ValueError('Output belongs to another frozen acceptance')
        save(output/'acceptance.json', definition)
        state = read(output/'state.json') if (output/'state.json').exists() else initial_state(definition)
        if (state.get('role') != ROLE or [(c['initial_state_id'], c['trial_id']) for c in state['cells']] !=
                [(c['initial_state_id'], trial) for c in definition['contexts'] for trial in definition['trials']]):
            raise ValueError('Resume must retain all sixteen cells in frozen order')
        physical.mark_orphaned_reservations(state)
        if state['status'].startswith('PAUSED') or state['status'] in ('COMPLETE', 'WINDOW_ENDED'):
            save(output/'state.json', state); return completion(state)
        from transformers import AutoTokenizer
        cache = read(ROOT/'configs/training/backbone_cache.json'); validate_tokenizer(cache['snapshot'], Path(definition['proposal_collection']).parent)
        tokenizer = AutoTokenizer.from_pretrained(cache['snapshot'], local_files_only=True, trust_remote_code=False)
        while datetime.now(timezone.utc) < datetime.fromisoformat(state['deadline_utc']):
            state.update(status='RUNNING', coordinator_pid=os.getpid())
            try:
                if not (Path(plan['output_root'])/'matrix.json').exists():
                    state['status'] = 'WAITING_FOR_FROZEN_PROPOSALS'; save(output/'state.json', state); time.sleep(5); continue
                scan_returned(definition, plan, parents, contexts, registry, state, output, tokenizer); save(output/'state.json', state)
                physical.physical_pass(definition, parents, registry, state, output, check_implementation=lambda: verify_code(path, definition))
                derive(definition, parents, registry, state, output, tokenizer, path.parent)
            except json.JSONDecodeError as exc:
                state['metadata_waits'].append({'at_utc': now(), 'error': str(exc)}); save(output/'state.json', state); time.sleep(5); continue
            except Exception as exc:
                state.update(status='PAUSED_UNKNOWN', error=type(exc).__name__+': '+str(exc)); break
            if state['status'].startswith('PAUSED') or state.get('dispatch_window_ended'): break
            if not any(c['status'] in ('NOT_RUN', 'PHYSICAL_PENDING') for c in state['cells']): state['status'] = 'COMPLETE'; break
            if (Path(plan['output_root'])/'completion.json').exists():
                for cell in state['cells']:
                    if cell['status'] == 'NOT_RUN': cell['status'] = 'ORIGINAL_NOT_RUN_PROPOSAL_WINDOW_ENDED'
                derive(definition, parents, registry, state, output, tokenizer, path.parent)
                if not state['status'].startswith('PAUSED'): state['status'] = 'COMPLETE'
                break
            state['status'] = 'WAITING_FOR_ALREADY_DECLARED_PROPOSALS'; save(output/'state.json', state); time.sleep(5)
        else: state['status'] = 'WINDOW_ENDED'
        if state.get('dispatch_window_ended') and not state['status'].startswith('PAUSED'): state['status'] = 'WINDOW_ENDED'
        state.update(coordinator_pid=None, ended_at_utc=now()); save(output/'state.json', state)
        if state['status'] == 'PAUSED_UNKNOWN': physical.invalidate_derivation(output)
        result = completion(state); save(output/'completion.json', result); return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); group = p.add_mutually_exclusive_group(required=True)
    for action in ('prepare', 'freeze', 'validate-only', 'baseline-control', 'execute'): group.add_argument('--'+action, action='store_true')
    for name in ('proposal', 'folder', 'output-root', 'plan', 'report'): p.add_argument('--'+name, type=Path)
    p.add_argument('--dispatch-hours', type=float, default=8); a = p.parse_args()
    if a.prepare: result = prepare(a.proposal, a.folder, a.output_root, a.dispatch_hours)
    elif a.baseline_control: result = baseline_control(a.plan, a.report)
    elif a.freeze: result = freeze(a.plan)
    elif a.execute: result = run(a.plan)
    else:
        definition, _, _, _, _ = load_acceptance(a.plan)
        result = {'status': 'VALIDATED_FROZEN_SPAN_PHYSICAL_ACCEPTANCE_NO_CALLS', 'planned_proposals': 16, 'new_model_calls': 0, 'new_physical_calls': 0}
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), flush=True)
