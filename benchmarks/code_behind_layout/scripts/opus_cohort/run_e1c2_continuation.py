#!/usr/bin/env python3
"""Acknowledge an operator-inspected hidden-stage unknown in E1-C2 and dispatch only the never-run rows.

Mirrors scripts/run_e1_scope_continuation.py for the Claude cohort: the original suite state stays
untouched; the acknowledged episode keeps its recorded unknown (no retry, no relabel); rows that were
never dispatched continue under the same frozen manifest, plan order and driver; any new unknown pauses
again. The continuation state holds every original row plus the continued ones, so analysis reads one
file with all 144 identities.
"""
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort import common, common_v2  # noqa: E402
from scripts.opus_cohort import run_e1_scope_suite_opus_v2 as v2  # noqa: E402
from scripts import run_e1_scope_suite as base  # noqa: E402
from scripts.prepare_e1_scope_cohort import COHORT, read  # noqa: E402

now, save = base.now, base.save
DISCLOSURE = ('Post-observation administrative stopping-rule acknowledgement: one hidden point of one episode ended as an '
              'infrastructure unknown (incomplete analysis), the episode is retained with its observed denominators, and only '
              'never-dispatched rows continue. Not a wholly blind original protocol.')


def identity(job):
    return job['task_id'], job['method'], str(job['trial_id'])


