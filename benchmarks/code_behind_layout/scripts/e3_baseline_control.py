#!/usr/bin/env python3
"""Bounded real P/I interface control: at most3 full points,0 models/hidden.

This uses a declared legal engineering layout variant, not a policy proposal.
An existing incomplete control is retained for reconciliation, never retried.
"""
import argparse
import copy
import fcntl
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.archive_e3_evidence import archive_point
from scripts.e3_episode import read, save
from scripts.e3_parameter_episode import ParameterGateway, action, canonical, patch_action, start
from scripts.e3_instance_episode import (CACHE, VERSION, WARM_START, InstanceGateway,
    finish_arrival, open_arrival, start_study)
from src.e3_task_prepare import INITIALS

TASK = 'draft_E3_stacked_switch_edit01'
BUDGET = {'wall_seconds': 1200, 'decisions': 6, 'patches': 1,
    'full_evaluations': 2, 'maximum_context_tokens': 12288, 'maximum_output_tokens': 1024}


def no_model_usage(decisions):
    return {'decision_step_attempts': decisions, 'model_cli_invocations': 0, 'public_provider_usage': [],
        'scope': 'Deterministic engineering API control, not a tested policy or model trial'}


def archive_returned(gateway):
    records = []
    for event in gateway.state.value['physical_events']:
        if event['status'] != 'RETURNED':
            raise RuntimeError('An unresolved physical call is preserved; no archive or retry')
        records.append(archive_point(Path(event['point_record']).parent))
    return [{'status': row['status'], 'archive_bytes': row.get('archive_bytes'),
        'raw_regular_file_bytes': row.get('raw_regular_file_bytes'), 'new_physical_calls': 0} for row in records]


def parameter_control(manifest, output):
    initialized = start({'manifest': str(manifest), 'task_id': TASK, 'strategy': 'random',
        'selection_seed': 41, 'trial_id': 'development_interface_control', 'formal': False})
    directory = initialized['episode_directory'];save(output/'P_started.json', {'episode_directory': directory})
    gateway = ParameterGateway(directory);observations = []
    initial = gateway.action(action('request_evaluation', configuration_ids=['anchor'], fidelity='pex_spice',
        summary='Engineering control: actual original anchor before the only parameter edit'))
    observations.append(initial);save(output/'P_observations.json', observations)
    if initial['checked']['execution_integrity'] == 'valid':
        # This fixed authored variant was declared in the development inventory.
        # No search, outcome-dependent endpoint choice or source sizing change.
        proposal = patch_action(gateway.sources()['layout_parameters.json'],
            canonical(INITIALS['stacked_switch'][1]), 'Engineering control: predeclared separation36um, signal-width1um')
        observations.append(gateway.action(proposal));save(output/'P_observations.json', observations)
        observations.append(gateway.action(action('request_evaluation', configuration_ids=['anchor'], fidelity='pex_spice',
            summary='Engineering control: actual rendered parameter revision anchor')))
        save(output/'P_observations.json', observations)
    valid = all(row.get('checked', {}).get('execution_integrity', 'valid') == 'valid' for row in observations)
    search = gateway.seal('SEARCH_FINISHED' if valid else 'INCOMPLETE_UNKNOWN', no_model_usage(gateway.state.value['decisions']))
    return {'episode_directory': directory, 'status': search['status'],
        'new_physical_calls': len(gateway.state.value['physical_events']), 'model_calls': 0,
        'hidden_calls': 0, 'selected_parameters': search['selected_parameters'],
        'initial_checked': observations[0]['checked'],
        'edited_checked': observations[-1].get('checked') if len(observations) == 3 else None,
        'costs_by_stage': search['costs_by_stage'], 'interface_cost': search['interface_cost'],
        'archives': archive_returned(gateway), 'scope': 'Renderer/patch/physical-feedback control, not random-search quality evidence'}


