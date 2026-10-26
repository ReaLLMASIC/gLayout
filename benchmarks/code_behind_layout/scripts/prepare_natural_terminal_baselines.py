"""Prepare only two fixed, naturally observed terminal programs as new TRAIN states.

Old measurements establish source provenance and size the preview, never replace
the eighteen fresh baseline calls. Teacher collection remains a separate DRAFT.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd().resolve(); sys.path.insert(0, str(ROOT))
from scripts.training_pilot_status import program
from src.training import TrustedPhysicalStore, frozen_train_registry
from src.train_span_proposer import teacher_request, proposal_prompt, mapping_proof
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget

SOURCES = ['textbook_sharing/layout.py', 'glayout/sharing/enumeration.py']
FIXED = [
    {'circuit_id': 'C01', 'initial_state_id': 'natural_terminal_c01_seed101_area_v1',
     'cohort': 'c01_collection_v2', 'candidate_id': 'c01_observed_T0_seed_241_source_teacher_v2__seed_101',
     'parent_collection': 'c01_collection_v2'},
    {'circuit_id': 'C02', 'initial_state_id': 'natural_terminal_c02_span1_area_v1',
     'cohort': 'literal_span_GPT_physical_v1', 'candidate_id': 'literal_span_GPT__planning_c02_program_039__trial_1',
     'parent_collection': 'c02_action_v1'},
]
CODE = ['scripts/prepare_natural_terminal_baselines.py', 'scripts/run_natural_terminal_baselines.py',
    'scripts/training_pilot_status.py', 'scripts/audit_train_pair_nf_rc.py',
    *['src/'+name+'.py' for name in ['candidate_executor', 'domain_runner', 'training',
        'measurement', 'report_parsers', 'device_intent', 'spice_validation', 'model_adapter',
        'local_model_adapter', 'policy_state', 'student_interface', 'train_span_proposer']]]


def read(path): return json.loads(Path(path).read_text())
def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n'); temporary.replace(path)


def packet(collection, state, points, summaries, preview=False):
    first = points[0]['contract']; circuit = points[0]['parameters']['circuit']
    order = [d['name'] for d in circuit['devices']]
    contract = {k: copy.deepcopy(v) for k, v in first.items() if k not in
                ('configuration_id', 'reference_id', 'scope')}
    contract.update(ports=circuit['ports'], devices=[{'name': d['name'], 'kind': d['kind'],
        'nets_D_G_S_B': d['nets']} for d in circuit['devices']],
        geometry_domain={'device_order': order, 'columns': ['w_total_um', 'l_um', 'nf'],
            'points': [{'id': p['configuration_id'], 'role': p['domain_role'], 'device_values': [
                [p['parameters']['sizing'][name][key] for key in ('w','l','nf')] for name in order]} for p in points]},
        immutable='All nine independent N(z), device graphs/sizes/ports, bias/load, PDK, testbench and physical contracts are fixed. Only the two complete provided modules are editable. The readonly generator.py document is the exact actual caller.')
    ordinary = {'task_packet': {'task_id': state['initial_state_id'],
        'goal': 'Reduce actual GDS area while satisfying the unchanged physical constraints on the complete nine-point domain. Preserve public APIs and all independent circuit intent.',
        'contract': contract, 'allowed_paths': SOURCES,
        'visible_sources': state['base_source'], 'documents': collection['documents'],
        'visible_configurations': [p['configuration_id'] for p in points],
        'budget': {'decisions': 1, 'maximum_output_tokens': 1024, 'maximum_context_tokens': 16384}},
        'visible_history': [{'observation': {'status': 'old_terminal_preview_not_new_baseline' if preview else 'begin',
            'qualification_preview' if preview else 'actual_new_baseline': summaries}}]}
    teacher = teacher_request(ordinary)
    return ordinary, teacher, mapping_proof(ordinary, teacher)


def preflight(tokenizer, ordinary, teacher):
    proof = mapping_proof(ordinary, teacher); student = proof.pop('ordinary_request')
    flights = {'teacher': prompt_token_budget(tokenizer, proposal_prompt(teacher), {'max_new_tokens': 3072, 'max_context_tokens': 16384}),
        'student': prompt_token_budget(tokenizer, decision_prompt(student), {'max_new_tokens': 1024, 'max_context_tokens': 16384})}
    if not all(row['fits_with_full_output_reserve'] for row in flights.values()):
        raise ValueError('Complete source, caller, contract and feedback do not fit; no truncation/model call allowed')
    return {'token_counts': flights, 'mapping': proof, 'model_calls': 0, 'source_or_contract_truncated': False}


def distinct_initials(selected, existing):
    identities = [program(source, source) for source in selected]
    if len(set(identities)) != len(identities) or any(identity in existing for identity in identities):
        raise ValueError('New initials must be distinct full AST pairs absent from every frozen initial pool')


def initial_inventory():
    existing = set(); pools = []
    for file in sorted((ROOT/'runtime/train_collections').glob('*/collection.json')):
        collection = read(file); states = collection.get('initial_states_path')
        source = collection.get('source_pack')
        if collection.get('status') != 'frozen' or not states or not source: continue
        original = {name: (Path(source)/name).read_text() for name in SOURCES}
        rows = [json.loads(line) for line in Path(states).read_text().splitlines() if line.strip()]
        existing.update(program(row['base_source'], original) for row in rows)
        pools.append({'collection': str(file), 'initial_states': str(states), 'states': len(rows)})
    if not pools: raise ValueError('No frozen compiler initial pools were inspected')
    return existing, pools


def ordered_domain(registry, candidate, circuit_id):
    points = [copy.deepcopy(p) for p in registry['configurations']
        if p['contract']['task_id'] == candidate['visible_contract']['task_id']]
    observed = [row['configuration_id'] for row in candidate['outcomes']]
    # Historical candidate rows were emitted in execution/completion order. The
    # prospective baseline retains the frozen registry order, not that ordering.
    if (len(points) != 9 or len(observed) != 9 or len(set(observed)) != 9
            or {p['configuration_id'] for p in points} != set(observed)
            or any(p['parameters']['circuit']['circuit_id'] != circuit_id for p in points)):
        raise ValueError('Keep the exact original ordered nine-point task domain')
    return points


def original(spec):
    cohort = ROOT/'runs/train_collection'/spec['cohort']
    rows = [json.loads(line) for line in (cohort/'candidates.jsonl').read_text().splitlines() if line.strip()]
    candidate, = [row for row in rows if row['candidate_id'] == spec['candidate_id']]
    registry = read(cohort/'effective_registry.json')
    parent = read(ROOT/'runtime/train_collections'/spec['parent_collection']/'collection.json')
    points = ordered_domain(registry, candidate, spec['circuit_id'])
    relative = Path(candidate['outcomes'][0]['evidence_path'])
    root, = [base for base in (cohort, ROOT) if (base/relative).is_file()]
    verified = TrustedPhysicalStore(root, registry)(candidate)
    checked = [verified['anchor']]+verified['family']
    if not verified['complete_domain_evaluation'] or len(checked) != 9 or not all(p['S2'] for p in checked):
        raise ValueError('The selected terminal must still pass the complete current Store')
    lineage, = [row for row in registry['lineages'] if row['lineage_id'] == candidate['parent_lineage']]
    if lineage['split'] != 'train' or candidate['origin'] != 'natural':
        raise ValueError('Only a naturally generated source in the unchanged train lineage is allowed')
    names = sorted(set(lineage['frozen_source_files']) | set(SOURCES))
    old_source = Path(lineage['frozen_source_pack'])
    base = {name: (old_source/name).read_text() for name in SOURCES}
    terminal = {name: candidate['candidate_source'].get(name, base[name]) for name in SOURCES}
    run = (root/relative).parent
    for outcome in candidate['outcomes']:
        file = root/outcome['evidence_path']; physical = file.parent
        manifest = read(file)
        if set(manifest['source_files']) != set(names): raise ValueError('Actual source closure differs')
        for name in names:
            expected = terminal[name].encode() if name in SOURCES else (old_source/name).read_bytes()
            if (physical/'source'/name).read_bytes() != expected:
                raise ValueError('Actual terminal full source differs: '+name)
        point, = [p for p in points if p['configuration_id'] == outcome['configuration_id']]
        if any((physical/'trusted'/name).read_text() != text for name, text in point['trusted_evaluator_files'].items()):
            raise ValueError('Independent trusted snapshot differs from its exact point binding')
        argv = manifest['candidate']['argv']; physical_argv = manifest['trusted']['argv']
        if (parent['container_image'] not in argv or parent['container_image'] not in physical_argv
                or not any(parent['magic_runtime'] in value for value in physical_argv)):
            raise ValueError('Original actual image/Magic differs from parent control')
    return candidate, registry, points, parent, names, terminal, run, verified


def prepare(output):
    from transformers import AutoTokenizer
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    cache = read(ROOT/'configs/training/backbone_cache.json')
    tokenizer = AutoTokenizer.from_pretrained(cache['snapshot'], local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id != 151645: raise ValueError('Unexpected pinned Qwen tokenizer')
    existing, pools = initial_inventory(); selected = []; collections = []
    for spec in FIXED:
        candidate, registry, points, parent, names, terminal, run, verified = original(spec)
        selected.append(terminal); distinct_initials(selected, existing)
        folder = output/spec['circuit_id']; folder.mkdir(); source = folder/'source'; trusted = folder/'trusted'
        for name in names:
            target = source/name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(run/'source'/name, target)
        trusted_files = points[0]['trusted_evaluator_files']
        if any(p['trusted_evaluator_files'] != trusted_files for p in points):
            raise ValueError('A single exact trusted capsule must bind all nine points')
        for name, text in trusted_files.items():
            target = trusted/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text)
        for point in points: point.pop('gold_control', None)
        assignment = next(row for row in registry['lineages'] if row['lineage_id'] == candidate['parent_lineage'])
        old_assignment = copy.deepcopy(registry['lineages'])
        assignment.update(frozen_source_pack=str(source), frozen_source_files=[n for n in names if n not in SOURCES],
            editable_paths=SOURCES, editable_paths_status='new_natural_terminal_context_complete_two_modules')
        registry.update(configurations=points, new_global_registry_revision=False,
            freeze_scope='same_train_assignment_exact_parent_nine_contracts_new_initial_source_only')
        frozen_train_registry(registry); save(folder/'registry.json', registry)
        save(folder/'parent_source_assignments.json', old_assignment)
        initial = {'initial_state_id': spec['initial_state_id'], 'parent_lineage': candidate['parent_lineage'],
            'task_id': points[0]['contract']['task_id'], 'origin': 'natural', 'editable_paths': SOURCES,
            'base_source': terminal, 'ancestry': {'terminal_candidate_id': candidate['candidate_id'],
                'original_initial_state_id': candidate['initial_state_id'], 'cohort': spec['cohort'],
                'new_initial_state_without_relabelling_old_evidence': True}}
        save(folder/'initial_state.json', initial)
        documents = copy.deepcopy(candidate['visible_contract']['documents'])
        documents.update(frozen_layout_consumer='Both complete layout.py and enumeration.py modules are editable. Preserve public build/planning APIs and return types. All other compiler, assembly, primitive, PDK and testbench source is frozen.',
            readonly_generator_py=(source/'generator.py').read_text(),
            actual_caller_scope='The complete generator.py above is readonly and used verbatim for every configuration. It is identical for teacher and ordinary student; generator.py is not an allowed edit path.')
        collection = {'status': 'DRAFT_WAITING_FRESH18_AND_SEPARATE_TEACHER_FREEZE',
            'collection_id': spec['initial_state_id'], 'circuit_id': spec['circuit_id'],
            'source_pack': str(source), 'source_files': names, 'trusted_bundle': str(trusted),
            'registry_path': str(folder/'registry.json'), 'initial_state_path': str(folder/'initial_state.json'),
            'documents': documents, 'pdk_revision': candidate['pdk_revision'],
            'container_image': parent['container_image'], 'magic_runtime': parent['magic_runtime'],
            'sampling': {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
                'seed': None, 'trials': list(range(1,9)), 'max_context_tokens': 16384, 'max_new_tokens': 3072, 'timeout_seconds': 240},
            'student': {'max_context_tokens': 16384, 'max_new_tokens': 1024},
            'new_lineages': 0, 'maximum_new_useful_contexts': 1, 'historical_contract_scope_retained_verbatim': True,
            'teacher_dispatch': 'Forbidden until all eighteen fresh baselines qualify and a separate producer/acceptance freezes after Root review.'}
        save(folder/'collection.json', collection)
        label = read(parent['label_rule_path']); objective = points[0]['contract']['objective']
        rule = label['objectives'][objective['id']]
        if (rule['quality_absolute_tolerance'], rule['quality_relative_tolerance'], rule['quality_minimum_relative_effect']) != (1e-8,1e-6,.01):
            raise ValueError('Keep the original area label threshold and tolerances')
        save(folder/'parent_label_rule.json', label)
        checked = {p['configuration_id']:p for p in [verified['anchor']]+verified['family']}
        summaries = [{key: checked[p['configuration_id']].get(key) for key in
            ('configuration_id','S0','S1','S2','objective','failure_class','reason')} for p in points]
        ordinary, teacher, _ = packet(collection, initial, points, summaries, True)
        save(folder/'preview_ordinary_request.json', ordinary); save(folder/'preview_teacher_request.json', teacher)
        flight = preflight(tokenizer, ordinary, teacher); flight.update(actual_formal_feedback_recount_required=True,
            feedback_scope='Original terminal current-Store measurements are preview only, never new baseline labels')
        save(folder/'preview_token_preflight.json', flight)
        save(folder/'origin_control.json', {'original_candidate_id': candidate['candidate_id'], 'original_initial_state_id': candidate['initial_state_id'],
            'original_run': str(run), 'current_Store_all9_S2': True, 'source_bytes_all9_exact': True,
            'old_points_relabelled': False, 'new_model_calls': 0, 'new_physical_calls': 0})
        collections.append({'circuit_id': spec['circuit_id'], 'initial_state_id': spec['initial_state_id'],
            'folder': str(folder), 'configuration_ids': [p['configuration_id'] for p in points]})
    for name in CODE:
        target = output/'code'/name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT/name, target)
    plan = {'status': 'PREPARED_TWO_NATURAL_TERMINAL_FRESH18_BASELINE_DRAFT',
        'prepared_at_utc': datetime.now(timezone.utc).isoformat(), 'fixed_order': FIXED, 'collections': collections,
        'CODE': CODE, 'phase': 'formal_train', 'workers': 1, 'CPUs': 2, 'memory_GiB': 8,
        'dispatch_horizon_seconds': 14400, 'maximum_new_full_points': 18,
        'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720,
        'resource_gate': {'busy_plus_2_max': 24, 'RAM_used_GiB_max': 190, 'root_free_GiB_min': 4},
        'new_model_calls': 0, 'development_evidence_relabelled': False, 'old_formal_evidence_relabelled': False,
        'automatic_retry': False, 'output_root': str(ROOT/'runs/train_collection/natural_terminal_fresh18_v1'),
        'teacher_collections_status': 'DRAFT', 'new_AST_pairs': 2, 'new_lineages': 0,
        'inspected_frozen_initial_ASTs': len(existing), 'inspected_initial_pools': pools}
    save(output/'baseline_plan.json', plan)
    return {'status': plan['status'], 'plan': str(output/'baseline_plan.json'),
        'preview_preflights': {c['circuit_id']: read(Path(c['folder'])/'preview_token_preflight.json')['token_counts'] for c in collections},
        'current_Store_complete_controls': 18, 'new_model_calls': 0, 'new_physical_calls': 0}


def freeze(output):
    output = Path(output).resolve(); plan = read(output/'baseline_plan.json')
    if plan['status'] != 'PREPARED_TWO_NATURAL_TERMINAL_FRESH18_BASELINE_DRAFT': raise ValueError('Only the prepared DRAFT may freeze once')
    for name in CODE:
        if (ROOT/name).read_bytes() != (output/'code'/name).read_bytes(): raise ValueError('Implementation changed since preparation: '+name)
    plan.update(status='FROZEN_TWO_NATURAL_TERMINAL_FRESH18_BASELINE_ONLY', frozen_at_utc=datetime.now(timezone.utc).isoformat())
    save(output/'baseline_plan.json', plan)
    save(output/'freeze_identity.json', {str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob('*')) if p.is_file() and '__pycache__' not in p.parts})
    for p in sorted(output.rglob('*'), key=lambda p:len(p.parts), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status': plan['status'], 'plan': str(output/'baseline_plan.json'), 'model_calls': 0, 'new_physical_calls': 0}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--freeze',action='store_true'); a=p.parse_args()
    print(json.dumps(freeze(a.output) if a.freeze else prepare(a.output),indent=2),flush=True)
