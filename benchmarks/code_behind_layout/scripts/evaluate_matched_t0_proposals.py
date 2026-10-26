"""Finite train-only physical follow-up of the already frozen matched T0 proposals.

No model requests are made. Original proposal/GPT collections are read-only.
Prepare a DRAFT, review/freeze it, then execute fresh candidate points only.
"""
import argparse
import ast
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path.cwd().resolve();sys.path.insert(0, str(ROOT))
from scripts.collect_matched_t0_proposals import identity
from scripts.collect_planning_trajectories import workspace
from scripts.derive_training_selection_v2 import frozen_base_selection
from scripts.prepare_student_data import bound_registry
from scripts.run_frozen_training_collection import frozen_module, load_definition
from scripts.serve_matched_t0_proposals import MODE, SEEDS, validate_request
from scripts.train_collection_queue import resource_sample
from src.candidate_executor import CandidateExecutor, apply_source_patch
from src.e4_methods import REVISION
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget, validate_action
from src.student_interface import CONTEXT_VERSION, derive_matched_samples, encode_policy_action, student_request
from src.training import TrustedPhysicalStore, admit_candidates, bind_candidate_edit, sample_identity
from src.training_selection_v2 import make_rule

ROLE = 'matched_T0_physical_followup_train_only'
CODE = ('scripts/evaluate_matched_t0_proposals.py', 'scripts/collect_matched_t0_proposals.py',
    'scripts/collect_planning_trajectories.py', 'scripts/derive_training_selection_v2.py',
    'scripts/prepare_student_data.py', 'scripts/run_frozen_training_collection.py',
    'scripts/serve_matched_t0_proposals.py', 'scripts/train_collection_queue.py',
    'src/candidate_executor.py', 'src/training.py', 'src/training_selection_v2.py',
    'src/domain_runner.py', 'src/device_intent.py', 'src/measurement.py', 'src/report_parsers.py',
    'src/spice_validation.py', 'src/model_adapter.py', 'src/local_model_adapter.py',
    'src/student_interface.py', 'src/policy_state.py', 'src/e4_methods.py')