def instance_control(manifest, output):
    initialized = start_study({'manifest': str(manifest), 'task_id': TASK,
        'trial_id': 'development_interface_control', 'formal': False})
    study = initialized['study_directory'];save(output/'I_started.json', {'study_directory': study})
    reports, total_physical = [], 0
    for index in range(2):
        opened = open_arrival(study)
        gateway = InstanceGateway(opened['arrival_directory'])
        if index == 1 and not opened['served_from_exact_cache']:
            raise RuntimeError('Repeated exact instance was not verified from its own cache; no extra physical fallback allowed by this control')
        if opened['served_from_exact_cache']:
            status = 'EXACT_CACHE_SERVED'
        else:
            feedback = gateway.action(action('request_evaluation', configuration_ids=['current'], fidelity='pex_spice',
                summary='Engineering control: actual first independent instance anchor'))
            save(output/'I_first_feedback.json', feedback)
            status = 'SEARCH_FINISHED' if feedback['checked']['execution_integrity'] == 'valid' else 'INCOMPLETE_UNKNOWN'
        gateway.seal(status, no_model_usage(gateway.state.value['decisions']))
        # Do not allow even a deployment fallback to exceed the declared3-point
        # engineering budget; the actual first result must be exact-verifiable.
        revision = gateway.state.value['selected_revision']
        previous = gateway.state.value['results'].get(str(revision))
        if status != 'INCOMPLETE_UNKNOWN' and (previous is None or gateway.cached(previous, revision) is None):
            raise RuntimeError('No exact first-instance deployment evidence; retain control without physical retry')
        report = gateway.deploy();summary = finish_arrival(study)
        total_physical += len(gateway.state.value['physical_events'])
        archives = archive_returned(gateway)
        reports.append({'arrival_ordinal': index, 'status': report['status'], 'S2': report['S2'],
            'complete': report['complete'], 'objective': report['objective'],
            'opened_with_exact_cache': opened['served_from_exact_cache'],
            'physical_calls': len(gateway.state.value['physical_events']), 'archives': archives})
        save(output/'I_progress.json', {'arrivals': reports, 'new_physical_calls': total_physical})
        if not report['complete'] or not report['S2']:
            break
    if len(reports) == 2:
        open_arrival(study)  # Marks the fixed two-arrival stream complete; no point/model call.
    return {'study_directory': study, 'new_physical_calls': total_physical, 'model_calls': 0, 'hidden_calls': 0,
        'arrivals': reports, 'repeat_exact_cache_established': len(reports) == 2 and reports[1]['opened_with_exact_cache']
            and reports[1]['physical_calls'] == 0,
        'cumulative_costs': summary['cumulative_costs'],
        'scope': 'Independent library starts empty; no result from P, C or E4 enters it'}


def run(manifest, output):
    output = Path(output).resolve()
    if output.exists():
        if (output/'summary.json').is_file():
            return read(output/'summary.json')
        raise RuntimeError('An incomplete engineering control already exists; retain and reconcile rather than relaunch')
    original = read(manifest)
    if original.get('status') == 'FROZEN_E3':
        raise ValueError('Use a DRAFT development manifest; this control cannot mutate or impersonate a formal freeze')
    output.mkdir(parents=True, mode=0o700)
    began, cpu = time.monotonic(), time.process_time()
    with (output/'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings = copy.deepcopy(original)
        settings.update(status='DEVELOPMENT_E3_BASELINE_INTERFACE_CONTROL', formal_dispatch=False,
            task_ids=[TASK], budget=BUDGET,
            parameter_baseline={'configuration_selector': 'C', 'strategies': ['random', 'gpt_feedback'],
                'interface': 'prospective_expanded_layout_grid_v1'})
        save(output/'arrival_order.json', ['anchor', 'anchor'])
        settings['instance_baseline'] = {'algorithm': VERSION, 'warm_start': WARM_START, 'cache': CACHE,
            'arrival_order': str(output/'arrival_order.json'), 'deployment_verification_maximum_physical_calls': 1,
            'budget': BUDGET}
        save(output/'manifest.json', settings)
        save(output/'plan.json', {'task_id': TASK, 'maximum_new_physical_calls': 3, 'model_calls': 0,
            'hidden_calls': 0, 'P_revision': INITIALS['stacked_switch'][1], 'I_arrivals': ['anchor', 'anchor'],
            'automatic_retries': False, 'formal_policy_trials': 0})
        results = {'P': parameter_control(output/'manifest.json', output)}
        save(output/'progress.json', results)
        if results['P']['status'] == 'INCOMPLETE_UNKNOWN':
            result = {'status': 'PAUSED_UNKNOWN', **results, 'I': {'status': 'NOT_RUN'}}
        else:
            results['I'] = instance_control(output/'manifest.json', output)
            result = {'status': 'COMPLETE', **results}
        result.update(scope='development_E3_P_I_real_interface_control_not_formal',
            new_physical_calls=sum(row.get('new_physical_calls', 0) for row in results.values()),
            model_calls=0, hidden_calls=0, formal_policy_trials=0,
            controller_wall_seconds=time.monotonic()-began, controller_process_CPU_seconds=time.process_time()-cpu)
        save(output/'summary.json', result)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True);parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.manifest, args.output)
    except Exception as error:
        if args.output.is_dir():
            save(args.output/'error.json', {'status': 'UNRESOLVED_NO_AUTOMATIC_RETRY',
                'error': type(error).__name__+': '+str(error)})
        raise
    print(json.dumps(result), flush=True)
