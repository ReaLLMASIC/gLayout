#!/usr/bin/env python3
"""Bounded Claude interface pilot against a cohort DRAFT manifest; no hidden or post-freeze call.

E1: one fresh --pilot episode per interface G0/G1/G2 (two decisions, one visible full evaluation).
E3: one development --search-only episode per method C and A under the draft's two-decision budget.
Sessions run one at a time. Every CLI envelope, request, token budget and action is retained and
copied beside the summary so the freeze can re-inspect them.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort import common  # noqa: E402
from scripts.opus_cohort.common import POLICY_BACKEND, POLICY_MODEL, read, save  # noqa: E402

DRIVERS = {'E3': ROOT / 'scripts/opus_cohort/e3_episode_opus.py', 'E1': ROOT / 'scripts/opus_cohort/e1_scope_runner_opus.py'}
DEFAULT_METHODS = {'E3': ['C', 'A'], 'E1': ['G0', 'G1', 'G2']}
DEFAULT_TASKS = {'E3': 'draft_E3_mirror_edit02', 'E1': 'draft_E1_mirror_s01'}


def now():
    return datetime.now(timezone.utc).isoformat()


def argv_for(kind, manifest, task, method, record):
    common_args = ['--manifest', manifest['backend_manifest_path'], '--task', task, '--method', method,
                   '--trial', 'claude_pilot', '--dispatch-record', str(record)]
    if kind == 'E1':
        return [sys.executable, str(DRIVERS[kind]), *common_args, '--pilot']
    return [sys.executable, str(DRIVERS[kind]), *common_args, '--selection-seed', '41', '--search-only']


def invocation_rows(raw):
    rows = []
    for path in sorted(raw.glob('decisions/*/decision_*/invocation.json')):
        record = read(path)
        rows.append({key: record.get(key) for key in ('pid', 'status', 'requested_model', 'requested_effort', 'actual_models',
                                                      'num_turns', 'permission_denials', 'native_item_types', 'wall_seconds',
                                                      'fence_stripped', 'returncode')} | {'path': str(path), 'action_accepted': (path.parent / 'action.json').is_file()})
    return rows


def collect(kind, job, output):
    record = Path(job['dispatch_record'])
    if not record.is_file():
        job['status'] = 'UNRESOLVED_NO_CLIENT_RECORD'
        return
    client = read(record)
    job.update(episode_directory=client.get('episode_directory'), local_output_directory=client.get('local_output_directory'),
               policy_backend_recorded=client.get('policy_backend'))
    local = Path(client['local_output_directory'])
    raw = output / 'policy' / job['method']
    if raw.exists():
        shutil.rmtree(raw)
    shutil.copytree(local, raw)
    job['raw_directory'] = str(raw)
    report_name = 'search_report.json' if kind == 'E1' else 'search.json'
    if (local / report_name).is_file():
        report = read(local / report_name)
        job['search_status'] = report.get('status')
        if kind == 'E1':
            job['visible_calls'] = report.get('selection_calls')
            job['hidden_calls'] = report.get('costs_by_stage', {}).get('hidden', {}).get('physical_calls', 0)
        else:
            job['hidden_calls'] = 0 if report.get('post_freeze_started') in (None, False) else 1
            job['full_evaluations'] = report.get('full_evaluations')
    else:
        job['status'] = 'UNRESOLVED_NO_SEARCH_RETURN'
        return
    rows = invocation_rows(raw)
    job['invocations'] = rows
    job['actions_accepted'] = sum(row['action_accepted'] for row in rows)
    session = next(iter(sorted(raw.glob('decisions/*/session.json'))), None) or next(iter(sorted(raw.glob('session.json'))), None)
    if session is not None:
        value = read(session)
        job['decisions'] = len(value.get('history', []))
        job['provider_usage'] = value.get('usage')
    job['status'] = 'RETURNED'


def run(kind, manifest_path, task, methods, output):
    manifest = read(manifest_path)
    common.require_claude_manifest(manifest, kind, formal=False)
    if manifest.get('formal_dispatch') is not False or not manifest['freeze_id'].endswith('_DRAFT'):
        raise ValueError('The pilot runs only against the unfrozen cohort draft')
    if task not in manifest['task_ids']:
        raise ValueError('Pilot task is outside the cohort')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('This finite pilot is never automatically repeated; inspect or move its records: ' + str(output))
    output.mkdir(parents=True)
    jobs = [{'method': method, 'task_id': task, 'status': 'NOT_RUN'} for method in methods]
    state = {'status': 'RUNNING', 'kind': kind, 'cohort_label': common.COHORT_LABEL[kind], 'manifest': str(manifest_path),
             'manifest_backend_path': manifest['backend_manifest_path'], 'policy_backend': POLICY_BACKEND, 'policy_model': POLICY_MODEL,
             'task': task, 'created_at_utc': now(), 'jobs': jobs, 'hidden_calls': 0, 'automatic_retry': False,
             'per_session_limits': {'E1': {'decisions': 2, 'visible_physical_calls': 1}, 'E3': manifest['budget']}[kind]}
    save(output / 'summary.json', state)
    for job in jobs:
        folder = output / job['method']
        folder.mkdir()
        record = folder / 'client.json'
        argv = argv_for(kind, manifest, task, job['method'], record)
        job.update(argv=argv, dispatch_record=str(record), started_at_utc=now(), status='RUNNING')
        save(output / 'summary.json', state)
        with (folder / 'runner.log').open('x') as log:
            process = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
        job.update(returncode=process.returncode, ended_at_utc=now())
        try:
            collect(kind, job, output)
        except Exception as error:
            job.update(status='UNRESOLVED_COLLECTION', reason=type(error).__name__ + ': ' + str(error))
        save(output / 'summary.json', state)
    state['hidden_calls'] = sum(job.get('hidden_calls') or 0 for job in jobs)
    state['status'] = 'FINITE_PILOT_RETURNED' if all(job['status'] == 'RETURNED' for job in jobs) else 'INCOMPLETE_FINITE_PILOT'
    state['ended_at_utc'] = now()
    save(output / 'summary.json', state)
    return state


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind', choices=('E3', 'E1'), required=True)
    p.add_argument('--manifest', type=Path, required=True, help='Local copy of the cohort DRAFT manifest')
    p.add_argument('--task')
    p.add_argument('--methods', nargs='+')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = run(a.kind, a.manifest, a.task or DEFAULT_TASKS[a.kind], a.methods or DEFAULT_METHODS[a.kind], a.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'jobs'} | {'jobs': [{k: j.get(k) for k in ('method', 'status', 'returncode', 'search_status', 'actions_accepted', 'hidden_calls')} for j in result['jobs']]}, indent=2))
