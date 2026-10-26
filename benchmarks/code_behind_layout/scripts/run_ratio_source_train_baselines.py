"""One finite worker: nine fresh formal_train ratio baselines, zero models."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.prepare_ratio_source_train_baselines import read, save, packet, token_preflight, EDITABLE
from scripts.ratio_source_physical_qualification import resource_gate
from scripts.ratio_source_physical_probe import contracted_rc_devices
from src.candidate_executor import CandidateExecutor
from src.device_intent import compare_device_intent
from src.training import TrustedPhysicalStore


def now(): return datetime.now(timezone.utc).isoformat()


def load(path):
    path = Path(path).resolve(); plan = read(path); folder = path.parent
    if (plan['status'] != 'FROZEN_RATIO_FRESH9_BASELINE_ONLY' or plan['phase'] != 'formal_train'
            or plan['workers'] != 1 or plan['maximum_new_full_points'] != 9
            or plan['dispatch_horizon_seconds'] != 14400 or plan['new_model_calls'] != 0
            or plan['automatic_retry'] is not False or not plan['unknown_stops_future_dispatch']):
        raise ValueError('Only the fixed one-worker fresh9 baseline plan is executable')
    for name, digest in read(folder / 'freeze_identity.json').items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen ratio baseline package changed: ' + name)
    for name in plan['CODE']:
        if (ROOT / name).read_bytes() != (folder / 'code' / name).read_bytes():
            raise ValueError('Baseline implementation changed: ' + name)
    registry = read(folder / 'baseline_registry.json'); initial = read(folder / 'initial_state.json')
    if [p['configuration_id'] for p in registry['configurations']] != plan['fixed_order']:
        raise ValueError('Do not select a subset or change point order')
    return plan, registry, initial


def check_result(result, point, registry, initial, plan):
    run = Path(result['run_directory']); manifest = read(run / 'manifest.json')
    if manifest['phase'] != 'formal_train' or manifest['context'].get('evidence_roles') != ['trusted_evaluator_control']:
        raise ValueError('A development control cannot become a fresh formal_train baseline')
    for stage in ('candidate', 'trusted'):
        argv = manifest[stage]['argv']
        if (plan['container_image'] not in argv or argv[argv.index('--cpus') + 1] != '2'
                or argv[argv.index('--memory') + 1] != '8g'):
            raise ValueError('Actual physical resources or image differ from frozen plan')
    point['gold_control'] = {'run_directory': str(run)}
    candidate = {'candidate_id': initial['initial_state_id'] + '__baseline',
        'initial_state_id': initial['initial_state_id'], 'parent_lineage': plan['lineage_id'],
        'pdk_revision': plan['PDK_revision'],
        'visible_contract': {'task_id': initial['task_id'], 'editable_paths': [EDITABLE]}}
    checked = TrustedPhysicalStore(ROOT, registry)._read_run(str((run / 'manifest.json').relative_to(ROOT)),
        candidate, point['configuration_id'], initial['base_source'], candidate['candidate_id'])
    validation = read(run / 'evidence/validation.json'); pex = validation['artifacts']['pex']
    if sorted(p.upper() for p in pex['ports']) != sorted(p.upper() for p in point['contract']['ports']):
        raise ValueError('Unsimplified RC omits a required original named port')
    view = contracted_rc_devices((run / 'evidence' / pex['netlist']).read_text(), pex['top_cell'], pex['ports'])
    graph = compare_device_intent(view, (run / 'trusted' / point['reference_file']).read_text())
    if not graph['is_clean'] or not checked['point_evaluation_complete'] or not checked['S2']:
        raise ValueError('Fresh baseline lacks complete physical/corner intent or fails original specs; stop without labels')
    return {**checked, 'full_RC_device_graph_audit': graph}


def run(path, execute=None, gate=None):
    path = Path(path).resolve(); plan, registry, initial = load(path); output = Path(plan['output_root'])
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = read(output / 'state.json') if (output / 'state.json').exists() else {
            'status': 'RUNNING_FORMAL_RATIO_FRESH9', 'pid': os.getpid(), 'started_at_utc': now(),
            'deadline_utc': (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            'cells': [{'configuration_id': identifier, 'status': 'NOT_RUN'} for identifier in plan['fixed_order']],
            'maximum_full_points': 9, 'new_model_calls': 0, 'training_examples': 0,
            'global_registry_modified': False, 'automatic_retry': False}
        if [c['configuration_id'] for c in state['cells']] != plan['fixed_order']:
            raise ValueError('Existing state does not preserve all nine reservations')
        for cell in state['cells']:
            if cell['status'] == 'DISPATCH_RESERVED':
                cell['status'] = 'UNRESOLVED_RESERVED_NO_RETRY'; state['status'] = 'PAUSED_UNKNOWN_NO_RETRY'
        save(output / 'state.json', state)
        if state['status'] != 'RUNNING_FORMAL_RATIO_FRESH9': return state
        deadline = time.monotonic() + max(0, (datetime.fromisoformat(state['deadline_utc']) - datetime.now(timezone.utc)).total_seconds())
        for cell, point in zip(state['cells'], registry['configurations']):
            if cell['status'] != 'NOT_RUN': continue
            load(path)
            sample = (gate or resource_gate)(output, deadline)
            if sample is None:
                state['status'] = 'WINDOW_ENDED_NOT_RUN_RETAINED'; break
            point_output = output / 'points' / point['configuration_id']
            if point_output.exists():
                state.update(status='PAUSED_UNKNOWN_NO_RETRY', error='Existing point output without a resolved reservation'); break
            point_output.mkdir(parents=True)
            cell.update(status='DISPATCH_RESERVED', reserved_at_utc=now(), resources=sample, point_output=str(point_output))
            save(point_output / 'reservation.json', cell); save(output / 'state.json', state)
            began = time.monotonic(); result = None
            try:
                executor = CandidateExecutor(ROOT / 'runtime/GLdev', point_output / 'physical', plan['magic_runtime'], image=plan['container_image'])
                result = (execute or executor.execute)(source_dir=plan['source_pack'], source_paths=plan['source_files'],
                    entrypoint='generator.py', representation='G2', configuration=point['parameters'],
                    trusted_dir=plan['trusted_bundle'], trusted_paths=plan['trusted_files'], fidelity='pex_spice', phase='formal_train',
                    context={'candidate_id': initial['initial_state_id'] + '__baseline', 'initial_state_id': initial['initial_state_id'],
                        'parent_lineage': plan['lineage_id'], 'split': 'train', 'source_role': 'formal_train',
                        'pdk_revision': plan['PDK_revision'], 'configuration_id': point['configuration_id'],
                        'reference_id': point['reference_id'], 'evidence_roles': ['trusted_evaluator_control']},
                    generation_timeout_seconds=plan['generation_timeout_seconds'],
                    evaluator_timeout_seconds=plan['evaluator_timeout_seconds'], execution_deadline_utc=state['deadline_utc'])
                save(point_output / 'result.json', result)
                checked = check_result(result, point, registry, initial, plan)
                cell.update(status='COMPLETE_QUALIFIED_FORMAL_BASELINE', result=result, checked=checked)
                baselines = read(output / 'baseline_results.json') if (output / 'baseline_results.json').exists() else {}
                baselines[point['configuration_id']] = result; save(output / 'baseline_results.json', baselines)
                save(output / 'effective_registry.json', registry)
            except Exception as error:
                cell.update(status='UNKNOWN_OR_UNQUALIFIED_NO_RETRY', error=type(error).__name__ + ': ' + str(error))
                state['status'] = 'PAUSED_UNKNOWN_OR_UNQUALIFIED_NO_RETRY'
            finally:
                stages, errors = {}, []
                if result is not None:
                    try:
                        run_dir = Path(result['run_directory']); manifest = read(run_dir / 'manifest.json')
                        for name in ('candidate', 'trusted'):
                            if name not in manifest: continue
                            telemetry = run_dir / (name + '_stage/resource_usage.json')
                            raw = read(telemetry) if telemetry.exists() else None
                            stages[name] = {'wall_seconds': manifest[name]['wall_seconds'],
                                'waited_child_CPU_seconds': raw['child_user_cpu_seconds'] + raw['child_system_cpu_seconds'] if raw else None,
                                'raw_telemetry': str(telemetry) if raw else None}
                    except (ValueError, OSError, KeyError) as error: errors.append(str(error))
                save(point_output / 'actual_cost.json', {'wall_seconds': time.monotonic() - began, 'stages': stages,
                    'new_model_calls': 0, 'new_physical_points': 1, 'missing_CPU_values_are_zero': False,
                    'cost_metadata_errors': errors})
            cell['returned_at_utc'] = now(); save(output / 'state.json', state)
            print(json.dumps({'configuration_id': point['configuration_id'], 'status': cell['status']}), flush=True)
            if state['status'] != 'RUNNING_FORMAL_RATIO_FRESH9': break
        if all(c['status'] == 'COMPLETE_QUALIFIED_FORMAL_BASELINE' for c in state['cells']):
            try:
                summaries = [{'configuration_id': c['configuration_id'], 'S0': c['checked']['S0'],
                    'S1': c['checked']['S1'], 'S2': c['checked']['S2'], 'objective': c['checked']['objective'],
                    'failure_class': c['checked']['failure_class']} for c in state['cells']]
                request = packet(initial, registry['configurations'], summaries)
                flight, teacher = token_preflight(request)
                save(output / 'actual_formal_ordinary_request.json', request)
                save(output / 'actual_formal_teacher_preview_DRAFT.json', teacher)
                save(output / 'actual_formal_feedback_token_preflight.json', flight)
                state.update(status='COMPLETED_FORMAL_RATIO_FRESH9_ALL_QUALIFIED_NO_MODELS',
                    actual_formal_feedback_token_counts=flight['token_counts'], future_collection_status='DRAFT')
            except Exception as error:
                state.update(status='PAUSED_FINAL_MATERIALIZATION_UNKNOWN', error=type(error).__name__ + ': ' + str(error))
        state.update(ended_at_utc=now(), qualified_points=sum(c['status'] == 'COMPLETE_QUALIFIED_FORMAL_BASELINE' for c in state['cells']),
            not_run=[c['configuration_id'] for c in state['cells'] if c['status'] == 'NOT_RUN'])
        save(output / 'state.json', state); save(output / 'completion.json', state)
        return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--plan', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument('--validate-only', action='store_true'); mode.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.validate_only:
        load(args.plan); result = {'status': 'VALIDATED_RATIO_FRESH9_BASELINE_ONLY', 'model_calls': 0, 'physical_calls': 0}
    else: result = run(args.plan)
    print(json.dumps(result, indent=2), flush=True)