def run(args):
    manifest_path = args.manifest.resolve(); manifest = read(manifest_path)
    common_v2.require_claude_manifest_v2(manifest)
    base_dir = args.base.resolve(); base_state = read(base_dir / 'state.json'); base_plan = read(base_dir / 'plan.json')
    if base_state['freeze_id'] != manifest['freeze_id'] or [identity(j) for j in base_plan['jobs']] != [identity(j) for j in base_state['jobs']]:
        raise ValueError('Continuation must use the original cohort plan and freeze')
    jobs = copy.deepcopy(base_state['jobs'])
    acknowledged = [i for i, j in enumerate(jobs) if j.get('requires_pause')]
    if sorted(acknowledged) != sorted(args.acknowledge):
        raise ValueError('Acknowledged indices differ from the paused rows: %s' % acknowledged)
    for i, j in enumerate(jobs):
        if i in acknowledged:
            if j['status'] != 'RECORDED' or j.get('post_freeze_status') != 'INCOMPLETE_UNKNOWN':
                raise ValueError('Only a recorded episode whose hidden stage ended unknown may be acknowledged')
        elif j['status'] == 'RECORDED':
            if j.get('requires_pause') or j.get('post_freeze_status') != 'COMPLETE':
                raise ValueError('No other unknown is acknowledged')
        elif j['status'] != 'NOT_RUN' or any(k in j for k in ('pid', 'dispatch_record', 'started_at_utc')):
            raise ValueError('Only never-dispatched rows may continue')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    with (output / 'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = {'continuation_of': str(base_dir), 'original_plan_sha256': common.digest(base_dir / 'plan.json'), 'cohort_id': COHORT,
                'cohort_label': common_v2.COHORT_LABEL_V2, 'freeze_id': manifest['freeze_id'], 'manifest': str(manifest_path),
                'acknowledged_indices': sorted(acknowledged), 'acknowledged': [{'index': i, **{k: jobs[i][k] for k in ('task_id', 'method', 'trial_id', 'episode_directory', 'post_freeze_status')}} for i in acknowledged],
                'reason': args.reason, 'protocol_disclosure': DISCLOSURE, 'jobs': [identity(j) for j in jobs], 'automatic_retry': False}
        plan_file, state_file = output / 'plan.json', output / 'state.json'
        if plan_file.exists():
            if read(plan_file) != plan or plan_file.stat().st_mode & 0o222:
                raise ValueError('A continuation plan cannot change')
        else:
            save(plan_file, plan); plan_file.chmod(0o444)
        if state_file.exists():
            state = read(state_file)
            if [identity(j) for j in state['jobs']] != [identity(j) for j in jobs]:
                raise ValueError('Resume must use the same continuation matrix')
            jobs = state['jobs']
        else:
            state = {'status': 'RUNNING', 'continuation_of': str(base_dir), 'cohort_id': COHORT, 'cohort_label': common_v2.COHORT_LABEL_V2,
                     'policy_backend': common.POLICY_BACKEND, 'policy_model': common.POLICY_MODEL, 'system_prompt_version': common_v2.SYSTEM_PROMPT_VERSION,
                     'freeze_id': manifest['freeze_id'], 'manifest': str(manifest_path), 'created_at_utc': now(), 'acknowledged_indices': sorted(acknowledged),
                     'formal_episodes_planned': len(jobs), 'jobs': jobs, 'automatic_retry': False}
        state.update(coordinator_pid=os.getpid(), maximum_simultaneous_episodes=args.workers)
        children, logs = {}, {}
        while True:
            active = []
            for number, job in enumerate(jobs):
                if job['status'] == 'DISPATCH_RESERVED':
                    job.update(status='UNRESOLVED_RESERVATION', reason='No durable PID after reservation; never assume no backend start')
                if job['status'] != 'RUNNING':
                    continue
                child = children.get(number)
                running = child.poll() is None if child else v2.alive(job)
                if running is True:
                    active.append(number); continue
                if running is None:
                    job.update(status='UNRESOLVED_PROCESS_OBSERVATION'); continue
                job['waited_returncode'] = child.returncode if child else None
                if child:
                    logs.pop(number).close()
                try:
                    base.collect(job, manifest)
                except Exception as error:
                    job.update(status='UNRESOLVED_RETURN', reason=type(error).__name__ + ': ' + str(error))
            unresolved = any(j['status'].startswith('UNRESOLVED') or (j.get('requires_pause') and i not in acknowledged) for i, j in enumerate(jobs))
            pause = unresolved or (output / 'PAUSE_REQUESTED').exists()
            pending = next((i for i, j in enumerate(jobs) if j['status'] == 'NOT_RUN'), None)
            if not active and (pending is None or pause):
                state['status'] = 'PAUSED_UNRESOLVED_OR_UNKNOWN' if unresolved else 'PAUSED' if pause else 'COMPLETE'; break
            if not pause and pending is not None and len(active) < args.workers:
                sample = base.resources(); state['last_resource_sample'] = {**sample, 'at_utc': now()}
                if sample['disk_available_GiB'] < 4 and not active:
                    state['status'] = 'PAUSED_STORAGE'; break
                if sample['busy_cores'] + 2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_available_GiB'] >= 4:
                    job = jobs[pending]
                    folder = output / ('%03d_%s_%s_%s' % (pending, job['task_id'], job['method'], job['trial_id']))
                    if folder.exists():
                        job['status'] = 'UNRESOLVED_EXISTING_DIRECTORY'; continue
                    folder.mkdir(); record = folder / 'client.json'
                    command = [sys.executable, str(v2.DRIVER), '--manifest', manifest['backend_manifest_path'], '--task', job['task_id'],
                               '--method', job['method'], '--trial', job['trial_id'], '--formal', '--dispatch-record', str(record)]
                    save(folder / 'reservation.json', {'cohort_id': COHORT, 'cohort_label': common_v2.COHORT_LABEL_V2, 'continuation': True, 'argv': command, 'reserved_at_utc': now()})
                    (folder / 'reservation.json').chmod(0o444)
                    job.update(status='DISPATCH_RESERVED', argv=command, dispatch_record=str(record), resources_before_launch=sample, continuation=True)
                    save(state_file, state)
                    log = (folder / 'runner.log').open('x')
                    try:
                        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                                 env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
                        job.update(status='RUNNING', pid=child.pid, started_at_utc=now()); children[pending] = child; logs[pending] = log
                    except Exception as error:
                        log.close(); job.update(status='UNRESOLVED_LAUNCH', reason=str(error))
            state.update(updated_at_utc=now(), jobs=jobs); save(state_file, state); base.index(output, jobs); time.sleep(5)
        state.update(updated_at_utc=now(), coordinator_pid=None, jobs=jobs); save(state_file, state); base.index(output, jobs)
        return {'cohort_label': common_v2.COHORT_LABEL_V2, 'status': state['status'], 'planned': len(jobs), 'recorded': sum(j['status'] == 'RECORDED' for j in jobs)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True); p.add_argument('--base', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--acknowledge', type=int, nargs='+', required=True, help='indices of the paused rows being acknowledged')
    p.add_argument('--reason', required=True); p.add_argument('--workers', type=int, choices=range(1, 5), default=4)
    print(json.dumps(run(p.parse_args())), flush=True)