def read(path):return json.loads(Path(path).read_text())
def now():return datetime.now(timezone.utc).isoformat()
def save(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n');temporary.replace(path)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path);value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value);return value


def proposal_definition(path):
    path = Path(path).resolve()
    frozen_service = module(path.parent/'interface/service.py', '_frozen_matched_t0_followup_service')
    plan = frozen_service.load_plan(path)
    if (plan['planned_proposals'] != 96 or plan['distinct_task_contexts'] != 12 or plan['actual_source_programs'] != 6
            or plan['source_lineages'] != 1 or plan['physical_jobs'] != 0):
        raise ValueError('Preserve the original96 proposal cells and twelve shared task contexts')
    parents = {}
    for name, item in plan['parent_GPT_collections'].items():
        manifest_path = Path(item['path'])
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != item['manifest_sha256']:
            raise ValueError('The frozen matched parent collection changed')
        manifest, registry, states, files = load_definition(manifest_path)
        parents[name] = {'manifest': manifest, 'registry': registry, 'states': states, 'files': files,
            'collector': frozen_module(manifest_path)}
    for context in plan['contexts']:
        parent = parents[context['parent_collection']]
        states = [s for s in parent['states'] if s['initial_state_id'] == context['initial_state_id']]
        if len(states) != 1 or states[0]['base_source'] != context['base_source']:
            raise ValueError('T0 must retain the exact existing GPT initial context')
        context['state'] = states[0]
    if len(parents) != 4 or len(merge_registries([p['registry'] for p in parents.values()])['configurations']) != 36:
        raise ValueError('Preserve four parent nine-point domains, not new contexts or lineages')
    return plan, parents


def prepare(proposal_path, folder, output_root, hours=8):
    plan, parents = proposal_definition(proposal_path)
    if type(hours) not in (int, float) or not math.isfinite(hours) or hours <= 0:
        raise ValueError('Review and freeze one explicit finite positive follow-up window')
    folder = Path(folder).resolve();folder.mkdir(parents=True, exist_ok=False)
    output_root = Path(output_root).resolve();output_root.relative_to(ROOT/'runs/train_collection')
    for name in CODE:
        target = folder/'interface'/name;target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    (folder/'interface/base_selection.py').write_text(frozen_base_selection((ROOT/'src/training.py').read_text()))
    for name, parent in parents.items():
        rule = make_rule(read(parent['manifest']['label_rule_path']), {'mode': 'train_collection', 'seeds': list(SEEDS)})
        save(folder/'rules'/(name+'.json'), rule)
    definition = {'status': 'DRAFT', 'role': ROLE, 'proposal_plan': str(Path(proposal_path).resolve()),
        'output_root': str(output_root), 'evidence_root': str(ROOT), 'created_at_utc': now(),
        'physical': {'workers': 2, 'cpus_per_job': 2, 'memory_GiB_per_job': 8,
            'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720,
            'maximum_dispatch_hours': hours, 'maximum_new_candidate_points': 864, 'maximum_new_baseline_points': 0,
            'actual_busy_cores_plus_new_limit': 24, 'RAM_used_GiB_limit': 190, 'minimum_free_disk_GiB': 4},
        'contexts': [{k: c[k] for k in ('initial_state_id', 'parent_collection', 'program_id', 'circuit_id')}
            for c in plan['contexts']], 'seeds': list(SEEDS), 'declared_proposals': 96,
        'implementation_files': list(CODE), 'source_lineages': 1, 'additional_independent_contexts': 0,
        'selection': 'Independent T0 eight-seed v2 cohort. Point/Family share the same physically admitted pool; no GPT/T0 joint16-candidate rule.',
        'baseline_reuse': 'Exact parent original source/config/N/contract/trusted files/PDK/tool runtime, independently re-read by TrustedPhysicalStore; never copy candidate labels.',
        'failure_policy': 'Reserve every point before execution; no automatic physical retries. Unknown/admission uncertainty stops new points; in-flight points finish and remain recorded.',
        'input_policy': 'Read only already returned original raw responses; no hunk repair, no model feedback, no new requests. NOT_RUN/invalid/noop/duplicate cells retain the96 denominator.'}
    save(folder/'acceptance.json', definition)
    return definition


def load_acceptance(path, require_frozen=True):
    path = Path(path).resolve();definition = read(path)
    if definition.get('role') != ROLE or definition.get('status') != ('frozen' if require_frozen else 'DRAFT'):
        raise ValueError('Use the separately reviewed/frozen T0 physical acceptance definition')
    expected = {'workers': 2, 'cpus_per_job': 2, 'memory_GiB_per_job': 8,
        'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720,
        'maximum_dispatch_hours': definition['physical']['maximum_dispatch_hours'],
        'maximum_new_candidate_points': 864, 'maximum_new_baseline_points': 0,
        'actual_busy_cores_plus_new_limit': 24, 'RAM_used_GiB_limit': 190, 'minimum_free_disk_GiB': 4}
    hours = expected['maximum_dispatch_hours']
    if definition['physical'] != expected or type(hours) not in (int, float) or not math.isfinite(hours) or hours <= 0:
        raise ValueError('Physical resources, finite window or declared864/0point limits differ')
    if definition['implementation_files'] != list(CODE):raise ValueError('Acceptance code closure changed')
    for name in CODE:
        if (ROOT/name).read_bytes() != (path.parent/'interface'/name).read_bytes():
            raise ValueError('Acceptance implementation changed: '+name)
    if (path.parent/'interface/base_selection.py').read_text() != frozen_base_selection((ROOT/'src/training.py').read_text()):
        raise ValueError('The exact inherited legacy selection functions changed')
    plan, parents = proposal_definition(definition['proposal_plan'])
    context_keys = ('initial_state_id', 'parent_collection', 'program_id', 'circuit_id')
    if (definition['contexts'] != [{k: c[k] for k in context_keys} for c in plan['contexts']]
            or definition['seeds'] != list(SEEDS) or definition['declared_proposals'] != 96):
        raise ValueError('Do not add or remove original proposal cells')
    for name, parent in parents.items():
        expected_rule = make_rule(read(parent['manifest']['label_rule_path']), {'mode': 'train_collection', 'seeds': list(SEEDS)})
        if read(path.parent/'rules'/(name+'.json')) != expected_rule:
            raise ValueError('T0 v2 changed the original physical label thresholds')
    if require_frozen and any(p.stat().st_mode & 0o222 for p in path.parent.rglob('*') if p.is_file()):
        raise ValueError('Frozen acceptance sources and definition must be read-only')
    return definition, plan, parents


def freeze(path):
    path = Path(path).resolve();definition, _, _ = load_acceptance(path, False)
    definition.update(status='frozen', frozen_at_utc=now());save(path, definition)
    for item in sorted(path.parent.rglob('*'), reverse=True):item.chmod(0o555 if item.is_dir() else 0o444)
    path.parent.chmod(0o555)
    return {'status': 'FROZEN_MATCHED_T0_PHYSICAL_FOLLOWUP_NOT_DISPATCHED', 'plan': str(path),
        'new_model_calls': 0, 'new_physical_calls': 0}


def verify_raw(plan, context, seed, directory, tokenizer):
    """Independently bind an original actual response to its exact matched request."""
    directory = Path(directory);attempt = read(directory/'attempt.json')
    body = read(directory/'request.json')
    validate_request(body, plan)
    if (body['request']['task_packet']['task_id'] != context['task_id'] or body['sampling']['seed'] != seed
            or attempt['initial_state_id'] != context['initial_state_id'] or attempt['seed'] != seed
            or body['request']['task_packet']['visible_sources'] != context['base_source']
            or attempt.get('model_calls_attempted') != 1):
        raise ValueError('Raw source/context/seed binding differs')
    if not (directory/'response.json').exists() and attempt.get('error'):
        return {'status': 'ORIGINAL_PROPOSAL_FAILED_NO_RESPONSE', 'attempt': attempt}
    response = read(directory/'response.json')
    if (attempt.get('inference_id') != response.get('inference_id')
            or not response.get('inference_id') or attempt.get('usage') != response.get('usage')
            or attempt.get('model') != response.get('model')):
        raise ValueError('Raw source/context/seed/inference/usage binding differs')
    if attempt.get('http_status') != 200 or attempt.get('error') or response.get('error'):
        return {'status': 'ORIGINAL_PROPOSAL_FAILED', 'attempt': attempt}
    usage = response['usage'];model = response['model']
    if (response.get('native_tools') != [] or model.get('source_role') != 'base_model_formal_train_action_proposals'
            or model.get('variant') != 'T0' or model.get('base_revision') != REVISION
            or model.get('tokenizer_revision') != REVISION or model.get('adapter') is not None
            or any(model.get('settings', {}).get(k) != v for k, v in
                {'quantization': 'NF4', 'double_quantization': True, 'compute_dtype': 'bfloat16',
                 'attention_backend': 'sdpa', 'max_new_tokens': 1024, 'maximum_context_tokens': 16384}.items())
            or usage.get('decoding_settings') != {'do_sample': True, 'temperature': .7, 'top_p': .95, 'seed': seed}
            or usage.get('request_mode') != MODE or usage.get('output_format') != 'ordinary_action_json'
            or usage.get('maximum_context_tokens') != 16384 or usage.get('max_new_tokens') != 1024
            or usage.get('eos_terminated') is not True
            or not 0 < usage.get('server_wall_seconds', float('inf')) <= 240
            or not 0 < attempt.get('wall_seconds', float('inf')) <= 240):
        raise ValueError('Actual T0 model, sampling, complete output or finite inference budget differs')
    flight = prompt_token_budget(tokenizer, decision_prompt(body['request']), {'max_context_tokens': 16384, 'max_new_tokens': 1024})
    action = validate_action(response['action'], body['request']['task_packet'])
    if (action['action'] != 'propose_patch' or json.loads(response['raw_action_text']) != action
            or not flight['fits_with_full_output_reserve'] or usage['input_tokens'] != flight['prompt_tokens']
            or len(tokenizer(response['raw_action_text'], add_special_tokens=False)['input_ids'])+1 > 1024
            or not 0 < usage['output_tokens'] <= 1024):
        raise ValueError('The exact original ordinary ACTION or its measured tokenizer budget differs')
    with tempfile.TemporaryDirectory(prefix='iscas-t0-exact-followup-') as temporary:
        root = Path(temporary)
        for name, text in context['base_source'].items():
            target = root/name;target.parent.mkdir(parents=True, exist_ok=True);target.write_text(text)
        try:apply_source_patch(root, action['patch'], list(context['base_source']))
        except (ValueError, subprocess.CalledProcessError) as error:
            return {'status': 'INVALID_ORIGINAL_PATCH', 'attempt': attempt, 'error': str(error), 'stderr': getattr(error, 'stderr', None)}
        edited = {name: (root/name).read_text() for name in context['base_source']}
    if edited != read(directory/'candidate_source.json'):raise ValueError('Saved candidate source differs from the unmodified actual patch')
    try:
        for text in edited.values():ast.parse(text)
    except (SyntaxError, ValueError) as error:return {'status': 'SOURCE_NOT_PARSEABLE', 'attempt': attempt, 'error': str(error)}
    if identity(edited) == identity(context['base_source']):return {'status': 'SEMANTIC_NOOP', 'attempt': attempt}
    return {'status': 'ELIGIBLE_UNIQUE_CHECK_PENDING', 'source': edited, 'patch': action['patch'],
        'attempt': attempt, 'request': body['request'], 'raw_response': str(directory/'response.json')}


def merge_registries(registries):
    lineages = {};points = {}
    for registry in registries:
        for row in registry['lineages']:
            if row['lineage_id'] in lineages and lineages[row['lineage_id']] != row:
                raise ValueError('Shared lineage has different source/split assignments')
            lineages[row['lineage_id']] = row
        for row in registry['configurations']:
            if row['configuration_id'] in points:raise ValueError('Parent configuration IDs must remain distinct')
            points[row['configuration_id']] = row
    return {'status': 'frozen', 'lineages': list(lineages.values()), 'configurations': list(points.values()),
        'topology_holdouts': sorted({v for registry in registries for v in registry.get('topology_holdouts', [])})}


def runtime_binding(manifest, parent):
    if manifest['phase'] != 'formal_train' or manifest['representation'] != 'G2' or manifest['fidelity'] != 'pex_spice':
        raise ValueError('Baseline is not a matching formal train full-fidelity isolated run')
    for stage in ('candidate', 'trusted'):
        if stage not in manifest:continue
        argv = manifest[stage]['argv']
        if (parent['container_image'] not in argv or str(ROOT/'runtime/GLdev')+':/headless/conda-env/miniconda3/envs/GLdev:ro' not in argv
                or argv[argv.index('--cpus')+1] != '2' or argv[argv.index('--memory')+1] != '8g'):
            raise ValueError('Original baseline image/runtime/resource binding differs')
        if stage == 'trusted' and str(parent['magic_runtime'])+':/work/runtime/magic-8.3.685:ro' not in argv:
            raise ValueError('Original baseline uses another Magic runtime')


def candidate_row(context, parent, proposal, seed):
    task = proposal['request']['task_packet'];state = context['state']
    points = [p for p in parent['registry']['configurations'] if p['parent_lineage'] == state['parent_lineage']
        and (not state.get('task_id') or p['contract']['task_id'] == state['task_id'])]
    if len(points) != 9:raise ValueError('This candidate must retain its exact frozen nine-point domain')
    visible = {k: v for k, v in task.items() if k != 'visible_sources'}
    visible.update(task_id=points[0]['contract']['task_id'], editable_paths=list(context['base_source']))
    return {'candidate_id': 'matched_T0__'+context['initial_state_id']+'__seed_'+str(seed),
        'initial_state_id': context['initial_state_id'], 'parent_lineage': state['parent_lineage'],
        'split': 'train', 'source_role': 'formal_train', 'origin': state['origin'], 'ancestry': state['ancestry'],
        'pdk_revision': parent['manifest']['pdk_revision'], 'base_source': context['base_source'],
        'candidate_source': proposal['source'], 'candidate_patch': proposal['patch'],
        'visible_contract': visible, 'visible_feedback': proposal['request']['visible_history'],
        'proposal_generation': {**proposal['attempt'], 'seed': seed, 'proposer_cohort': 'matched_T0',
            'actual_raw_response': proposal['raw_response']}, 'outcomes': []}


def baseline_bindings(context, parent, registry, row):
    work = Path(parent['manifest']['output_root'])/context['initial_state_id']
    raw = read(work/'baseline_results.json');points = [p for p in registry['configurations']
        if p['contract']['task_id'] == row['visible_contract']['task_id'] and p['parent_lineage'] == row['parent_lineage']]
    if len(raw) != 9 or set(raw) != {p['configuration_id'] for p in points}:
        raise ValueError('The parent must have all nine actual original-source baseline records')
    store = TrustedPhysicalStore(ROOT, registry);baseline_id = context['initial_state_id']+'__baseline';result = {};baseline = {}
    for point in points:
        run = Path(raw[point['configuration_id']]['run_directory']).resolve()
        manifest = read(run/'manifest.json');runtime_binding(manifest, parent['manifest'])
        evidence = str((run/'manifest.json').relative_to(ROOT))
        checked = store._read_run(evidence, row, point['configuration_id'], context['base_source'], baseline_id)
        result[point['configuration_id']] = {'evidence_path': evidence, 'baseline_candidate_id': baseline_id,
            'checked': checked, 'new_baseline_calls': 0, 'origin_run_directory': str(run)}
        baseline[point['configuration_id']] = {'result': raw[point['configuration_id']], 'checked': checked}
    task, history = parent['collector'].packet(parent['manifest'], context['state'], points, baseline)
    if task != read(context['materialized_task_packet']) or history != read(context['materialized_visible_history']):
        raise ValueError('The actual parent baseline does not reproduce its complete matched packet/history')
    return result


def gpt_duplicates(context, parent, source):
    """Record actual same-context source provenance, never reuse GPT candidate labels."""
    path = Path(parent['manifest']['output_root'])/'candidates.jsonl'
    if not path.exists():return [], 'parent candidate pool not yet present'
    try:rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except json.JSONDecodeError:return [], 'parent candidate pool currently partial; cross-cohort uniqueness not established'
    matches = []
    for row in rows:
        if (row['initial_state_id'] != context['initial_state_id'] or row['base_source'] != context['base_source']
                or identity(row['candidate_source']) != identity(source)):continue
        bind_candidate_edit(row, list(context['base_source']))
        matches.append({'candidate_id': row['candidate_id'], 'raw_candidates': str(path),
            'scope': 'Same complete source context and terminal AST; no GPT physical result adopted as T0 evidence'})
    return matches, 'only already materialized actual GPT candidates inspected'


def combined_registry(parents):
    registries = []
    for parent in parents.values():
        actual = Path(parent['manifest']['output_root'])/'effective_registry.json'
        registries.append(bound_registry(parent['registry'], read(actual)) if actual.exists() else parent['registry'])
    return merge_registries(registries)


def raw_matrix(plan):
    rows = read(Path(plan['output_root'])/'matrix.json')
    actual = [(r['initial_state_id'], r['seed']) for r in rows]
    expected = [(c['initial_state_id'], seed) for c in plan['contexts'] for seed in SEEDS]
    if len(actual) != 96 or len(set(actual)) != 96 or set(actual) != set(expected):
        raise ValueError('Keep the exact original96 proposal identities, including NOT_RUN')
    return {key: row for key, row in zip(actual, rows)}


def scan_returned(definition, plan, parents, state, output, tokenizer):
    """One finite scan of existing raw; no polling/model requests or relabelling raw."""
    matrix = raw_matrix(plan);save(output/'original_proposal_matrix_snapshot.json', list(matrix.values()))
    registry = combined_registry(parents);save(output/'effective_registry.json', registry)
    contexts = {c['initial_state_id']: c for c in plan['contexts']}
    seen = {name: {identity(c['base_source']): 'initial_source'} for name, c in contexts.items()}
    for cell in state['cells']:
        if cell.get('candidate_file'):
            candidate = read(output/cell['candidate_file'])
            seen[cell['initial_state_id']][identity(candidate['candidate_source'])] = candidate['candidate_id']
    for cell in state['cells']:
        raw = matrix[(cell['initial_state_id'], cell['seed'])];cell['original_proposal_status'] = raw['status']
        if cell['status'] != 'NOT_RUN':continue
        if raw['status'] == 'NOT_RUN':continue
        if raw['status'] == 'CONTEXT_OVERFLOW_NO_REQUEST':
            cell['status'] = raw['status'];cell['new_physical_calls'] = 0;continue
        context = contexts[cell['initial_state_id']];parent = parents[context['parent_collection']]
        directory = Path(plan['output_root'])/cell['initial_state_id']/('seed_'+str(cell['seed']))
        if raw.get('attempt_path') != str(directory/'attempt.json'):
            raise ValueError('Original attempt path differs from its frozen state/seed slot')
        proposal = verify_raw(plan, context, cell['seed'], directory, tokenizer)
        cell['proposal_audit'] = {k: v for k, v in proposal.items() if k not in ('source', 'patch', 'request')}
        if proposal['status'] != 'ELIGIBLE_UNIQUE_CHECK_PENDING':cell['status'] = proposal['status'];continue
        key = identity(proposal['source'])
        if key in seen[context['initial_state_id']]:
            cell.update(status='SEMANTIC_DUPLICATE_NOT_NEW_SAMPLE', duplicate_of=seen[context['initial_state_id']][key]);continue
        matches, scope = gpt_duplicates(context, parent, proposal['source'])
        cell.update(GPT_same_AST_matches=matches, GPT_duplicate_inspection_scope=scope)
        if matches:
            cell.update(status='EXACT_GPT_AST_DUPLICATE_NOT_NEW_SAMPLE', duplicate_of=matches[0]['candidate_id']);continue
        row = candidate_row(context, parent, proposal, cell['seed'])
        mapped = student_request({k: row[k] for k in ('base_source', 'visible_contract', 'visible_feedback')}, CONTEXT_VERSION, 16384)
        from src.student_interface import PolicyBudgetError
        try:encoded = encode_policy_action(tokenizer, mapped, row['candidate_patch'], 16384, 1024)
        except PolicyBudgetError as error:
            cell.update(status='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS', student_budget=error.details);continue
        cell['student_budget'] = {'prompt_tokens': encoded.prompt_tokens, 'completion_tokens_including_EOS': encoded.completion_tokens,
            'total_tokens': len(encoded.input_ids), 'source_truncated': False}
        baselines = baseline_bindings(context, parent, registry, row)
        folder = output/'candidates'/row['candidate_id'];folder.mkdir(parents=True, exist_ok=False)
        workspace(Path(parent['manifest']['source_pack']), parent['files'], row['candidate_source'], folder/'source')
        save(folder/'baseline_adoption.json', baselines);save(folder/'candidate.json', row)
        cell.update(status='PHYSICAL_PENDING', candidate_file=str((folder/'candidate.json').relative_to(output)),
            parent_collection=context['parent_collection'], baseline_adoption=str((folder/'baseline_adoption.json').relative_to(output)),
            points=[{'configuration_id': name, 'status': 'NOT_RUN'} for name in baselines])
        seen[context['initial_state_id']][key] = row['candidate_id']
    return registry


def point_call(parent, point, row, source, folder, deadline):
    began = time.monotonic()
    folder.mkdir(parents=True, exist_ok=False)
    save(folder/'reservation.json', {'candidate_id': row['candidate_id'], 'configuration_id': point['configuration_id'],
        'source': str(source), 'reserved_at_utc': now(), 'fidelity': 'pex_spice', 'phase': 'formal_train', 'automatic_retry': False})
    runtime = parent['manifest']
    runner = CandidateExecutor(ROOT/'runtime/GLdev', folder/'physical', Path(runtime['magic_runtime']),
        image=runtime['container_image'], timeout=runtime['physical']['evaluator_timeout_seconds'])
    result = runner.execute(source_dir=source, source_paths=parent['files'], entrypoint='generator.py', representation='G2',
        configuration=point['parameters'], trusted_dir=runtime['trusted_bundle'], trusted_paths=list(point['trusted_evaluator_files']),
        fidelity='pex_spice', phase='formal_train', context={key: row[key] for key in
            ('candidate_id', 'initial_state_id', 'parent_lineage', 'split', 'source_role', 'pdk_revision')}|
            {'configuration_id': point['configuration_id'], 'reference_id': point['reference_id']},
        generation_timeout_seconds=runtime['physical']['generation_timeout_seconds'],
        evaluator_timeout_seconds=runtime['physical']['evaluator_timeout_seconds'], execution_deadline_utc=deadline)
    save(folder/'result.json', result)
    run = Path(result['run_directory']);manifest = read(run/'manifest.json');stages = {}
    for name in ('candidate', 'trusted'):
        if name not in manifest:continue
        usage = run/(name+'_stage/resource_usage.json')
        raw = read(usage) if usage.exists() else None
        stages[name] = {'wall_seconds': manifest[name]['wall_seconds'],
            'waited_child_CPU_seconds': raw['child_user_cpu_seconds']+raw['child_system_cpu_seconds'] if raw else None,
            'raw_usage': str(usage) if raw else None}
    save(folder/'actual_cost.json', {'physical_point_calls': 1, 'new_model_calls': 0,
        'wall_seconds': time.monotonic()-began, 'stages': stages,
        'scope': 'Actual full-call wall and container child telemetry; missing CPU is null, no provider inference cost added again'})
    return result


def pending_points(state):
    return [(cell, point) for cell in state['cells'] if cell['status'] == 'PHYSICAL_PENDING'
        for point in cell['points'] if point['status'] == 'NOT_RUN']


def physical_pass(definition, parents, registry, state, output, sample=resource_sample, execute_point=point_call, check_implementation=lambda: None):
    """At most two2CPU point calls. Reservations are never automatically retried."""
    store = TrustedPhysicalStore(ROOT, registry);active = {}
    with ThreadPoolExecutor(max_workers=2) as workers:
        while active or pending_points(state):
            dispatched = False
            for future in list(active):
                if not future.done():continue
                cell, job = active.pop(future);row = read(output/cell['candidate_file'])
                try:
                    result = future.result();run = Path(result['run_directory']).resolve()
                    job['evidence_path'] = str((run/'manifest.json').relative_to(ROOT))
                    baseline = read(output/cell['baseline_adoption'])[job['configuration_id']]
                    point = store._configuration(row, job['configuration_id'])
                    row['outcomes'].append({'configuration_id': job['configuration_id'], 'role': point['domain_role'],
                        'evidence_path': job['evidence_path'], 'baseline_evidence_path': baseline['evidence_path'],
                        'baseline_candidate_id': baseline['baseline_candidate_id']})
                    save(output/cell['candidate_file'], row)
                    job['checked'] = store._read_run(job['evidence_path'], row, job['configuration_id'], row['candidate_source'], row['candidate_id'])
                    job.update(status='COMPLETE', returned_at_utc=now())
                except Exception as error:
                    job.update(status='UNKNOWN_NO_RETRY', error=type(error).__name__+': '+str(error), returned_at_utc=now())
                    cell['status'] = 'QUARANTINED_UNKNOWN';state['status'] = 'PAUSED_UNKNOWN'
                save(output/'state.json', state)
            if state['status'].startswith('PAUSED'):
                if active:wait(active, return_when=FIRST_COMPLETED, timeout=5);continue
                break
            if datetime.now(timezone.utc) >= datetime.fromisoformat(state['deadline_utc']):
                state['dispatch_window_ended'] = True
                if active:wait(active, return_when=FIRST_COMPLETED, timeout=5);continue
                break
            pending = pending_points(state)
            if pending and len(active) < 2:
                resource = sample();state['resource_samples'].append(resource)
                if resource['available_disk_GiB'] < 4:
                    state['status'] = 'PAUSED_STORAGE'
                    if active:wait(active, return_when=FIRST_COMPLETED, timeout=5);continue
                    break
                if resource['actual_busy_cores']+2 <= 24 and resource['RAM_used_GiB'] <= 190:
                    check_implementation()
                    cell, job = pending[0];row = read(output/cell['candidate_file'])
                    point = store._configuration(row, job['configuration_id']);parent = parents[cell['parent_collection']]
                    folder = output/'candidates'/row['candidate_id']/'points'/job['configuration_id']
                    if folder.exists():
                        job.update(status='UNRESOLVED_EXISTING_POINT_NO_RETRY');state['status'] = 'PAUSED_UNKNOWN';continue
                    job.update(status='DISPATCH_RESERVED', reserved_at_utc=now(), resources_before_dispatch=resource)
                    cell['physical_point_reservations'] = cell.get('physical_point_reservations', 0)+1
                    save(output/'state.json', state)
                    future = workers.submit(execute_point, parent, point, row,
                        (output/cell['candidate_file']).parent/'source', folder, state['deadline_utc'])
                    active[future] = (cell, job)
                    dispatched = True
            if dispatched:continue
            if active:wait(active, return_when=FIRST_COMPLETED, timeout=5)
            elif pending:time.sleep(5)
    return state


def derive(definition, parents, registry, state, output, tokenizer, plan_folder):
    admitted = [];rows = [];rejections = [];store = TrustedPhysicalStore(ROOT, registry)
    for cell in state['cells']:
        if not cell.get('candidate_file'):continue
        row = read(output/cell['candidate_file']);rows.append(row)
        if not cell.get('points') or not all(p['status'] == 'COMPLETE' for p in cell['points']):continue
        try:
            accepted = admit_candidates([row], registry, store);admitted.extend(accepted);cell['status'] = 'ADMITTED_COMPLETE_DOMAIN'
        except (ValueError, OSError, KeyError) as error:
            cell['status'] = 'QUARANTINED_ADMISSION';state['status'] = 'PAUSED_UNKNOWN'
            rejections.append({'candidate_id': row['candidate_id'], 'error': str(error)})
    (output/'candidates.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows))
    save(output/'physical_readmission.json', {'status': 'QUARANTINED' if rejections or state['status'] == 'PAUSED_UNKNOWN' else 'READMITTED_ACTUAL_COMPLETE_DOMAINS',
        'raw_candidates': len(rows), 'admitted_candidates': len(admitted), 'rejections': rejections,
        'unknowns_used_as_negatives': False, 'baseline_new_calls': 0, 'evidence_root': str(ROOT)})
    if state['status'] == 'PAUSED_UNKNOWN':
        invalidate_derivation(output);return
    closed = {c['initial_state_id'] for c in state['cells'] if c['status'] not in ('NOT_RUN', 'PHYSICAL_PENDING')}
    closed = {name for name in closed if all(c['status'] not in ('NOT_RUN', 'PHYSICAL_PENDING')
        for c in state['cells'] if c['initial_state_id'] == name)}
    implementation = module(plan_folder/'interface/src/training_selection_v2.py', '_matched_t0_frozen_v2_selection')
    legacy = module(plan_folder/'interface/base_selection.py', '_matched_t0_frozen_legacy_selection')
    datasets = {name: [] for name in ('T1', 'T2', 'T3', 'T4')};reports = []
    for name in parents:
        states = {c['initial_state_id'] for c in state['cells'] if c.get('parent_collection') == name}
        pool = [r for r in admitted if r['initial_state_id'] in states & closed]
        if not pool:continue
        groups, selection = implementation.build_matched_samples_v2(pool, read(plan_folder/'rules'/(name+'.json')), legacy)
        mapped, budget = derive_matched_samples(groups, tokenizer, 16384, interface_version=CONTEXT_VERSION)
        for method in datasets:datasets[method].extend(mapped[method])
        reports.append({'parent_collection': name, 'physical_selection': selection, 'student_budget_selection': budget})
    for method, values in datasets.items():
        (output/(method+'.jsonl')).write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in values))
    samples = [row['raw_sample'] for rows in datasets.values() for row in rows]
    save(output/'trusted_evidence_manifest.json', {'status': 'admitted', 'role': 'formal_train',
        'readmission_report': 'physical_readmission.json', 'evidence_root': str(ROOT),
        'admitted_sample_ids': [row['sample_id'] for row in samples],
        'sample_sha256': {row['sample_id']: sample_identity(row) for row in samples}})
    save(output/'student_selection.json', {'status': 'DERIVED_REQUIRES_TRAINING_MANIFEST_FREEZE',
        'proposer_cohort': 'matched_T0_eight_seed_independent_v2', 'raw_collection_root': str(output),
        'source_contexts_shared_with_GPT': True, 'additional_independent_contexts': 0,
        'closed_initial_states': sorted(closed), 'source_lineages': 1, 'planned_proposals': 96,
        'effective_samples_by_method': {name: len(rows) for name, rows in datasets.items()},
        'physical_readmission_report': 'physical_readmission.json', 'raw_evidence_re_admitted': True,
        'effective_registry_path': str(output/'effective_registry.json'), 'evidence_root': str(ROOT),
        'reports': reports, 'formal_training_started': False,
        'scope': 'T0 only; Point/Family share this admitted pool. Do not sum independent contexts across GPT/T0. A future cross-proposer data freeze must deduplicate actual context and terminal AST.'})


