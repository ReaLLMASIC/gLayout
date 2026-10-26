#!/usr/bin/env python3
"""Freeze and collect the original E3 program's private 24-by-25 baseline.

prepare() copies immutable inputs only. Physical collection is separate and may
start only after the methods freeze. Every declared slot is attempted at most
once; an unknown or interrupted execution is never silently repeated.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.archive_e3_evidence import archive_point, restore_run
from scripts.e3_episode import verify
from scripts.e3_generation_qualify import gate
from scripts.e3_instance_episode import exact_bindings, verify_cached
from scripts.e3_physical_point import inspect, trusted
from scripts.e3_task_prepare import capsule
from src.candidate_executor import CandidateExecutor, IMAGE
from src.domain_runner import source_contents
from src.device_intent import compare_device_intent
from src.e3_regression import summarize

PDK = '0fe599b2afb6708d281543108caf8310912f54af'
VERSION = 'immutable_E3_original_baseline_v1'


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n');temporary.replace(path)


def files(folder):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file())


def validate_task(task):
    points = task['configurations']
    if (len(points) != 25 or len({p['configuration_id'] for p in points}) != 25 or
            {role: sum(p['role'] == role for p in points) for role in ('anchor', 'development', 'hidden')}
                != {'anchor': 1, 'development': 8, 'hidden': 16}):
        raise ValueError('Each baseline task must bind exactly1 anchor,8 development and16 hidden points')
    if any(p['contract']['task_id'] != task['task_id'] for p in points):
        raise ValueError('A point contract belongs to another task')
    return points


def prepare(preparation: Path, output: Path):
    """Root freezer calls this after task relocation; no EDA or model access."""
    preparation, output = Path(preparation).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('An immutable baseline plan is written once, never overwritten')
    tasks = sorted((preparation/'private').glob('*/task.json'))
    if len(tasks) != 24:
        raise ValueError('The fixed original-source baseline contains exactly24 tasks')
    began, cpu = time.monotonic(), time.process_time()
    output.mkdir(parents=True, mode=0o700)
    rows = []
    for task_path in tasks:
        task = read(task_path);points = validate_task(task)
        if task.get('status') != 'FROZEN_E3_TASK' or task.get('formal_admission') is not True:
            raise ValueError('Prepare follows task admission and relocation, before chmod/final method freeze')
        folder = output/'tasks'/task['task_id'];folder.mkdir(parents=True)
        binding = capsule(task_path, folder/'source')
        save(folder/'task.json', task)
        frozen_points = []
        for point in points:
            destination = folder/'trusted'/point['configuration_id']
            paths = trusted(task, point, destination)
            frozen_points.append({'configuration_id': point['configuration_id'], 'role': point['role'],
                'trusted_directory': str(destination.relative_to(output)), 'trusted_files': paths})
        rows.append({'task_id': task['task_id'], 'task_file': str((folder/'task.json').relative_to(output)),
            'source_directory': str((folder/'source').relative_to(output)),
            'source_files': binding['source_files'], 'entrypoint': binding['entrypoint'],
            'parent_lineage': task['parent_lineage'], 'points': frozen_points})
    if len({r['task_id'] for r in rows}) != 24:
        raise ValueError('Duplicate original-source task identity')
    plan = {'status': 'IMMUTABLE_E3_ORIGINAL_BASELINE_PLAN', 'version': VERSION,
        'declared_tasks': 24, 'declared_points': 600, 'maximum_new_physical_calls': 600,
        'fidelity': 'pex_spice', 'automatic_physical_retries': False, 'single_worker_CPUs': 2,
        'methods_must_be_frozen_before_physical_collection': True,
        'tools': {'image': IMAGE, 'pdk_revision': PDK, 'runtime': str(ROOT/'runtime/GLdev'),
            'magic': str(ROOT/'runtime/magic-8.3.685')},
        'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720,
        'tasks': rows, 'hidden_evidence_exported': False,
        'preparation_cost': {'wall_seconds': time.monotonic()-began,
            'process_CPU_seconds': time.process_time()-cpu, 'physical_calls': 0, 'model_calls': 0},
        'frozen_regular_file_bytes': sum(p.stat().st_size for p in output.rglob('*') if p.is_file())}
    save(output/'plan.json', plan)
    return plan


def load_plan(path):
    root = Path(path).resolve();root = root.parent if root.is_file() else root
    plan = read(root/'plan.json')
    if (plan['version'] != VERSION or plan['status'] != 'IMMUTABLE_E3_ORIGINAL_BASELINE_PLAN' or
            plan['declared_tasks'] != 24 or plan['declared_points'] != 600 or
            plan['maximum_new_physical_calls'] != 600 or plan['fidelity'] != 'pex_spice' or
            plan['automatic_physical_retries'] is not False):
        raise ValueError('A fixed600-slot original baseline plan is required')
    rows = plan['tasks']
    if len(rows) != 24 or len({row['task_id'] for row in rows}) != 24:
        raise ValueError('Baseline task matrix differs')
    for row in rows:
        task = read(root/row['task_file']);points = validate_task(task)
        expected = [(p['configuration_id'], p['role']) for p in points]
        if expected != [(p['configuration_id'], p['role']) for p in row['points']]:
            raise ValueError('Frozen baseline points differ from their task')
        if files(root/row['source_directory']) != row['source_files']:
            raise ValueError('Original complete source capsule file set differs')
        for point in row['points']:
            if files(root/point['trusted_directory']) != point['trusted_files']:
                raise ValueError('Frozen evaluator file set differs')
    return root, plan


def check_methods_freeze(manifest_path, plan_root, plan):
    manifest = read(manifest_path)
    if manifest.get('status') != 'FROZEN_E3' or manifest.get('formal_dispatch') is not True:
        raise ValueError('Private original/hidden measurements start only after actual E3 methods freeze')
    verify(manifest)
    from scripts.e3_episode import require_release
    require_release(manifest, episode=None, baseline=True)
    bound = Path(manifest['original_baseline_plan']).resolve()
    if bound != plan_root and bound != plan_root/'plan.json':
        raise ValueError('Manifest binds another original-baseline plan')
    if set(manifest['task_ids']) != {row['task_id'] for row in plan['tasks']}:
        raise ValueError('Original baseline must match the frozen method task matrix')
    if any(path.stat().st_mode & 0o222 for path in [plan_root, *plan_root.rglob('*')]):
        raise ValueError('The prospective source/evaluator/plan must already be read-only')
    if plan['tools'] != {'image': IMAGE, 'pdk_revision': PDK,
            'runtime': str(ROOT/'runtime/GLdev'), 'magic': str(ROOT/'runtime/magic-8.3.685')}:
        raise ValueError('Frozen tools differ from the actual executor')
    return manifest


def point_inputs(plan_root, task_row, point_row):
    task = read(plan_root/task_row['task_file'])
    point = next(p for p in task['configurations'] if p['configuration_id'] == point_row['configuration_id'])
    point = dict(point, reference_file=str(plan_root/point_row['trusted_directory']/'reference.spice'))
    source = plan_root/task_row['source_directory'];evaluator = plan_root/point_row['trusted_directory']
    return task, point, source, evaluator


def checked_raw(run, point, source, source_files):
    """Reinspect real reports; retained original unknowns stay unknown."""
    try:
        checked = inspect({'run_directory': str(run)}, point, source_contents(source, source_files, binary=True),
            {'parameters': point['parameters']}, 'pex_spice')
        if checked['S1']:
            intent = compare_device_intent((run/'evidence/extracted_lvs.spice').read_text(),
                (run/'trusted/reference.spice').read_text())
            if not intent['is_clean']:
                raise ValueError('Independent per-finger terminal graph contradicts S1')
        quality = None
        if checked['S2']:
            raw = read(run/'evidence/validation.json');definition = point['contract']['objective']
            values = [raw['observation']['corners'][corner]['metrics'][definition['metric']]
                for corner in point['contract']['required_corners']]
            if any(value['unit'] != definition['unit'] or type(value['value']) not in (float, int)
                    or not math.isfinite(value['value']) for value in values):
                raise ValueError('Objective requires finite actual values in the frozen units')
            quality = (min if definition['direction'] == 'max' else max)(v['value'] for v in values)
        return checked, quality
    except (ValueError, KeyError, OSError, TypeError) as error:
        return {'S0': False, 'S1': False, 'S2': False, 'execution_integrity': 'incomplete',
            'failure_class': 'unknown', 'reason': type(error).__name__+': '+str(error)}, None


def physical_costs(run):
    manifest = read(run/'manifest.json')
    result = {'physical_calls': 1, 'stage_wall_seconds': 0., 'waited_child_CPU_seconds': 0.,
        'missing_CPU_records': 0, 'missing_wall_records': 0}
    for stage in ('candidate', 'trusted'):
        if stage not in manifest:
            continue
        if type(manifest[stage].get('wall_seconds')) in (float, int):
            result['stage_wall_seconds'] += manifest[stage]['wall_seconds']
        else:
            result['missing_wall_records'] += 1
        usage = run/(stage+'_stage/resource_usage.json')
        if usage.is_file():
            row = read(usage)
            result['waited_child_CPU_seconds'] += row['child_user_cpu_seconds']+row['child_system_cpu_seconds']
        else:
            result['missing_CPU_records'] += 1
    return result


def adopt_anchor(evidence, point, source, source_files, evaluator):
    """Returns a byte-bound old point or an explicit miss; no EDA fallback here."""
    began, cpu = time.monotonic(), time.process_time()
    event = {'status': 'MISS', 'origin_run': evidence['run_directory']};bound = False
    try:
        run = Path(evidence['run_directory'])
        if (run/'evidence_archive.json').is_file():
            restore_run(run)
        expected = source_contents(source, source_files, binary=True)
        if not exact_bindings(run, expected, point, {'parameters': point['parameters']}, evaluator):
            event['reason'] = 'Exact source/configuration/reference/contract/deck/tools/fidelity binding differs; old E1 records without the E3 objective are not adopted'
            return None, event
        bound = True
        row = verify_cached(evidence, expected, point, evaluator)
        if row is None:
            checked, quality = checked_raw(run, point, source, source_files)
            row = {**evidence, 'checked': checked, 'objective': quality}
        row.update(baseline_origin='exact_prior_original_anchor', original_physical_phase=read(run/'manifest.json')['phase'],
            origin_physical_costs=physical_costs(run), new_physical_calls=0,
            objective_definition=point['contract']['objective'])
        event['status'] = 'HIT' if row['checked']['execution_integrity'] == 'valid' else 'EXACT_PRIOR_UNKNOWN_RETAINED'
        return row, event
    except (KeyError, ValueError, OSError, TypeError) as error:
        event['reason'] = type(error).__name__+': '+str(error)
        if bound:
            event['status'] = 'EXACT_PRIOR_UNKNOWN_RETAINED'
            return {**evidence, 'baseline_origin': 'exact_prior_original_anchor',
                'checked': {'S0': False, 'S1': False, 'S2': False, 'execution_integrity': 'incomplete',
                    'failure_class': 'unknown', 'reason': event['reason']}, 'objective': None,
                'objective_definition': point['contract']['objective'], 'new_physical_calls': 0,
                'origin_cost_accounting_error': event['reason']}, event
        return None, event
    finally:
        event.update(wall_seconds=time.monotonic()-began, process_CPU_seconds=time.process_time()-cpu)


def execute_point(plan_root, plan, task_row, point_row, output):
    task, point, source, evaluator = point_inputs(plan_root, task_row, point_row)
    output.mkdir(parents=True, exist_ok=False)
    result = CandidateExecutor(ROOT/'runtime/GLdev', output/'physical', ROOT/'runtime/magic-8.3.685', timeout=720).execute(
        source_dir=source, source_paths=task_row['source_files'], entrypoint=task_row['entrypoint'],
        representation='G2', configuration={'parameters': point['parameters']}, trusted_dir=evaluator,
        trusted_paths=point_row['trusted_files'], fidelity='pex_spice', phase='formal_E3',
        context={'source_role': 'trusted_evaluator_control', 'experiment_role': 'immutable_original_baseline',
            'candidate_id': task['task_id'], 'initial_state_id': task['task_id'], 'parent_lineage': task['parent_lineage'],
            'configuration_id': point['configuration_id'], 'reference_id': point['reference_id'], 'pdk_revision': PDK},
        generation_timeout_seconds=plan['generation_timeout_seconds'], evaluator_timeout_seconds=plan['evaluator_timeout_seconds'])
    run = Path(result['run_directory'])
    checked, quality = checked_raw(run, point, source, task_row['source_files'])
    row = {'task_id': task['task_id'], 'configuration_id': point['configuration_id'], 'role': point['role'],
        'fidelity': 'pex_spice', 'run_directory': str(run), 'checked': checked, 'objective': quality,
        'objective_definition': point['contract']['objective'], 'baseline_origin': 'fresh_immutable_original',
        'new_physical_calls': 1, 'formal_policy_trial': False, 'physical_costs': physical_costs(run),
        'created_at_utc': datetime.now(timezone.utc).isoformat()}
    save(output/'point.json', row)
    return row


def slots(plan):
    return [(task, point) for task in plan['tasks'] for point in task['points']]


def retained(plan, output):
    rows, missing = [], []
    for task, point in slots(plan):
        folder = output/'private/points'/task['task_id']/point['configuration_id']
        if (folder/'point.json').is_file():
            row = read(folder/'point.json')
            if (row['task_id'] != task['task_id'] or row['configuration_id'] != point['configuration_id'] or
                    row['role'] != point['role'] or row['fidelity'] != 'pex_spice'):
                raise ValueError('Retained baseline slot belongs to another frozen point')
            rows.append(row)
        elif folder.exists():
            raise RuntimeError('UNRESOLVED original baseline slot: '+str(folder)+'; preserve raw and reconcile, no automatic retry')
        else:
            missing.append((task, point, folder))
    return rows, missing


def aggregate(rows, plan, status):
    fresh = [r for r in rows if r['new_physical_calls']]
    keys = ('stage_wall_seconds', 'waited_child_CPU_seconds', 'missing_CPU_records', 'missing_wall_records')
    return {'status': status, 'scope': 'E3_original_source_private_baseline_not_policy_trials',
        'declared_tasks': 24, 'declared_points': 600, 'returned_points': len(rows),
        'new_physical_calls': len(fresh), 'adopted_prior_original_anchors': len(rows)-len(fresh),
        'valid_points': sum(r['checked']['execution_integrity'] == 'valid' for r in rows),
        'S2_verified': sum(r['checked']['execution_integrity'] == 'valid' and r['checked']['S2'] for r in rows),
        'unknown_points': sum(r['checked']['execution_integrity'] != 'valid' for r in rows),
        'costs': {key: sum(r['physical_costs'][key] for r in fresh) for key in keys},
        'origin_costs_kept_separate_in_private_point_records': True,
        'preparation_cost': plan['preparation_cost'], 'hidden_point_records_exported': False,
        'automatic_physical_retries': False, 'formal_policy_trials': 0}


def collect(manifest_path, output, anchor_evidence=()):
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    manifest = read(manifest_path);plan_root, plan = load_plan(manifest['original_baseline_plan'])
    check_methods_freeze(manifest_path, plan_root, plan)
    if output == plan_root or output.is_relative_to(plan_root) or output.is_relative_to(manifest_path.parent):
        raise ValueError('Actual baseline evidence belongs outside the immutable method freeze')
    private = output/'private';private.mkdir(parents=True, exist_ok=True, mode=0o700)
    (output/'public').mkdir(exist_ok=True)
    with (private/'collector.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        binding = {'manifest': str(manifest_path), 'original_baseline_plan': str(plan_root),
            'task_ids': manifest['task_ids'], 'version': VERSION}
        if (private/'binding.json').is_file() and read(private/'binding.json') != binding:
            raise ValueError('Resume cannot change the actual baseline plan/method freeze')
        save(private/'binding.json', binding)
        candidates = {}
        for evidence_path in anchor_evidence:
            data = read(evidence_path)
            for row in data.get('records', []):
                if row.get('configuration_id') == 'anchor' and row.get('run_directory'):
                    candidates.setdefault(row['task_id'], []).append(row)
        in_flight = read(private/'in_flight.json') if (private/'in_flight.json').is_file() else None
        if in_flight and not (Path(in_flight['point_directory'])/'point.json').is_file():
            raise RuntimeError('UNRESOLVED prior original-baseline dispatch; reconcile its actual execution before any new point')
        rows, missing = retained(plan, output)
        save(private/'in_flight.json', None)
        for task, point in slots(plan):
            folder = private/'points'/task['task_id']/point['configuration_id']
            if (folder/'point.json').is_file():
                archive_point(folder)
        if any(row['checked']['execution_integrity'] != 'valid' for row in rows):
            result = aggregate(rows, plan, 'PAUSED_PRIOR_UNKNOWN_NO_AUTOMATIC_NEW_DISPATCH')
            save(output/'public/summary.json', result)
            return result
        for task, point, folder in missing:
            check_methods_freeze(manifest_path, plan_root, plan)
            task_data, actual, source, evaluator = point_inputs(plan_root, task, point)
            adopted, cache_events = None, []
            if point['role'] == 'anchor':
                for evidence in candidates.get(task['task_id'], []):
                    adopted, event = adopt_anchor(evidence, actual, source, task['source_files'], evaluator)
                    cache_events.append(event)
                    if adopted is not None:
                        break
            if adopted is not None:
                row = {**adopted, 'task_id': task['task_id'], 'configuration_id': point['configuration_id'],
                    'role': point['role'], 'fidelity': 'pex_spice', 'anchor_cache_events': cache_events}
                save(folder/'point.json', row)
            else:
                if shutil.disk_usage(ROOT).free < 4*1024**3:
                    save(output/'public/summary.json', aggregate(rows, plan, 'PAUSED_STORAGE_NO_NEW_DISPATCH'))
                    return read(output/'public/summary.json')
                waiting, began = {}, time.monotonic()
                try:
                    waiting = gate()
                finally:
                    waiting['actual_wait_wall_seconds'] = time.monotonic()-began
                    save(private/'next_resource_wait.json', waiting)
                if len([r for r in rows if r['new_physical_calls']])+1 > plan['maximum_new_physical_calls']:
                    raise RuntimeError('The fixed600-call ceiling is exhausted')
                save(private/'in_flight.json', {'task_id': task['task_id'], 'configuration_id': point['configuration_id'],
                    'point_directory': str(folder), 'started_at_utc': datetime.now(timezone.utc).isoformat()})
                row = execute_point(plan_root, plan, task, point, folder)
                row.update(resource_wait=waiting, anchor_cache_events=cache_events)
                save(folder/'point.json', row)
            rows.append(row)
            save(private/'in_flight.json', None)
            archive_point(folder)
            if row['checked']['execution_integrity'] != 'valid':
                result = aggregate(rows, plan, 'PAUSED_UNKNOWN_NO_AUTOMATIC_RETRY')
                save(output/'public/summary.json', result)
                return result
            save(output/'public/summary.json', aggregate(rows, plan, 'RUNNING'))
        result = aggregate(rows, plan, 'COMPLETE')
        save(output/'public/summary.json', result)
        return result


def join(baseline_output, episode, output):
    """Private server-side vector join; the returned/written object is aggregate."""
    baseline_output, episode = Path(baseline_output).resolve(), Path(episode).resolve()
    binding = read(baseline_output/'private/binding.json')
    plan_root, plan = load_plan(binding['original_baseline_plan'])
    state = read(episode/'private/state.json');manifest = read(episode/'private/manifest.json')
    if not state.get('sealed') or state.get('in_flight') or not (episode/'public/episode.json').is_file():
        raise ValueError('Regression joins only a sealed source after its deployment/hidden phase terminates')
    main_manifest = read(binding['manifest'])
    same_freeze = manifest == main_manifest
    if manifest.get('status') == 'FROZEN_E3_FIDELITY_METHOD':
        same_freeze = (Path(manifest['main_protocol_manifest']).resolve() == Path(binding['manifest']).resolve()
            and manifest['main_freeze_id'] == main_manifest['freeze_id']
            and manifest['hidden_release_file'] == main_manifest['hidden_release_file']
            and manifest['original_baseline_plan'] == main_manifest['original_baseline_plan'])
    if (state.get('formal_trial') is not True or manifest.get('status') not in ('FROZEN_E3', 'FROZEN_E3_FIDELITY_METHOD') or
            not same_freeze):
        raise ValueError('The regression join requires an actual episode of the same formal method freeze')
    verify(manifest)
    from scripts.e3_episode import require_release
    require_release(manifest, episode)
    if Path(manifest['original_baseline_plan']).resolve() not in (plan_root, plan_root/'plan.json'):
        raise ValueError('Selected-source episode belongs to another original baseline plan')
    task = read(episode/'private/task.json')
    task_row = next(row for row in plan['tasks'] if row['task_id'] == task['task_id'])
    if task != read(plan_root/task_row['task_file']):
        raise ValueError('Selected and original task/domain/reference/contract bytes differ')
    original = []
    for point in task_row['points']:
        filename = baseline_output/'private/points'/task['task_id']/point['configuration_id']/'point.json'
        if filename.is_file():
            row = read(filename)
            if (row['task_id'] != task['task_id'] or row['configuration_id'] != point['configuration_id'] or
                    row['role'] != point['role'] or row['fidelity'] != 'pex_spice'):
                raise ValueError('Original observation belongs to another frozen slot')
            original.append(row)
    selected_path = episode/'private/post_freeze_points.json'
    selected = read(selected_path) if selected_path.is_file() else []
    result = summarize(task['configurations'], original, selected)
    search = read(episode/'public/search.json')
    result.update(task_id=task['task_id'], method=search['method'], trial_id=state.get('trial_id'), phase=state['phase'],
        fidelity_policy=manifest.get('fidelity_policy'), selector_variant=state.get('selector_variant', 'main'),
        policy_variant=state.get('policy_variant', 'GPT'), evaluation_seed_slot=state.get('evaluation_seed_slot'),
        baseline_output=str(baseline_output), episode_directory=str(episode),
        original_baseline_returned=len(original), sealed_source_revision=state['selection']['revision'])
    save(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare');p.add_argument('--preparation', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('collect');p.add_argument('--manifest', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    p.add_argument('--anchor-evidence', type=Path, action='append', default=[])
    p = sub.add_parser('join');p.add_argument('--baseline-output', type=Path, required=True)
    p.add_argument('--episode', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        report = prepare(args.preparation, args.output)
        print(json.dumps({key: value for key, value in report.items() if key != 'tasks'}), flush=True)
    elif args.command == 'collect':
        print(json.dumps(collect(args.manifest, args.output, args.anchor_evidence)), flush=True)
    else:
        print(json.dumps(join(args.baseline_output, args.episode, args.output)), flush=True)
