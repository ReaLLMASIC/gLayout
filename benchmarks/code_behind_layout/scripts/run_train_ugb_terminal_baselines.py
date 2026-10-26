"""One prospective C08 TRAIN pilot:3 anchor controls then8 baseline points.

Only a separately committed readonly11-point freeze is executable. There is no
teacher, GPU, hidden evaluation, automatic retry, or existing-pool mutation.
"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.prepare_train_ugb_terminal_pilot import (
    SPEC, TASK_ID, OBJECTIVE, GOAL, CODE, read, save, baseline_cells,
)
from scripts.prepare_natural_terminal_baselines import packet, preflight
from scripts.run_natural_terminal_baselines import resource_gate, check_result
from src.candidate_executor import CandidateExecutor
from src.train_span_proposer import teacher_request, mapping_proof

FROZEN = 'FROZEN_C08_NATURAL_TERMINAL_UGB_11_BASELINES_ONLY'


def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rebase(value, old, new):
    if isinstance(value, dict): return {k: rebase(v, old, new) for k, v in value.items()}
    if isinstance(value, list): return [rebase(v, old, new) for v in value]
    if isinstance(value, str) and (value == str(old) or value.startswith(str(old)+'/')):
        return str(new)+value[len(str(old)):]
    return value


def verify(path):
    path = Path(path).resolve(); folder = path.parent; plan = read(path)
    if (plan['status'] != FROZEN or plan['maximum_new_full_points'] != 11 or plan['workers'] != 1
            or plan['initial_state_id'] != SPEC['initial_state_id'] or plan['phase'] != 'formal_train'
            or plan['automatic_retry'] is not False or plan['new_model_calls'] != 0
            or plan['dispatch_horizon_seconds'] != 14400 or plan['CODE'] != CODE):
        raise ValueError('Only the exact fixed one-worker11-control freeze is executable')
    for name, digest in read(folder/'freeze_identity.json').items():
        file = folder/name
        if file.stat().st_mode & 0o222 or sha(file) != digest:
            raise ValueError('C08 readonly freeze changed: '+name)
    for name in CODE:
        if (ROOT/name).read_bytes() != (folder/'code'/name).read_bytes():
            raise ValueError('Committed C08 pilot implementation changed: '+name)
    collection = read(plan['collection']); registry = read(collection['registry_path'])
    initial = read(collection['initial_state_path'])
    if (plan['cells'] != baseline_cells(registry['configurations'])
            or initial['initial_state_id'] != SPEC['initial_state_id'] or initial['task_id'] != TASK_ID
            or any(p['contract']['objective'] != OBJECTIVE or p['contract']['task_id'] != TASK_ID
                   for p in registry['configurations'])):
        raise ValueError('The frozen source/domain/task/objective binding differs')
    return plan, collection, registry, initial


def freeze(prepared, output, index):
    prepared = Path(prepared).resolve(); output = Path(output).resolve(); index = read(index)
    output.relative_to(ROOT/'runtime/protocol_freezes')
    plan = read(prepared/'baseline_plan_DRAFT.json')
    if plan['status'] != 'DRAFT_CPU_ONLY_NO_DISPATCH' or output.exists():
        raise ValueError('Require a new independent prospective freeze; preserve old preparations')
    for name in CODE:
        if sha(ROOT/name) != index['files_sha256'][name] or (ROOT/name).read_bytes() != (prepared/'code'/name).read_bytes():
            raise ValueError('Prepared implementation differs from the committed source index')
    shutil.copytree(prepared, output)
    for file in sorted(output.rglob('*.json')):
        original = read(file); updated = rebase(original, prepared, output)
        if updated != original: save(file, updated)
    plan = read(output/'baseline_plan_DRAFT.json')
    plan.update(status=FROZEN, source_revision=index['revision'], frozen_at_utc=now(),
        output_root=str(ROOT/'runs/train_collection/c08_natural_terminal_ugb_baselines_v1'))
    save(output/'baseline_plan_DRAFT.json', plan); save(output/'committed_source_index.json', index)
    identities = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
    save(output/'freeze_identity.json', identities)
    for p in output.rglob('*'): p.chmod(0o555 if p.is_dir() else 0o444)
    output.chmod(0o555); verify(output/'baseline_plan_DRAFT.json')
    return {'status': FROZEN, 'plan': str(output/'baseline_plan_DRAFT.json'),
        'files': len(identities), 'new_model_calls': 0, 'new_physical_calls': 0}


def exact_geometry(first, second):
    """Original database precision, absolute coordinates and all label attributes."""
    import gdstk
    def load(path):
        lib = gdstk.read_gds(str(path)); top, = lib.top_level(); top.flatten(); layers = {}
        for polygon in top.get_polygons(include_paths=True):
            layers.setdefault((polygon.layer, polygon.datatype), []).append(polygon)
        labels = sorted((x.text, tuple(x.origin), x.layer, x.texttype, x.rotation, x.magnification, x.x_reflection) for x in top.labels)
        return lib, layers, labels
    a, left, la = load(first); b, right, lb = load(second)
    if (a.unit, a.precision) != (b.unit, b.precision): raise ValueError('GDS units/precision changed')
    changed = [list(layer) for layer in set(left)|set(right) if gdstk.boolean(
        left.get(layer, []), right.get(layer, []), 'xor', precision=a.precision/a.unit)]
    return {'equal': not changed and la == lb, 'changed_layers': changed,
        'all_label_attributes_equal': la == lb, 'translation_removed': False}


def control_spread(values):
    if len(values) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('Three actual positive finite worst-corner UGB values are required')
    relative = (max(values)-min(values))/min(values)
    return {'worst_corner_ugb_Hz': values, 'relative_range': relative,
        'fixed_minimum_label_effect': .01, 'passes': relative < .01}


def point_cost(result):
    stages = {}; errors = []
    if result is not None:
        try:
            run = Path(result['run_directory']); manifest = read(run/'manifest.json')
            for name in ('candidate', 'trusted'):
                if name not in manifest: continue
                usage = run/(name+'_stage/resource_usage.json'); raw = read(usage) if usage.exists() else None
                stages[name] = {'wall_seconds': manifest[name]['wall_seconds'],
                    'waited_child_CPU_seconds': raw['child_user_cpu_seconds']+raw['child_system_cpu_seconds'] if raw else None,
                    'raw_telemetry': str(usage) if raw else None}
        except (ValueError, KeyError, OSError) as error: errors.append(str(error))
    return {'stages': stages, 'cost_metadata_errors': errors, 'missing_CPU_values_are_zero': False}


def run(path, execute=None, gate=None, geometry=exact_geometry):
    plan, collection, registry, initial = verify(path); output = Path(plan['output_root'])
    # A previous directory/reservation is preserved, including a killed host.
    # This small pilot has no process-restart inference or retry entry point.
    output.mkdir(parents=True, exist_ok=False)
    with (output/'coordinator.lock').open('x') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        began, cpu = time.monotonic(), time.process_time(); deadline = began+14400
        state = {'status': 'RUNNING_C08_UGB_BASELINE11', 'started_at_utc': now(),
            'deadline_utc': (datetime.now(timezone.utc)+timedelta(hours=4)).isoformat(),
            'cells': [{**c, 'status': 'NOT_RUN'} for c in plan['cells']],
            'physical_call_reservations': 0, 'new_model_calls': 0, 'automatic_retry': False}
        save(output/'state.json', state); results = {}; controls = []
        for cell in state['cells']:
            verify(path)
            if (gate or resource_gate)(output, deadline) is None:
                state['status'] = 'RESOURCE_WINDOW_ENDED_NOT_RUN_RETAINED'; break
            point = next(p for p in registry['configurations'] if p['configuration_id'] == cell['configuration_id'])
            folder = output/'points'/cell['cell_id']; folder.mkdir(parents=True)
            cell.update(status='DISPATCH_RESERVED', reserved_at_utc=now())
            state['physical_call_reservations'] += 1; save(folder/'reservation.json', cell); save(output/'state.json', state)
            result = None; point_began = time.monotonic()
            try:
                call = execute or CandidateExecutor(ROOT/'runtime/GLdev', folder/'physical',
                    collection['magic_runtime'], image=collection['container_image']).execute
                result = call(source_dir=collection['source_pack'], source_paths=collection['source_files'],
                    entrypoint='generator.py', representation='G2', configuration=point['parameters'],
                    trusted_dir=collection['trusted_bundle'], trusted_paths=list(point['trusted_evaluator_files']),
                    fidelity='pex_spice', phase='formal_train',
                    context={'candidate_id': initial['initial_state_id']+'__baseline',
                        'initial_state_id': initial['initial_state_id'], 'parent_lineage': initial['parent_lineage'],
                        'split': 'train', 'source_role': 'formal_train', 'pdk_revision': collection['pdk_revision'],
                        'configuration_id': point['configuration_id'], 'reference_id': point['reference_id'],
                        'evidence_roles': ['trusted_evaluator_control']}, generation_timeout_seconds=240,
                    evaluator_timeout_seconds=720, execution_deadline_utc=state['deadline_utc'])
                save(folder/'result.json', result)
                checked = check_result(result, point, collection, registry, initial)
                cell.update(status='COMPLETE_QUALIFIED', result=result, checked=checked)
                if cell['cell_id'] == 'anchor_repeat_1' or cell['role'] == 'new_baseline_development':
                    results[point['configuration_id']] = result
                if cell['cell_id'].startswith('anchor_repeat_'):
                    controls.append({'result': result, 'objective': checked['objective']})
                    if len(controls) == 3:
                        spread = control_spread([r['objective'] for r in controls])
                        first = Path(controls[0]['result']['run_directory'])/'accepted/candidate.gds'
                        comparisons = [geometry(first, Path(r['result']['run_directory'])/'accepted/candidate.gds') for r in controls[1:]]
                        save(output/'anchor_extraction_controls.json', {**spread, 'exact_GDS_comparisons': comparisons})
                        if not spread['passes'] or any(not r['equal'] for r in comparisons):
                            state['status'] = 'CONTROL_VARIATION_EXCEEDS_PREDECLARED_BOUND_NO_TEACHER'; break
            except Exception as error:
                cell.update(status='UNKNOWN_OR_BASELINE_REJECTED_NO_RETRY', error=type(error).__name__+': '+str(error))
                state['status'] = 'PAUSED_UNKNOWN_OR_BASELINE_REJECTION_NO_TEACHER'
            finally:
                save(folder/'actual_cost.json', {**point_cost(result), 'wall_seconds': time.monotonic()-point_began,
                    'physical_point_calls': 1, 'new_model_calls': 0})
                cell['returned_at_utc'] = now(); save(output/'state.json', state)
            if state['status'] != 'RUNNING_C08_UGB_BASELINE11': break
        if all(c['status'] == 'COMPLETE_QUALIFIED' for c in state['cells']):
            try:
                from transformers import AutoTokenizer
                for point in registry['configurations']:
                    point['gold_control'] = {'run_directory': results[point['configuration_id']]['run_directory']}
                summaries = [{k: c['checked'].get(k) for k in ('configuration_id', 'S0', 'S1', 'S2', 'objective')}
                    for c in state['cells'] if c['cell_id'] == 'anchor_repeat_1' or c['role'] == 'new_baseline_development']
                ordinary, _, _ = packet(collection, initial, registry['configurations'], summaries)
                ordinary['task_packet']['goal'] = GOAL; teacher = teacher_request(ordinary)
                tokenizer = AutoTokenizer.from_pretrained(read(ROOT/'configs/training/backbone_cache.json')['snapshot'],
                    local_files_only=True, trust_remote_code=False)
                flight = preflight(tokenizer, ordinary, teacher)
                proof = mapping_proof(ordinary, teacher); student = proof.pop('ordinary_request')
                for name, value in [('effective_registry', registry), ('baseline_results', results),
                        ('ordinary_request', ordinary), ('teacher_request', teacher), ('student_request', student),
                        ('teacher_to_student_mapping', proof), ('actual_token_preflight', flight)]:
                    save(output/(name+'.json'), value)
                state['status'] = 'COMPLETED_FRESH11_QUALIFIED_TEACHER_STILL_UNFROZEN'
            except Exception as error:
                state.update(status='PAUSED_FINAL_MATERIALIZATION_UNKNOWN_NO_TEACHER', error=type(error).__name__+': '+str(error))
        state.update(ended_at_utc=now(), parent_CPU_seconds=time.process_time()-cpu,
            wall_seconds=time.monotonic()-began, not_run=[c['cell_id'] for c in state['cells'] if c['status']=='NOT_RUN'])
        save(output/'state.json', state); return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['freeze', 'check', 'run'], required=True)
    parser.add_argument('--prepared', type=Path); parser.add_argument('--source-index', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    if args.mode == 'freeze': result = freeze(args.prepared, args.output, args.source_index)
    elif args.mode == 'check':
        plan, *_ = verify(args.plan); result = {'status': 'CHECKED_NO_CALLS', 'full_points': len(plan['cells'])}
    else:
        state = run(args.plan); result = {k: v for k, v in state.items() if k != 'cells'}
    print(json.dumps(result, indent=2))
