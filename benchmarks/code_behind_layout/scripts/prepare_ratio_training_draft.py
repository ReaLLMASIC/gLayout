"""Prepare the next train-only ratio context after all nine fresh controls pass.

This writes a DRAFT only. It neither changes the global registry nor starts a
proposal producer, physical candidate collection, data admission or training.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.prepare_ratio_source_train_baselines import read, save, packet, token_preflight, EDITABLE
from scripts.run_ratio_source_train_baselines import load, check_result
from scripts.prepare_ratio_train_context import add_caller
from src.train_span_proposer import mapping_proof


def validate_completion(terminal, fixed_order):
    if (terminal.get('status') != 'COMPLETED_FORMAL_RATIO_FRESH9_ALL_QUALIFIED_NO_MODELS'
            or terminal.get('qualified_points') != 9 or terminal.get('not_run')
            or len(terminal.get('cells', [])) != 9
            or [c['configuration_id'] for c in terminal['cells']] != fixed_order
            or any(c['status'] != 'COMPLETE_QUALIFIED_FORMAL_BASELINE' for c in terminal['cells'])):
        raise ValueError('All nine fresh formal controls must qualify; development or successful subsets cannot replace them')


def with_exact_configuration_constraints(request, points):
    """Expose the prior ratio-dependent ro limit without a conflicting R=1 default."""
    result = json.loads(json.dumps(request)); contract = result['task_packet']['contract']
    variable = 'branch2_output_resistance_ohm'
    contract['constraints'] = [s for s in contract['constraints'] if s['name'] != variable]
    contract['configuration_constraints'] = [{'id': point['configuration_id'],
        'specifications': [s for s in point['contract']['specifications'] if s['name'] == variable]} for point in points]
    return result


def prepare(plan_path, output):
    plan_path = Path(plan_path).resolve(); plan, registry, initial = load(plan_path)
    actual = Path(plan['output_root']); terminal = read(actual / 'completion.json')
    validate_completion(terminal, plan['fixed_order'])
    baselines = read(actual / 'baseline_results.json')
    if set(baselines) != set(plan['fixed_order']): raise ValueError('The full fixed nine baseline evidence is required')
    summaries, audits = [], []
    caller = (Path(plan['source_pack']) / 'generator.py').read_bytes()
    for point in registry['configurations']:
        result = baselines[point['configuration_id']]
        checked = check_result(result, point, registry, initial, plan)
        if (Path(result['run_directory']) / 'source/generator.py').read_bytes() != caller:
            raise ValueError('Caller documentation differs from actual fresh baseline execution')
        summaries.append({'configuration_id': point['configuration_id'], 'S0': checked['S0'], 'S1': checked['S1'],
            'S2': checked['S2'], 'objective': checked['objective'], 'failure_class': checked['failure_class']})
        audits.append({'configuration_id': point['configuration_id'], 'run_directory': result['run_directory'],
            'phase': 'formal_train', 'point_evaluation_complete': checked['point_evaluation_complete'],
            'S2': checked['S2'], 'raw_perfinger_terminal_graph_clean': checked['device_intent_audit']['is_clean'],
            'full_RC_device_graph_clean': checked['full_RC_device_graph_audit']['is_clean']})
    ordinary = packet(initial, registry['configurations'], summaries)
    if ordinary != read(actual / 'actual_formal_ordinary_request.json'):
        raise ValueError('Fresh raw controls do not reproduce the original full-source context')
    ordinary = add_caller(ordinary, caller.decode('utf-8'))
    ordinary = with_exact_configuration_constraints(ordinary, registry['configurations'])
    flight, teacher = token_preflight(ordinary)
    mapping = mapping_proof(ordinary, teacher); student = mapping.pop('ordinary_request')
    if student['task_packet']['visible_sources'] != initial['base_source']:
        raise ValueError('The ordinary ACTION student must receive the same full editable source')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    (output / 'readonly_generator.py').write_bytes(caller)
    values = {'ordinary_request': ordinary, 'teacher_request': teacher, 'student_request': student,
        'teacher_to_ordinary_mapping': mapping, 'initial_state': initial, 'baseline_results': baselines,
        'effective_registry': registry, 'source_assignment_DRAFT': read(plan_path.parent / 'source_assignment_DRAFT.json'),
        'actual_baseline_audit': {'status': 'ALL_NINE_FRESH_CURRENT_GATE_AND_FULL_RC_DEVICE_GRAPH_QUALIFIED',
            'records': audits, 'new_model_or_physical_calls_for_audit': 0},
        'actual_feedback_token_preflight': flight}
    for name, value in values.items(): save(output / (name + '.json'), value)
    objective = registry['configurations'][0]['contract']['objective']
    labels = {'status': 'DRAFT_NOT_FOR_DATA_ADMISSION', 'objectives': {objective['id']: {
        'metric': objective['metric'], 'unit': objective['unit'], 'direction': objective['direction'],
        'quality_absolute_tolerance': 1e-8, 'quality_relative_tolerance': 1e-6,
        'quality_minimum_relative_effect': .01}},
        'reason': 'Feasible-first actual area reduction;1% effect threshold follows the existing train area objective. No numerical/performance specification is relaxed.'}
    save(output / 'label_rule_DRAFT.json', labels)
    manifest = {'status': 'DRAFT_RATIO_TRAIN_TASK_AFTER_FRESH9_NOT_A_COLLECTION_FREEZE',
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'collection_id': 'ratio_source_literal_span8_v1',
        'parent_lineage': plan['lineage_id'], 'baseline_plan': str(plan_path),
        'baseline_results': str(actual / 'baseline_results.json'),
        'natural_initial_state_id': initial['initial_state_id'], 'complete_editable_modules': [EDITABLE],
        'fixed_configuration_order': plan['fixed_order'], 'initial_contexts': 1, 'initial_source_ASTs': 1,
        'new_global_lineages_activated': 0, 'global_registry_modified': False,
        'source_ancestry': initial['ancestry'], 'nine_configurations_are_nine_independent_sources': False,
        'readonly_caller_equal_in_teacher_and_ordinary': True,
        'ordinary_interface': {'interface_version': 'ordinary_policy_action_context_v2',
            'max_new_tokens': 1024, 'max_context_tokens': 16384,
            'canonical_action': 'propose_patch; full ordinary unified source diff; no patch repair'},
        'producer_DRAFT': {'backend': 'isolated_gpt_cli', 'literal_span_output_max_tokens': 3072,
            'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'seed_control_available': False,
            'max_context_tokens': 16384, 'trials': list(range(1, 9)), 'proposal_workers': 2,
            'timeout_seconds': 240, 'native_tools': [], 'dispatch_allowed': False},
        'proposal_to_data_path': ['Validate literal old/new spans against exact complete source',
            'Compile unchanged spans into ordinary unified diff with existing train_span_proposer',
            'Canonical propose_patch ACTION_JSON must fit the same1024/16k ordinary student interface before physics',
            'Generate changed GDS in CandidateExecutor; evaluate original nine points using the independent frozen trusted capsule',
            'TrustedPhysicalStore verifies actual source/N/PDK/corner/raw evidence; only a separately frozen label rule may create training rows'],
        'maximum_future_candidate_full_points_DRAFT': 72, 'candidate_physics_started': False,
        'prospective_visible_input_revision': 'Exact immutable caller plus explicit original per-configuration branch2 ro limits replace the preview R=1 default. No N, specification, domain, bench or baseline source changes.',
        'activation_blockers': ['Root accepts prospective train-only source assignment with every prior split preserved',
            'Independent producer/consumer and label-rule freeze; old span16/NF bundles and frozen LIVE bytes stay unchanged',
            'Exact new broker identity and shared-global2 maintenance proof before any future model call'],
        'new_model_calls': 0, 'new_physical_calls': 0, 'training_examples': 0}
    save(output / 'collection_DRAFT.json', manifest)
    return {'status': manifest['status'], 'collection_DRAFT': str(output / 'collection_DRAFT.json'),
        'fresh_controls_revalidated': 9, 'token_counts': flight['token_counts'],
        'new_model_calls': 0, 'new_physical_calls': 0, 'global_registry_modified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(prepare(args.plan, args.output), indent=2), flush=True)
