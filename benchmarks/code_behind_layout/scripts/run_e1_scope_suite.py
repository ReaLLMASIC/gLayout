#!/usr/bin/env python3
"""Fresh cohort-specific E1 matrix; no old interface trial is carried forward."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
from scripts.prepare_e1_scope_cohort import BUDGET, COHORT, read
from scripts.run_e1_suite import plan as original_plan
from scripts.e1_scope_runner import SSH, resources
from scripts.e1_matched_runner import REMOTE


def now():return datetime.now(timezone.utc).isoformat()
def save(filename, value):
    filename = Path(filename);temporary = filename.with_name(filename.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n');temporary.replace(filename)


def archive_evidence(job):
    command = 'cd '+shlex.quote(REMOTE)+' && '+shlex.quote(REMOTE+'/runtime/GLdev/bin/python')+' scripts/archive_e1_episode.py --episode '+shlex.quote(job['episode_directory'])
    result = subprocess.run(SSH+[command], text=True, capture_output=True, check=True, timeout=120)
    row = json.loads(result.stdout)
    if row['status'] != 'COMPRESSED_RAW_RETAINED' or row['hidden_evidence_exported'] is not False:
        raise ValueError('Actual private raw evidence archive not established')
    job['evidence_archive'] = row


def plan(manifest):
    if manifest.get('cohort_id') != COHORT or manifest['budget'] != BUDGET:raise ValueError('Use the independent16k cohort only')
    return [{**row, 'cohort_id': COHORT} for row in original_plan(manifest)]


def collect(job, manifest):
    filename = Path(job['dispatch_record'])
    if not filename.is_file():raise ValueError('No actual child dispatch record; never infer success from stdout')
    client = read(filename)
    if ((client['task_id'], client['method'], str(client['trial_id'])) != (job['task_id'], job['method'], job['trial_id'])
            or client['cohort_id'] != COHORT or client['formal'] is not True):raise ValueError('Child belongs to another cohort/trial')
    episode = Path(client['local_output_directory'])/'episode.json'
    if not episode.is_file():raise ValueError('No returned local full evaluation report')
    row = read(episode)
    if (row.get('cohort_id') != COHORT or row.get('freeze_id') != manifest['freeze_id'] or row['phase'] != 'formal_E1'
            or (row['task_id'], row['method'], str(row['trial_id'])) != (job['task_id'], job['method'], job['trial_id'])
            or row.get('post_freeze_status') not in ('COMPLETE', 'INCOMPLETE_UNKNOWN') or not row.get('sealed')):
        raise ValueError('The actual returned report is partial, unsealed or from another freeze')
    if job.get('waited_returncode') not in (None, 0):raise ValueError('A nonzero child remains unresolved without an automatic retry')
    job.update(status='RECORDED', episode_json=str(episode), episode_directory=client['episode_directory'],
        local_output_directory=client['local_output_directory'], ended_at_utc=now(),
        post_freeze_status=row['post_freeze_status'], requires_pause=row['post_freeze_status'] == 'INCOMPLETE_UNKNOWN')
    archive_evidence(job)


def alive(job):
    result = subprocess.run(['ps', '-p', str(job['pid']), '-o', 'command='], text=True, capture_output=True)
    if result.returncode and result.stderr.strip():return None
    return result.returncode == 0 and 'e1_scope_runner.py' in result.stdout and job['dispatch_record'] in result.stdout


def index(output, jobs):
    rows = [{key: job[key] for key in ('cohort_id', 'task_id', 'method', 'trial_id', 'status',
        'episode_json', 'episode_directory', 'local_output_directory') if key in job} for job in jobs]
    save(output/'complete_matrix_index.json', rows)
    (output/'episode_index.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows if row['status'] == 'RECORDED'))


def run(args):
    manifest_path = args.manifest.resolve();manifest = read(manifest_path);jobs = plan(manifest)
    output = args.output.resolve();output.mkdir(parents=True, exist_ok=True)
    with (output/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        expected = {'cohort_id': COHORT, 'freeze_id': manifest['freeze_id'], 'manifest': str(manifest_path),
            'backend_manifest': manifest['backend_manifest_path'], 'jobs': jobs, 'automatic_retry': False}
        plan_file = output/'plan.json';state_file = output/'state.json'
        if plan_file.exists():
            if read(plan_file) != expected or plan_file.stat().st_mode & 0o222:raise ValueError('A fresh cohort plan cannot change or import old trials')
        else:save(plan_file, expected);plan_file.chmod(0o444)
        if state_file.exists():
            state = read(state_file)
            if (state.get('cohort_id') != COHORT or state['freeze_id'] != manifest['freeze_id'] or state['manifest'] != str(manifest_path)
                    or [(j['task_id'], j['method'], j['trial_id']) for j in state['jobs']] != [(j['task_id'], j['method'], j['trial_id']) for j in jobs]):
                raise ValueError('Resume must use the same complete independent cohort matrix')
            jobs = state['jobs']
        else:state = {'status': 'RUNNING', 'cohort_id': COHORT, 'freeze_id': manifest['freeze_id'], 'manifest': str(manifest_path),
            'created_at_utc': now(), 'formal_episodes_planned': 360, 'jobs': jobs, 'automatic_retry': False}
        state.update(coordinator_pid=os.getpid(), maximum_simultaneous_episodes=args.workers)
        children = {};logs = {}
        while True:
            active = []
            for number, job in enumerate(jobs):
                if job['status'] == 'DISPATCH_RESERVED':job.update(status='UNRESOLVED_RESERVATION', reason='No durable PID after reservation; never assume no backend start')
                if job['status'] != 'RUNNING':continue
                child = children.get(number);running = child.poll() is None if child else alive(job)
                if running is True:active.append(number);continue
                if running is None:job.update(status='UNRESOLVED_PROCESS_OBSERVATION');continue
                job['waited_returncode'] = child.returncode if child else None
                if child:logs.pop(number).close()
                try:collect(job, manifest)
                except Exception as error:job.update(status='UNRESOLVED_RETURN', reason=type(error).__name__+': '+str(error))
            unresolved = any(j['status'].startswith('UNRESOLVED') or j.get('requires_pause') for j in jobs)
            pause = unresolved or (output/'PAUSE_REQUESTED').exists()
            pending = next((i for i, j in enumerate(jobs) if j['status'] == 'NOT_RUN'), None)
            if not active and (pending is None or pause):
                state['status'] = 'PAUSED_UNRESOLVED_OR_UNKNOWN' if unresolved else 'PAUSED' if pause else 'COMPLETE';break
            if not pause and pending is not None and len(active) < args.workers:
                sample = resources();state['last_resource_sample'] = {**sample, 'at_utc': now()}
                if sample['disk_available_GiB'] < 4 and not active:state['status'] = 'PAUSED_STORAGE';break
                if sample['busy_cores']+2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_available_GiB'] >= 4:
                    job = jobs[pending];folder = output/('%03d_%s_%s_%s' % (pending, job['task_id'], job['method'], job['trial_id']))
                    if folder.exists():job['status'] = 'UNRESOLVED_EXISTING_DIRECTORY';continue
                    folder.mkdir();record = folder/'client.json'
                    command = [sys.executable, str(ROOT/'scripts/e1_scope_runner.py'), '--manifest', manifest['backend_manifest_path'],
                        '--task', job['task_id'], '--method', job['method'], '--trial', job['trial_id'], '--formal', '--dispatch-record', str(record)]
                    save(folder/'reservation.json', {'cohort_id': COHORT, 'argv': command, 'reserved_at_utc': now()});(folder/'reservation.json').chmod(0o444)
                    job.update(status='DISPATCH_RESERVED', argv=command, dispatch_record=str(record), resources_before_launch=sample)
                    save(state_file, state)
                    log = (folder/'runner.log').open('x')
                    try:
                        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                            env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
                        job.update(status='RUNNING', pid=child.pid, started_at_utc=now());children[pending] = child;logs[pending] = log
                    except Exception as error:log.close();job.update(status='UNRESOLVED_LAUNCH', reason=str(error))
            state.update(updated_at_utc=now(), jobs=jobs);save(state_file, state);index(output, jobs);time.sleep(5)
        state.update(updated_at_utc=now(), coordinator_pid=None, jobs=jobs);save(state_file, state);index(output, jobs)
        return {'cohort_id': COHORT, 'status': state['status'], 'planned': 360, 'recorded': sum(j['status'] == 'RECORDED' for j in jobs)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True);p.add_argument('--workers', type=int, choices=range(1, 5), default=4)
    print(json.dumps(run(p.parse_args())), flush=True)
