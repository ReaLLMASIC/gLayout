"""One finite worker:18 fresh formal_train NF baselines, no model or retries."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path.cwd().resolve(); sys.path.insert(0, str(ROOT))
from scripts.prepare_nf_span_baselines import read, save, packet, preflight
from scripts.train_pair_nf_physical_qualification import resource_gate
from scripts.audit_train_pair_nf_rc import contracted_devices
from src.candidate_executor import CandidateExecutor
from src.device_intent import compare_device_intent
from src.training import TrustedPhysicalStore


def now(): return datetime.now(timezone.utc).isoformat()


def load(path):
    path = Path(path).resolve(); plan = read(path); folder = path.parent
    if (plan['status'] != 'FROZEN_NF_FRESH18_BASELINE_ONLY' or plan['workers'] != 1 or plan['maximum_new_full_points'] != 18
            or plan['dispatch_horizon_seconds'] != 14400 or plan['phase'] != 'formal_train'
            or plan['new_model_calls'] != 0 or plan['automatic_retry'] is not False):
        raise ValueError('Only the exact finite one-worker formal18 baseline plan is allowed')
    for name, digest in read(folder/'freeze_identity.json').items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest() != digest: raise ValueError('Baseline freeze changed: '+name)
    for name in plan['CODE']:
        if (ROOT/name).read_bytes() != (folder/'code'/name).read_bytes(): raise ValueError('Baseline implementation changed: '+name)
    collections = []
    for item in plan['collections']:
        directory = Path(item['folder']); collection = read(directory/'collection.json'); registry = read(directory/'registry.json')
        state = read(directory/'initial_state.json')
        if [p['configuration_id'] for p in registry['configurations']] != item['configuration_ids'] or len(item['configuration_ids']) != 9:
            raise ValueError('Do not alter the full declared NF grid')
        collections.append({'collection': collection, 'registry': registry, 'initial_state': state})
    return plan, collections


def orphaned(state):
    for cell in state['cells']:
        if cell['status'] == 'DISPATCH_RESERVED':
            cell['status'] = 'UNRESOLVED_RESERVED_NO_RETRY'; state['status'] = 'PAUSED_UNKNOWN_NO_RETRY'
    return state


def check_result(result, point, collection, registry, initial):
    run = Path(result['run_directory']); current = read(run/'manifest.json')
    if current['phase'] != 'formal_train' or current['context'].get('evidence_roles') != ['trusted_evaluator_control']:
        raise ValueError('A development run cannot become a new formal baseline/control')
    for stage in ('candidate', 'trusted'):
        argv = current[stage]['argv']
        if (collection['container_image'] not in argv or argv[argv.index('--cpus')+1] != '2'
                or argv[argv.index('--memory')+1] != '8g'):
            raise ValueError('Actual physical image/resources differ')
    point['gold_control'] = {'run_directory': str(run)}
    row = {'candidate_id': initial['initial_state_id']+'__baseline', 'initial_state_id': initial['initial_state_id'],
        'parent_lineage': initial['parent_lineage'], 'pdk_revision': collection['pdk_revision'],
        'visible_contract': {'task_id': initial['task_id'], 'editable_paths': list(initial['base_source'])}}
    checked = TrustedPhysicalStore(ROOT, registry)._read_run(str((run/'manifest.json').relative_to(ROOT)), row,
        point['configuration_id'], initial['base_source'], row['candidate_id'])
    validation = read(run/'evidence/validation.json'); pex = validation['artifacts']['pex']
    if pex['ports'] != point['parameters']['circuit']['ports']: raise ValueError('RC port ordering differs from immutable bench')
    view = contracted_devices((run/'evidence'/pex['netlist']).read_text(), pex['top_cell'], pex['ports'])
    graph = compare_device_intent(view, (run/'trusted/references'/(point['configuration_id']+'.spice')).read_text())
    if not graph['is_clean']: raise ValueError('Unsimplified RC device graph mismatch; do not use as training evidence')
    if not checked.get('point_evaluation_complete') or not checked['S2']: raise ValueError('Fresh baseline did not qualify; stop without inventing labels')
    return {**checked, 'full_RC_device_graph_audit': graph}


def materialize(data, output, tokenizer):
    collection, registry, initial = data['collection'], data['registry'], data['initial_state']
    rows = read(output/'baseline_results.json'); store = TrustedPhysicalStore(ROOT, registry); summaries = []
    for point in registry['configurations']:
        result = rows[point['configuration_id']]; point['gold_control'] = {'run_directory': result['run_directory']}
    for point in registry['configurations']:
        result = rows[point['configuration_id']]
        checked = check_result(result, point, collection, registry, initial)
        summaries.append({'configuration_id': point['configuration_id'], 'S0': checked['S0'], 'S1': checked['S1'],
            'S2': checked['S2'], 'objective': checked['objective'], 'failure_class': checked.get('failure_class'), 'reason': checked.get('reason')})
    ordinary, teacher, mapping = packet(collection, initial, registry['configurations'], summaries)
    flight = preflight(tokenizer, ordinary, teacher)
    save(output/'effective_registry.json', registry); save(output/'ordinary_request.json', ordinary)
    save(output/'teacher_request.json', teacher); save(output/'student_request.json', mapping.pop('ordinary_request'))
    save(output/'teacher_to_student_mapping_proof.json', mapping); save(output/'actual_formal_token_preflight.json', flight)
    return {'status': 'FRESH_FORMAL_NINE_CURRENT_GATE_AND_RC_GRAPH_QUALIFIED_TEACHER_STILL_DRAFT',
        'points': 9, 'token_counts': flight['token_counts'], 'new_model_calls': 0}


def run(path, execute=None, gate=None):
    path = Path(path).resolve(); plan, collections = load(path); output = Path(plan['output_root'])
    output.mkdir(parents=True, exist_ok=True)
    with (output/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        expected = [(d['collection']['circuit_id'], p['configuration_id']) for d in collections for p in d['registry']['configurations']]
        state = read(output/'state.json') if (output/'state.json').exists() else {
            'status': 'RUNNING_FORMAL_FRESH18', 'pid': os.getpid(), 'started_at_utc': now(),
            'deadline_utc': (datetime.now(timezone.utc)+timedelta(hours=4)).isoformat(),
            'cells': [{'circuit_id': cid, 'configuration_id': identifier, 'status': 'NOT_RUN'} for cid, identifier in expected],
            'maximum_full_points': 18, 'new_model_calls': 0, 'training_examples': 0, 'automatic_retry': False}
        if [(c['circuit_id'],c['configuration_id']) for c in state['cells']] != expected: raise ValueError('Resume must retain all18 original reservations')
        orphaned(state); save(output/'state.json', state)
        if state['status'] != 'RUNNING_FORMAL_FRESH18': return state
        deadline = time.monotonic()+max(0,(datetime.fromisoformat(state['deadline_utc'])-datetime.now(timezone.utc)).total_seconds())
        by_cid = {d['collection']['circuit_id']: d for d in collections}
        for cell in state['cells']:
            if cell['status'] != 'NOT_RUN': continue
            load(path)  # Exact current source and frozen blueprint before each new reservation.
            sample = (gate or resource_gate)(output, deadline)
            if sample is None: state['status'] = 'WINDOW_ENDED_NOT_RUN_RETAINED'; break
            data = by_cid[cell['circuit_id']]; collection, registry, initial = data['collection'], data['registry'], data['initial_state']
            point, = [p for p in registry['configurations'] if p['configuration_id'] == cell['configuration_id']]
            point_output = output/cell['circuit_id']/'points'/cell['configuration_id']
            if point_output.exists(): state.update(status='PAUSED_UNKNOWN_NO_RETRY', error='Existing point directory without a resolved reservation'); break
            point_output.mkdir(parents=True)
            cell.update(status='DISPATCH_RESERVED', reserved_at_utc=now(), resources=sample, point_output=str(point_output))
            save(point_output/'reservation.json', cell); save(output/'state.json', state)
            began = time.monotonic(); result = None
            try:
                executor = CandidateExecutor(ROOT/'runtime/GLdev', point_output/'physical', collection['magic_runtime'], image=collection['container_image'])
                call = execute or executor.execute
                result = call(source_dir=collection['source_pack'], source_paths=collection['source_files'], entrypoint='generator.py',
                    representation='G2', configuration=point['parameters'], trusted_dir=collection['trusted_bundle'],
                    trusted_paths=list(point['trusted_evaluator_files']), fidelity='pex_spice', phase='formal_train',
                    context={'candidate_id': initial['initial_state_id']+'__baseline', 'initial_state_id': initial['initial_state_id'],
                        'parent_lineage': initial['parent_lineage'], 'split': 'train', 'source_role': 'formal_train',
                        'pdk_revision': collection['pdk_revision'], 'configuration_id': point['configuration_id'],
                        'reference_id': point['reference_id'], 'evidence_roles': ['trusted_evaluator_control']},
                    generation_timeout_seconds=240, evaluator_timeout_seconds=720, execution_deadline_utc=state['deadline_utc'])
                save(point_output/'result.json', result)
                checked = check_result(result, point, collection, registry, initial)
                cell.update(status='COMPLETE_QUALIFIED_FORMAL_BASELINE', result=result, checked=checked)
                baseline_path = output/cell['circuit_id']/'baseline_results.json'
                baselines = read(baseline_path) if baseline_path.exists() else {}; baselines[point['configuration_id']] = result; save(baseline_path, baselines)
                save(output/cell['circuit_id']/'effective_registry.json', registry)
            except Exception as exc:
                cell.update(status='UNKNOWN_NO_RETRY', error=type(exc).__name__+': '+str(exc)); state['status'] = 'PAUSED_UNKNOWN_NO_RETRY'
            finally:
                stages = {}; cost_errors = []
                if result is not None:
                    try:
                        manifest = read(Path(result['run_directory'])/'manifest.json')
                        for name in ('candidate','trusted'):
                            if name not in manifest: continue
                            usage = Path(result['run_directory'])/(name+'_stage/resource_usage.json')
                            raw = read(usage) if usage.exists() else None
                            stages[name] = {'wall_seconds':manifest[name]['wall_seconds'],
                                'waited_child_CPU_seconds':raw['child_user_cpu_seconds']+raw['child_system_cpu_seconds'] if raw else None,
                                'raw_telemetry':str(usage) if raw else None}
                    except (ValueError,OSError,KeyError) as exc: cost_errors.append(str(exc))
                save(point_output/'actual_cost.json', {'wall_seconds':time.monotonic()-began, 'stages':stages,
                    'new_model_calls':0, 'physical_point_calls':1, 'cost_metadata_errors':cost_errors,
                    'missing_CPU_values_are_zero':False})
            cell['returned_at_utc'] = now(); save(output/'state.json', state)
            print(json.dumps({'configuration_id':cell['configuration_id'],'status':cell['status']}), flush=True)
            if state['status'] != 'RUNNING_FORMAL_FRESH18': break
        if all(c['status'] == 'COMPLETE_QUALIFIED_FORMAL_BASELINE' for c in state['cells']):
            from transformers import AutoTokenizer
            cache = read(ROOT/'configs/training/backbone_cache.json')
            tokenizer = AutoTokenizer.from_pretrained(cache['snapshot'], local_files_only=True, trust_remote_code=False)
            try:
                state['materialized_collections'] = {d['collection']['circuit_id']:materialize(d, output/d['collection']['circuit_id'], tokenizer) for d in collections}
                state['status'] = 'COMPLETED_FORMAL18_ALL_QUALIFIED_NO_MODELS'
            except Exception as exc: state.update(status='PAUSED_FINAL_MATERIALIZATION_UNKNOWN', error=type(exc).__name__+': '+str(exc))
        state.update(ended_at_utc=now(), qualified_points=sum(c['status']=='COMPLETE_QUALIFIED_FORMAL_BASELINE' for c in state['cells']),
            not_run=[c['configuration_id'] for c in state['cells'] if c['status']=='NOT_RUN'])
        save(output/'state.json',state); save(output/'completion.json',state); return state


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--plan',type=Path,required=True)
    g=p.add_mutually_exclusive_group(required=True);g.add_argument('--validate-only',action='store_true');g.add_argument('--execute',action='store_true')
    a=p.parse_args();print(json.dumps({'status':'VALIDATED_FORMAL18_BASELINE_PLAN_NO_CALLS','maximum_new_points':18,'model_calls':0} if a.validate_only and load(a.plan) else run(a.plan),indent=2),flush=True)
