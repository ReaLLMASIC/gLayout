#!/usr/bin/env python3
"""Bounded interface pilot for the amended E1-C2 cohort: one --pilot episode per G0/G1/G2 against its DRAFT manifest."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort import common, common_v2  # noqa: E402
from scripts.opus_cohort import pilot_opus_policy as v1  # noqa: E402
from scripts.opus_cohort.common import POLICY_BACKEND, POLICY_MODEL, read, save  # noqa: E402

DRIVER = ROOT / 'scripts/opus_cohort/e1_scope_runner_opus_v2.py'


def now():
    return datetime.now(timezone.utc).isoformat()


def run(manifest_path, task, methods, output):
    manifest = read(manifest_path)
    common_v2.require_claude_manifest_v2(manifest, formal=False)
    if manifest.get('formal_dispatch') is not False or not manifest['freeze_id'].endswith('_DRAFT'):
        raise ValueError('The pilot runs only against the unfrozen cohort draft')
    if task not in manifest['task_ids']:
        raise ValueError('Pilot task is outside the cohort')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('This finite pilot is never automatically repeated; inspect or move its records: ' + str(output))
    output.mkdir(parents=True)
    jobs = [{'method': method, 'task_id': task, 'status': 'NOT_RUN'} for method in methods]
    state = {'status': 'RUNNING', 'kind': 'E1', 'cohort_label': common_v2.COHORT_LABEL_V2, 'system_prompt_version': common_v2.SYSTEM_PROMPT_VERSION,
             'manifest': str(manifest_path), 'manifest_backend_path': manifest['backend_manifest_path'],
             'policy_backend': POLICY_BACKEND, 'policy_model': POLICY_MODEL, 'task': task, 'created_at_utc': now(),
             'jobs': jobs, 'hidden_calls': 0, 'automatic_retry': False, 'per_session_limits': {'decisions': 2, 'visible_physical_calls': 1}}
    save(output / 'summary.json', state)
    for job in jobs:
        folder = output / job['method']
        folder.mkdir()
        record = folder / 'client.json'
        argv = [sys.executable, str(DRIVER), '--manifest', manifest['backend_manifest_path'], '--task', task, '--method', job['method'],
                '--trial', 'claude_pilot', '--dispatch-record', str(record), '--pilot']
        job.update(argv=argv, dispatch_record=str(record), started_at_utc=now(), status='RUNNING')
        save(output / 'summary.json', state)
        with (folder / 'runner.log').open('x') as log:
            process = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
        job.update(returncode=process.returncode, ended_at_utc=now())
        try:
            v1.collect('E1', job, output)
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
    p.add_argument('--manifest', type=Path, required=True, help='Local copy of the E1-C2 DRAFT manifest')
    p.add_argument('--task', default='draft_E1_mirror_s01')
    p.add_argument('--methods', nargs='+', default=['G0', 'G1', 'G2'])
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = run(a.manifest, a.task, a.methods, a.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'jobs'} | {'jobs': [{k: j.get(k) for k in ('method', 'status', 'returncode', 'search_status', 'actions_accepted', 'hidden_calls')} for j in result['jobs']]}, indent=2))
