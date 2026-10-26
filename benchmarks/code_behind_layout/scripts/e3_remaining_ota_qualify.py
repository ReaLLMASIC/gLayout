#!/usr/bin/env python3
"""Fixed four remaining E3 OTA initial anchors, after existing lanes stop.

This is development qualification, never a tested-policy episode. Returned
failures and unknowns are preserved and not automatically repeated. An existing
point directory without its final point record is unresolved, not a retry slot.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_generation_qualify import gate
from scripts.e3_physical_point import evaluate
from scripts.e3_task_prepare import save

TASKS = ('draft_E3_five_t_edit02', 'draft_E3_five_t_edit03',
         'draft_E3_compact_miller_edit02', 'draft_E3_compact_miller_edit03')


def read(path):
    return json.loads(path.read_text())


def returned_file(path):
    try:
        return read(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return None  # the producing lane may be writing its final JSON now


def wait_upstream(full_summary, basic_point, output, timeout):
    began = time.monotonic()
    while True:
        full, basic = returned_file(full_summary), returned_file(basic_point)
        if full is not None and full.get('status') != 'COMPLETE':
            raise RuntimeError('Upstream full lane has a non-complete terminal summary; reconcile it first')
        if full is not None and basic is not None:
            if basic.get('fidelity') != 'basic' or not isinstance(basic.get('checked'), dict) or not basic.get('run_directory'):
                raise ValueError('The prerequisite basic point is not an actual returned point record')
            record = {'status': 'UPSTREAM_PHYSICAL_LANES_RETURNED', 'full_summary': str(full_summary),
                'basic_point': str(basic_point), 'queue_wait_wall_seconds': time.monotonic()-began,
                'upstream_basic_checked': basic['checked']}
            save(output/'queue_wait.json', record)
            return full, record
        elapsed = time.monotonic()-began
        save(output/'queue_wait.json', {'status': 'WAITING_UPSTREAM', 'full_summary_present': full is not None,
            'basic_point_present': basic is not None, 'queue_wait_wall_seconds': elapsed})
        if elapsed >= timeout:
            raise TimeoutError('Upstream full/basic lanes did not reach returned point records within the declared wait limit; no new physical point dispatched')
        time.sleep(min(15, max(0.01, timeout-elapsed)))


def fixed_plan(preparation):
    records = []
    for ident in TASKS:
        path = preparation/'private'/ident/'task.json';task = read(path)
        if task['task_id'] != ident or task['target'] not in ('five_t', 'compact_miller'):
            raise ValueError('The final qualification plan contains exactly the four declared OTA states')
        if task.get('formal_admission') is True:
            raise ValueError('This control qualifies draft initial states; it does not run formal policy trials')
        records.append({'task_id': ident, 'task_path': str(path), 'task_json': path.read_text(),
            'editable_source_bytes_as_text': {name: Path(source).read_text() for name, source in task['source_overrides'].items()}})
    return records


def retained_points(output):
    """A returned unknown is still an occurred point and must never be rerun."""
    done, missing = {}, []
    for ident in TASKS:
        folder = output/'points'/ident;point = folder/'point.json'
        if point.is_file():
            row = read(point)
            if row.get('task_id') != ident or row.get('configuration_id') != 'anchor' or row.get('fidelity') != 'pex_spice':
                raise ValueError('A retained point belongs to another source/configuration/fidelity')
            if not row.get('run_directory') or not isinstance(row.get('checked'), dict):
                raise ValueError('An existing point lacks its actual execution record')
            if (folder/'resources.json').is_file():
                row['resources'] = read(folder/'resources.json')
            done[ident] = row
        elif folder.exists():
            raise RuntimeError('UNRESOLVED '+ident+': point directory exists without a returned point.json; retain raw and reconcile instead of rerunning')
        else:
            missing.append(ident)
    return done, missing


def run(preparation, full_summary, basic_point, output, wait_timeout):
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (output/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = {'scope': 'development_E3_final_four_OTA_initial_anchor_qualification',
            'preparation': str(preparation), 'tasks': fixed_plan(preparation),
            'full_summary': str(full_summary), 'basic_point': str(basic_point),
            'fidelity': 'pex_spice', 'configuration': 'anchor', 'formal_trials': 0, 'model_calls': 0,
            'source_sizing_reference_specification_changes': False,
            'single_worker_CPUs': 2, 'automatic_retry': False}
        plan_path = output/'plan.json'
        if plan_path.is_file():
            if read(plan_path) != plan:
                raise ValueError('Resume must retain the exact original four source/contract/task bindings and prerequisites')
        else:
            save(plan_path, plan)
        invocations = output/'invocations';invocations.mkdir(exist_ok=True)
        invocation = invocations/('%04d' % len([path for path in invocations.iterdir() if path.is_dir()]))
        invocation.mkdir()
        save(invocation/'start.json', {'pid': os.getpid(), 'argv': sys.argv,
            'started_at_utc': datetime.now(timezone.utc).isoformat(), 'scope': plan['scope']})
        save(output/'latest_invocation.json', {'directory': str(invocation), 'pid': os.getpid()})
        done, missing = retained_points(output)
        upstream, waiting = wait_upstream(full_summary, basic_point, invocation, wait_timeout)
        dispatched = 0
        for ident in missing:
            resources = gate()
            if shutil.disk_usage(ROOT).free < 4*1024**3:
                raise RuntimeError('Research disk below4GiB; no new OTA qualification point dispatched')
            # Check bindings immediately before each actual launch, including
            # a resume; no size or source is selected using physical outcomes.
            if fixed_plan(preparation) != plan['tasks']:
                raise ValueError('A fixed initial source or task binding changed')
            task_path = preparation/'private'/ident/'task.json'
            result = evaluate(task_path, 'anchor', output/'points'/ident, fidelity='pex_spice')
            result['resources'] = resources
            save(output/'points'/ident/'resources.json', resources)
            done[ident] = result;dispatched += 1
            save(output/'progress.json', {'status': 'RUNNING', 'declared_states': 4,
                'returned_states': len(done), 'dispatched_this_invocation': dispatched,
                'records': [done[name] for name in TASKS if name in done]})
            print(json.dumps({'task_id': ident, 'returned': len(done),
                'checked': {key: result['checked'].get(key) for key in ('S0', 'S1', 'S2', 'execution_integrity', 'failure_class')},
                'objective': result['objective']}), flush=True)
        records = [done[name] for name in TASKS]
        summary = {'scope': plan['scope'], 'status': 'COMPLETE', 'preparation': str(preparation),
            'declared_states': 4, 'returned_states': len(records),
            'total_unique_physical_runs': len({row['run_directory'] for row in records}),
            'S2_verified': sum(row['checked']['execution_integrity'] == 'valid' and row['checked']['S2'] for row in records),
            'unknown_states': sum(row['checked']['execution_integrity'] != 'valid' for row in records),
            'dispatched_this_invocation': dispatched, 'retained_previous_points': 4-dispatched,
            'records': records, 'upstream_queue': waiting, 'formal_trials': 0, 'model_calls': 0,
            'interpretation': 'Complete means all fixed four executions returned, not all states feasible. Historical failures/unknowns and their costs remain unchanged.'}
        save(output/'summary.json', summary)
        merged = {'scope': 'development_E3_all24_initial_anchor_evidence_not_formal', 'status': 'COMPLETE',
            'records': upstream['records']+records, 'original_full_summary': str(full_summary),
            'remaining_four_summary': str(output/'summary.json'), 'extra_basic_control': str(basic_point),
            'formal_trials': 0, 'model_calls': 0,
            'interpretation': 'Failed cache audits remain raw; only adopted audits and actual returned point records count as inventory evidence. No hidden domain layout qualification is claimed.'}
        save(output/'merged_inventory_evidence.json', merged)
        from scripts.e3_summarize_qualification import summarize
        summarize(preparation, output/'merged_inventory_evidence.json', output/'qualification.json')
        save(invocation/'finish.json', {'status': 'COMPLETE', 'dispatched_this_invocation': dispatched,
            'retained_previous_points': 4-dispatched, 'ended_at_utc': datetime.now(timezone.utc).isoformat()})
        print(json.dumps({'summary': str(output/'summary.json'), 'merged_inventory_evidence': str(output/'merged_inventory_evidence.json'),
            'returned_states': 4, 'S2_verified': summary['S2_verified'], 'unknown_states': summary['unknown_states']}), flush=True)
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation', type=Path, required=True)
    parser.add_argument('--full-summary', type=Path, required=True)
    parser.add_argument('--basic-point', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wait-timeout-seconds', type=int, default=7200)
    args = parser.parse_args()
    run(args.preparation, args.full_summary, args.basic_point, args.output, args.wait_timeout_seconds)
