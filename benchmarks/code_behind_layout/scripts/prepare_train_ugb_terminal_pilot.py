"""CPU-only preparation of one fixed TRAIN terminal with a prospective UGB goal.

Historical measurements prove provenance and preview context length. They never
become baselines under the new objective/task identity. No physical/model caller
is imported by this preparer; a separately reviewed finite consumer is required.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_natural_terminal_baselines import (
    ROOT, SOURCES, CODE as PARENT_CODE, read, save, original, initial_inventory,
    distinct_initials, packet, preflight,
)
from src.train_span_proposer import teacher_request
from src.training import frozen_train_registry

SPEC = {
    'circuit_id': 'C08',
    'initial_state_id': 'natural_terminal_c08_trial7_worst_ugb_v1',
    'cohort': 'c08_minimal_gpt_teacher_v1',
    'candidate_id': 'c08_minimal_gpt_teacher_v1__c08_original_compiler_source_teacher__minimal_GPT_teacher_v1__trial_7',
    'parent_collection': 'c08_minimal_gpt_teacher_v1',
}
TASK_ID = 'train_c08_natural_terminal_worst_ugb_v1'
OBJECTIVE = {'id': 'c08_terminal_worst_ugb_max_v1', 'metric': 'ugb_Hz',
    'unit': 'Hz', 'direction': 'max', 'corner_aggregation': 'worst'}
SCOPE = 'prospective_c08_natural_terminal_ugb_v1'
GOAL = ('Increase the minimum post-PEX unity-gain bandwidth across the declared '
    'corners while satisfying every unchanged physical and electrical constraint '
    'on all nine configurations. Preserve all independent device sizes, nets, '
    'ports, public APIs, readonly caller and testbenches.')
CODE = list(dict.fromkeys([*PARENT_CODE, 'scripts/prepare_train_ugb_terminal_pilot.py',
    'scripts/run_train_ugb_terminal_baselines.py']))


def prospective_points(points):
    """Change only prospective task/scope/objective; keep all nine N(z) intact."""
    result = copy.deepcopy(points)
    if len(result) != 9 or len({p['configuration_id'] for p in result}) != 9:
        raise ValueError('Keep the fixed nine distinct C08 configurations')
    old_files = result[0]['trusted_evaluator_files']
    if any(p['trusted_evaluator_files'] != old_files for p in result):
        raise ValueError('One exact independent evaluator must bind all nine points')
    trusted = copy.deepcopy(old_files)
    for old, new in zip(points, result):
        if old['parameters']['circuit']['circuit_id'] != 'C08':
            raise ValueError('Only the fixed train-admitted C08 source is allowed')
        contract_name = 'contracts/' + old['configuration_id'] + '.json'
        if json.loads(old_files[contract_name]) != old['contract']:
            raise ValueError('The parent independent contract does not match its point')
        new['contract'].update(task_id=TASK_ID, scope=SCOPE, objective=copy.deepcopy(OBJECTIVE))
        trusted[contract_name] = json.dumps(new['contract'], indent=2) + '\n'
        new.pop('gold_control', None)
    for new in result:
        new['trusted_evaluator_files'] = copy.deepcopy(trusted)
    # Explicitly document the limited differences, including the evaluator's
    # embedded copies of the same contracts. Existing raw trees are untouched.
    changed = {name for name in trusted if trusted[name] != old_files[name]}
    expected = {'contracts/' + p['configuration_id'] + '.json' for p in points}
    if changed != expected:
        raise ValueError('Only the nine prospective contract JSON files may change')
    return result


def baseline_cells(points):
    anchors = [p for p in points if p['domain_role'] == 'anchor']
    if len(anchors) != 1:
        raise ValueError('One original anchor is required')
    anchor = anchors[0]['configuration_id']
    return ([{'cell_id': 'anchor_repeat_' + str(i), 'configuration_id': anchor,
              'role': 'new_baseline_anchor' if i == 1 else 'independent_extraction_control'}
             for i in [1, 2, 3]] +
            [{'cell_id': p['configuration_id'], 'configuration_id': p['configuration_id'],
              'role': 'new_baseline_development'} for p in points if p['configuration_id'] != anchor])


def prepare(output):
    from transformers import AutoTokenizer
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Preserve earlier preparation; use a fresh DRAFT directory')
    inventory = read(ROOT/'results/derived/train_natural_terminal_next_states_readonly_actual.json')
    selected = next(row for row in inventory['records'] if row['circuit_id'] == 'C08')
    if (selected['AST_ordinal_in_fixed_sorted_union'] != 0
            or selected['candidate_id'] != SPEC['candidate_id']
            or not selected['new_initial_full_AST_candidate']):
        raise ValueError('Keep the earliest fixed-inventory C08 terminal, without objective-based selection')
    candidate, registry, old_points, parent, names, terminal, run, verified = original(SPEC)
    existing, pools = initial_inventory()
    distinct_initials([terminal], existing)
    points = prospective_points(old_points)
    output.mkdir(parents=True)
    source = output/'source'; trusted = output/'trusted'
    for name in names:
        target = source/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run/'source'/name, target)
    for name, text in points[0]['trusted_evaluator_files'].items():
        target = trusted/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text)
    assignment = next(r for r in registry['lineages'] if r['lineage_id'] == candidate['parent_lineage'])
    assignment.update(frozen_source_pack=str(source), frozen_source_files=[n for n in names if n not in SOURCES],
        editable_paths=SOURCES, editable_paths_status='new_natural_terminal_ugb_complete_two_modules')
    registry.update(configurations=points, new_global_registry_revision=False,
        freeze_scope='same_train_assignment_new_terminal_and_prospective_objective_only')
    frozen_train_registry(registry); save(output/'registry.json', registry)
    initial = {'initial_state_id': SPEC['initial_state_id'], 'parent_lineage': candidate['parent_lineage'],
        'task_id': TASK_ID, 'origin': 'natural', 'editable_paths': SOURCES, 'base_source': terminal,
        'ancestry': {'terminal_candidate_id': candidate['candidate_id'],
            'original_initial_state_id': candidate['initial_state_id'], 'cohort': SPEC['cohort'],
            'new_initial_state_without_relabelling_old_evidence': True}}
    save(output/'initial_state.json', initial)
    documents = copy.deepcopy(candidate['visible_contract']['documents'])
    documents.update(readonly_generator_py=(source/'generator.py').read_text(),
        actual_caller_scope='Complete readonly generator.py is identical for teacher and ordinary student. Only both supplied complete modules may change.')
    collection = {'status': 'DRAFT_ZERO_DISPATCH_WAITING_SEPARATE_11POINT_CONSUMER',
        'collection_id': SPEC['initial_state_id'], 'circuit_id': 'C08',
        'source_pack': str(source), 'source_files': names, 'trusted_bundle': str(trusted),
        'registry_path': str(output/'registry.json'), 'initial_state_path': str(output/'initial_state.json'),
        'documents': documents, 'pdk_revision': candidate['pdk_revision'],
        'container_image': parent['container_image'], 'magic_runtime': parent['magic_runtime'],
        'new_lineages': 0, 'maximum_new_useful_contexts': 1,
        'teacher_dispatch': 'Forbidden before all11 new controls qualify and a separate teacher/acceptance freeze is reviewed.'}
    save(output/'collection.json', collection)
    old_rule = read(parent['label_rule_path'])
    old_objective = old_points[0]['contract']['objective']['id']
    tolerances = old_rule['objectives'][old_objective]
    label = copy.deepcopy(old_rule); label.update(status='DRAFT', version=SCOPE+'_label_v1')
    label['objectives'] = {OBJECTIVE['id']: {k: copy.deepcopy(v) for k, v in OBJECTIVE.items()
        if k in ['metric', 'unit', 'direction']}}
    for key in ['quality_absolute_tolerance', 'quality_relative_tolerance', 'quality_minimum_relative_effect']:
        label['objectives'][OBJECTIVE['id']][key] = tolerances[key]
    if tolerances['quality_minimum_relative_effect'] != .01:
        raise ValueError('The existing1% minimum label effect must remain fixed')
    save(output/'label_rule_DRAFT.json', label)
    previews = []
    for old in old_points:
        outcome = next(o for o in candidate['outcomes'] if o['configuration_id'] == old['configuration_id'])
        evidence = ROOT/outcome['evidence_path']
        if not evidence.is_file(): evidence = ROOT/'runs/train_collection'/SPEC['cohort']/outcome['evidence_path']
        record = read(evidence.parent/'evidence/validation.json')
        measured = [record['observation']['corners'][c]['metrics']['ugb_Hz'] for c in old['contract']['required_corners']]
        if any(m['unit'] != 'Hz' for m in measured): raise ValueError('Old preview UGB unit mismatch')
        previews.append({'configuration_id': old['configuration_id'], 'S2': True,
            'old_terminal_worst_ugb_Hz_preview': min(m['value'] for m in measured),
            'new_baseline_measurement': False})
    ordinary, _, _ = packet(collection, initial, points, previews, True)
    ordinary['task_packet']['goal'] = GOAL
    teacher = teacher_request(ordinary)
    tokenizer = AutoTokenizer.from_pretrained(read(ROOT/'configs/training/backbone_cache.json')['snapshot'],
        local_files_only=True, trust_remote_code=False)
    flight = preflight(tokenizer, ordinary, teacher)
    save(output/'preview_ordinary_request.json', ordinary); save(output/'preview_teacher_request.json', teacher)
    save(output/'preview_token_preflight.json', flight)
    for name in CODE:
        target = output/'code'/name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT/name, target)
    plan = {'status': 'DRAFT_CPU_ONLY_NO_DISPATCH', 'initial_state_id': SPEC['initial_state_id'],
        'collection': str(output/'collection.json'), 'cells': baseline_cells(points),
        'maximum_new_full_points': 11, 'workers': 1, 'CPU_per_stage': 2, 'RAM_per_stage_GiB': 8,
        'dispatch_horizon_seconds': 14400, 'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720,
        'resource_gate': 'busy+2<=24/RAMused<=190GiB/rootfree>=4GiB',
        'phase': 'formal_train', 'new_model_calls': 0, 'automatic_retry': False,
        'control_order': 'First3 independent anchor extractions before the remaining8 baselines.',
        'control_acceptance': 'All3 S2/full unsimplified RC graph clean/exact manufacturing GDS equal; (maxUGB-minUGB)/minUGB <0.01. Unknown or failure stops before teacher.',
        'old_measurements_relabelled': False, 'new_lineages': 0, 'CODE': CODE,
        'maximum_future_teacher_proposals': 8, 'maximum_future_candidate_points': 72,
        'origin': {'fixed_inventory': selected, 'all9_old_current_Store_S2': True,
            'old_complete_domain_evaluation': verified['complete_domain_evaluation'],
            'existing_initial_pools_checked': pools}, 'preview_token_counts': flight['token_counts']}
    save(output/'baseline_plan_DRAFT.json', plan)
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); value = prepare(args.output)
    print(json.dumps({k: v for k, v in value.items() if k not in ['origin', 'CODE']}, indent=2))
