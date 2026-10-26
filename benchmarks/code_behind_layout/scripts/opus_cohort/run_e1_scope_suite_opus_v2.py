#!/usr/bin/env python3
"""Fresh Minimum-tier E1-C2 matrix (24 tasks x G0/G1/G2 x 2 trials) on the amended Claude cohort freeze.

Mirrors run_e1_scope_suite_opus.py with the E1-C2 plan, driver and labels; collection, archive and
index helpers of the frozen suite are reused unchanged.
"""
import argparse
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
from scripts import run_e1_scope_suite as base  # noqa: E402
from scripts.prepare_e1_scope_cohort import COHORT, read  # noqa: E402

DRIVER = ROOT / 'scripts/opus_cohort/e1_scope_runner_opus_v2.py'
now, save = base.now, base.save


def alive(job):
    result = subprocess.run(['ps', '-p', str(job['pid']), '-o', 'command='], text=True, capture_output=True)
    if result.returncode and result.stderr.strip():
        return None
    return result.returncode == 0 and DRIVER.name in result.stdout and job['dispatch_record'] in result.stdout


def run(args):
    manifest_path = args.manifest.resolve()
    manifest = read(manifest_path)
    jobs = common_v2.claude_e1_plan_v2(manifest)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        expected = {'cohort_id': COHORT, 'cohort_label': common_v2.COHORT_LABEL_V2, 'policy_backend': common.POLICY_BACKEND,
                    'policy_model': common.POLICY_MODEL, 'system_prompt_version': common_v2.SYSTEM_PROMPT_VERSION,
                    'freeze_id': manifest['freeze_id'], 'manifest': str(manifest_path),
                    'backend_manifest': manifest['backend_manifest_path'], 'jobs': jobs, 'automatic_retry': False}
        plan_file, state_file = output / 'plan.json', output / 'state.json'
        if plan_file.exists():
            if read(plan_file) != expected or plan_file.stat().st_mode & 0o222:
                raise ValueError('A fresh cohort plan cannot change or import old trials')
        else:
            save(plan_file, expected)
            plan_file.chmod(0o444)
        if state_file.exists():
            state = read(state_file)
            if (state.get('cohort_id') != COHORT or state['freeze_id'] != manifest['freeze_id'] or state['manifest'] != str(manifest_path)
                    or [(j['task_id'], j['method'], j['trial_id']) for j in state['jobs']] != [(j['task_id'], j['method'], j['trial_id']) for j in jobs]):
                raise ValueError('Resume must use the same complete independent cohort matrix')
            jobs = state['jobs']
        else:
            state = {'status': 'RUNNING', 'cohort_id': COHORT, 'cohort_label': common_v2.COHORT_LABEL_V2,
                     'policy_backend': common.POLICY_BACKEND, 'policy_model': common.POLICY_MODEL,
                     'system_prompt_version': common_v2.SYSTEM_PROMPT_VERSION,
                     'freeze_id': manifest['freeze_id'], 'manifest': str(manifest_path), 'created_at_utc': now(),
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
                running = child.poll() is None if child else alive(job)
                if running is True:
                    active.append(number)
                    continue
                if running is None:
                    job.update(status='UNRESOLVED_PROCESS_OBSERVATION')
                    continue
                job['waited_returncode'] = child.returncode if child else None
                if child:
                    logs.pop(number).close()
                try:
                    base.collect(job, manifest)
                except Exception as error:
                    job.update(status='UNRESOLVED_RETURN', reason=type(error).__name__ + ': ' + str(error))
            unresolved = any(j['status'].startswith('UNRESOLVED') or j.get('requires_pause') for j in jobs)
            pause = unresolved or (output / 'PAUSE_REQUESTED').exists()
            pending = next((i for i, j in enumerate(jobs) if j['status'] == 'NOT_RUN'), None)
            if not active and (pending is None or pause):
                state['status'] = 'PAUSED_UNRESOLVED_OR_UNKNOWN' if unresolved else 'PAUSED' if pause else 'COMPLETE'
                break
            if not pause and pending is not None and len(active) < args.workers:
                sample = base.resources()
                state['last_resource_sample'] = {**sample, 'at_utc': now()}
                if sample['disk_available_GiB'] < 4 and not active:
                    state['status'] = 'PAUSED_STORAGE'
                    break
                if sample['busy_cores'] + 2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_available_GiB'] >= 4:
                    job = jobs[pending]
                    folder = output / ('%03d_%s_%s_%s' % (pending, job['task_id'], job['method'], job['trial_id']))
                    if folder.exists():
                        job['status'] = 'UNRESOLVED_EXISTING_DIRECTORY'
                        continue
                    folder.mkdir()
                    record = folder / 'client.json'
                    command = [sys.executable, str(DRIVER), '--manifest', manifest['backend_manifest_path'], '--task', job['task_id'],
                               '--method', job['method'], '--trial', job['trial_id'], '--formal', '--dispatch-record', str(record)]
                    save(folder / 'reservation.json', {'cohort_id': COHORT, 'cohort_label': common_v2.COHORT_LABEL_V2,
                                                       'argv': command, 'reserved_at_utc': now()})
                    (folder / 'reservation.json').chmod(0o444)
                    job.update(status='DISPATCH_RESERVED', argv=command, dispatch_record=str(record), resources_before_launch=sample)
                    save(state_file, state)
                    log = (folder / 'runner.log').open('x')
                    try:
                        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                                 env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
                        job.update(status='RUNNING', pid=child.pid, started_at_utc=now())
                        children[pending] = child
                        logs[pending] = log
                    except Exception as error:
                        log.close()
                        job.update(status='UNRESOLVED_LAUNCH', reason=str(error))
            state.update(updated_at_utc=now(), jobs=jobs)
            save(state_file, state)
            base.index(output, jobs)
            time.sleep(5)
        state.update(updated_at_utc=now(), coordinator_pid=None, jobs=jobs)
        save(state_file, state)
        base.index(output, jobs)
        return {'cohort_id': COHORT, 'cohort_label': common_v2.COHORT_LABEL_V2, 'status': state['status'],
                'planned': len(jobs), 'recorded': sum(j['status'] == 'RECORDED' for j in jobs)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workers', type=int, choices=range(1, 5), default=4)
    print(json.dumps(run(p.parse_args())), flush=True)