def invalidate_derivation(output):
    save(output/'trusted_evidence_manifest.json', {'status': 'quarantined', 'role': 'formal_train',
        'admitted_sample_ids': [], 'sample_sha256': {}, 'reason': 'Current acceptance is paused on unknown evidence; no negative labels or final dataset inferred'})
    save(output/'student_selection.json', {'status': 'QUARANTINED_NO_CURRENT_USABLE_DATASET',
        'formal_training_started': False, 'raw_retained': True})


def verify_code(path, definition):
    for name in definition['implementation_files']:
        if (ROOT/name).read_bytes() != (Path(path).parent/'interface'/name).read_bytes():
            raise ValueError('Frozen acceptance code changed before next dispatch: '+name)


def initial_state(definition):
    return {'status': 'RUNNING', 'role': ROLE, 'started_at_utc': now(),
        'deadline_utc': (datetime.now(timezone.utc)+timedelta(hours=definition['physical']['maximum_dispatch_hours'])).isoformat(),
        'new_model_calls': 0, 'new_baseline_calls': 0, 'automatic_physical_retry': False,
        'resource_samples': [], 'metadata_waits': [],
        'cells': [{'initial_state_id': c['initial_state_id'], 'parent_collection': c['parent_collection'],
            'seed': seed, 'status': 'NOT_RUN'} for c in definition['contexts'] for seed in SEEDS]}


