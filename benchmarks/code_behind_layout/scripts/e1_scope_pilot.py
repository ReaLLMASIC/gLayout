#!/usr/bin/env python3
"""One fresh bounded interface trial per G0/G1/G2; no hidden evaluation."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
from scripts.prepare_e1_scope_cohort import BUDGET, COHORT, read, save
from scripts.e1_scope_runner import resources


def now():return datetime.now(timezone.utc).isoformat()


def run(manifest_path, preflight_path, task, output):
    manifest, capacity = read(manifest_path), read(preflight_path)
    if (manifest.get('cohort_id') != COHORT or manifest['budget'] != BUDGET or manifest['formal_dispatch'] is not False
            or capacity['cohort_id'] != COHORT or capacity['packets'] != 72 or not capacity['all_initial_fit']
            or not capacity['all_three_real_payloads_fit']):
        raise ValueError('Only the unrun scope cohort after complete real-payload capacity preflight is accepted')
    if task not in manifest['task_ids']:raise ValueError('Pilot task is outside the prospective cohort')
    output = Path(output).resolve();output.mkdir(parents=True, exist_ok=True)
    with (output/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_file = output/'state.json'
        if state_file.exists():
            raise ValueError('This finite three-session pilot is never automatically repeated; inspect its original raw records')
        jobs = [{'method': method, 'task_id': task, 'status': 'NOT_RUN'} for method in ('G0', 'G1', 'G2')]
        state = {'status': 'RUNNING', 'cohort_id': COHORT, 'manifest': str(manifest_path), 'created_at_utc': now(),
            'jobs': jobs, 'per_session_limits': {'decisions': 2, 'visible_physical_calls': 1, 'hidden_calls': 0},
            'maximum_prelaunch_queue_wall_seconds': 1200, 'automatic_retry': False};save(state_file, state)
        queue_start = time.monotonic()
        children = {};logs = {}
        while True:
            for method, child in list(children.items()):
                if child.poll() is None:continue
                logs.pop(method).close();job = next(j for j in jobs if j['method'] == method)
                job.update(returncode=child.returncode, ended_at_utc=now(), status='RETURNED');del children[method]
                record = Path(job['dispatch_record'])
                if record.is_file():
                    client = read(record)
                    if client.get('cohort_id') != COHORT or client['formal'] is not False:raise ValueError('Wrong pilot client identity')
                    directory = Path(client['local_output_directory'])
                    if (directory/'search_report.json').is_file():
                        shutil.copytree(directory, output/'policy'/method)
                        report = read(directory/'search_report.json')
                        job.update(episode_directory=client['episode_directory'], local_output_directory=str(directory),
                            raw_directory=str(output/'policy'/method), search_status=report['status'],
                            actual_model_cli_invocations=report['costs_by_stage'].get('policy', {}).get('model_cli_invocations'),
                            visible_calls=report['selection_calls'], hidden_calls=report['costs_by_stage']['hidden']['physical_calls'])
                    else:job['status'] = 'UNRESOLVED_NO_SEARCH_RETURN'
                else:job['status'] = 'UNRESOLVED_NO_CLIENT_RECORD'
            pending = next((j for j in jobs if j['status'] == 'NOT_RUN'), None)
            if pending and time.monotonic()-queue_start >= 1200:
                state['status'] = 'PAUSED_RESOURCE_QUEUE_BUDGET';pending = None
            if pending and len(children) < 3:
                sample = resources();state['last_resource_sample'] = sample
                if sample['disk_available_GiB'] < 4:state['status'] = 'PAUSED_STORAGE';pending = None
                elif sample['busy_cores']+2 <= 24 and sample['RAM_used_GiB'] <= 190:
                    folder = output/pending['method'];folder.mkdir();record = folder/'client.json'
                    command = [sys.executable, str(ROOT/'scripts/e1_scope_runner.py'), '--manifest', manifest['backend_manifest_path'],
                        '--task', task, '--method', pending['method'], '--trial', 'scope_interface_pilot', '--pilot', '--dispatch-record', str(record)]
                    pending.update(status='DISPATCH_RESERVED', dispatch_record=str(record), argv=command, reserved_at_utc=now())
                    save(state_file, state)  # durable before any policy/backend start
                    log = (folder/'runner.log').open('x')
                    try:
                        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                            env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
                        pending.update(status='RUNNING', pid=child.pid);children[pending['method']] = child;logs[pending['method']] = log
                    except Exception as error:
                        log.close();pending.update(status='UNRESOLVED_LAUNCH', error=type(error).__name__+': '+str(error))
            save(state_file, state)
            if not children and (not any(j['status'] == 'NOT_RUN' for j in jobs) or state['status'] != 'RUNNING'):break
            time.sleep(3)
        state['status'] = 'FINITE_PILOT_RETURNED' if all(j['status'] == 'RETURNED' for j in jobs) else 'INCOMPLETE_FINITE_PILOT'
        state['qualification'] = 'Trusted backend raw inspection is required; a returned process alone is not an interface pass.'
        state['ended_at_utc'] = now();save(state_file, state);save(output/'summary.json', state)
        return state


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--preflight', type=Path, required=True);p.add_argument('--task', default='draft_E1_mirror_s01')
    p.add_argument('--output', type=Path, required=True);a = p.parse_args()
    print(json.dumps(run(a.manifest, a.preflight, a.task, a.output)), flush=True)