def mark_orphaned_reservations(state):
    for cell in state['cells']:
        for point in cell.get('points', []):
            if point['status'] == 'DISPATCH_RESERVED':
                point['status'] = 'UNRESOLVED_RESERVATION_NO_RETRY';cell['status'] = 'QUARANTINED_UNKNOWN'
                state['status'] = 'PAUSED_UNKNOWN'
    return state


def completion(state):
    from collections import Counter
    points = [p for cell in state['cells'] for p in cell.get('points', [])]
    return {'status': state['status'], 'planned_proposals': 96, 'declared_original_contexts': 12,
        'source_programs': 6, 'source_lineages': 1, 'additional_independent_contexts': 0,
        'original_proposal_status_counts': dict(Counter(cell.get('original_proposal_status', 'NOT_RUN') for cell in state['cells'])),
        'followup_status_counts': dict(Counter(cell['status'] for cell in state['cells'])),
        'point_status_counts': dict(Counter(p['status'] for p in points)),
        'actual_reserved_candidate_points': sum(p['status'] != 'NOT_RUN' for p in points),
        'actual_returned_point_records': sum('evidence_path' in p for p in points),
        'maximum_candidate_points': 864, 'new_baseline_points': 0, 'new_model_calls': 0,
        'deadline_utc': state['deadline_utc'], 'automatic_retry': False, 'formal_model_training_runs': 0,
        'raw_proposal_costs': 'Original sampler attempts/response usage retained as source records; not new model cost of this follow-up',
        'finished_at_utc': now()}


def run(path):
    path = Path(path).resolve();definition, plan, parents = load_acceptance(path)
    output = Path(definition['output_root']).resolve();output.relative_to(ROOT/'runs/train_collection')
    output.mkdir(parents=True, exist_ok=True)
    if str(ROOT) != definition['evidence_root']:raise ValueError('Run on the exact declared private execution endpoint')
    with (output/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (output/'acceptance.json').exists():
            if read(output/'acceptance.json') != definition:raise ValueError('Existing output belongs to another immutable acceptance plan')
        else:save(output/'acceptance.json', definition)
        state = read(output/'state.json') if (output/'state.json').exists() else initial_state(definition)
        expected = [(c['initial_state_id'], seed) for c in definition['contexts'] for seed in SEEDS]
        actual = [(c['initial_state_id'], c['seed']) for c in state['cells']]
        if state.get('role') != ROLE or actual != expected:
            raise ValueError('Resume must retain the original96 cells in their frozen order')
        state = mark_orphaned_reservations(state)
        if state['status'].startswith('PAUSED') or state['status'] in ('COMPLETE', 'WINDOW_ENDED'):
            save(output/'state.json', state);return completion(state)
        from transformers import AutoTokenizer
        cache = read(ROOT/'configs/training/backbone_cache.json')
        if cache['revision'] != REVISION:raise ValueError('The exact pinned tokenizer is required; no model is loaded')
        tokenizer = AutoTokenizer.from_pretrained(cache['snapshot'], local_files_only=True, trust_remote_code=False)
        while datetime.now(timezone.utc) < datetime.fromisoformat(state['deadline_utc']):
            state.update(status='RUNNING', coordinator_pid=os.getpid())
            try:
                registry = scan_returned(definition, plan, parents, state, output, tokenizer)
                save(output/'state.json', state)
                physical_pass(definition, parents, registry, state, output,
                    check_implementation=lambda: verify_code(path, definition))
                derive(definition, parents, registry, state, output, tokenizer, path.parent)
            except json.JSONDecodeError as error:
                # The original sampler/collector writes JSON in place. Only a
                # metadata read is retried, never a proposal or physical call.
                state['metadata_waits'].append({'at_utc': now(), 'error': str(error)})
                state['status'] = 'WAITING_FOR_COMPLETE_ORIGINAL_JSON'
                save(output/'state.json', state);time.sleep(5);continue
            except Exception as error:
                state.update(status='PAUSED_UNKNOWN', error=type(error).__name__+': '+str(error));break
            if state['status'].startswith('PAUSED') or state.get('dispatch_window_ended'):break
            if not any(cell['status'] in ('NOT_RUN', 'PHYSICAL_PENDING') for cell in state['cells']):
                state['status'] = 'COMPLETE';break
            sampler_terminal = Path(plan['output_root'])/'completion.json'
            if sampler_terminal.exists():
                for cell in state['cells']:
                    if cell['status'] == 'NOT_RUN':cell['status'] = 'ORIGINAL_NOT_RUN_SAMPLER_WINDOW_ENDED'
                derive(definition, parents, registry, state, output, tokenizer, path.parent)
                if not state['status'].startswith('PAUSED'):state['status'] = 'COMPLETE'
                break
            state['status'] = 'WAITING_FOR_ALREADY_DECLARED_PROPOSALS'
            save(output/'state.json', state);time.sleep(5)
        else:state['status'] = 'WINDOW_ENDED'
        if state.get('dispatch_window_ended') and not state['status'].startswith('PAUSED'):state['status'] = 'WINDOW_ENDED'
        state.update(coordinator_pid=None, ended_at_utc=now());save(output/'state.json', state)
        if state['status'] == 'PAUSED_UNKNOWN':invalidate_derivation(output)
        result = completion(state);save(output/'completion.json', result)
        return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare', action='store_true');g.add_argument('--freeze', action='store_true')
    g.add_argument('--validate-only', action='store_true');g.add_argument('--execute', action='store_true')
    p.add_argument('--proposal-plan', type=Path);p.add_argument('--folder', type=Path)
    p.add_argument('--output-root', type=Path);p.add_argument('--plan', type=Path)
    p.add_argument('--dispatch-hours', type=float, default=8)
    args = p.parse_args()
    if args.prepare:
        if any(v is None for v in (args.proposal_plan, args.folder, args.output_root)):p.error('Prepare needs proposal-plan, folder and output-root')
        value = prepare(args.proposal_plan, args.folder, args.output_root, args.dispatch_hours)
    else:
        if args.plan is None:p.error('The exact acceptance plan is required')
        value = freeze(args.plan) if args.freeze else run(args.plan) if args.execute else {
            'status': 'FROZEN_ACCEPTANCE_VALIDATED_NO_CALLS',
            'planned_proposals': load_acceptance(args.plan)[0]['declared_proposals'], 'new_model_calls': 0, 'new_physical_calls': 0}
    print(json.dumps(value, indent=2, ensure_ascii=False), flush=True)
