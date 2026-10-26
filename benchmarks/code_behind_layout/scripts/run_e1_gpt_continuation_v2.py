#!/usr/bin/env python3
"""Second acknowledgement continuation of the GPT action-level cohort (E1_scope_v2_16k).

The first continuation (scripts/run_e1_scope_continuation.py, output E1_scope_v2_16k_closed_unknowns_v1) was
paused by the operator on 2026-10-19 (provider usage limit) and resumed on 2026-10-21; its in-flight
episodes returned as transport unknowns and it paused under its own stopping rule. This controller mirrors
scripts/opus_cohort/run_e1c2_continuation.py for the GPT backend: the paused ledger is read, never written;
every unresolved or unknown row is acknowledged by explicit index and keeps its recorded status (no retry, no
relabel, no replacement identity); only rows that were never dispatched continue under the unchanged frozen
manifest, plan order, budgets and runner; any new unknown pauses dispatch again. The continuation state holds
all 360 identities so analysis reads one ledger.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_e1_scope_suite as original  # noqa: E402
from scripts.run_e1_scope_continuation import job_command, retain_new_unknown, identity, read  # noqa: E402
from scripts.e1_matched_runner import verify_implementation  # noqa: E402

now, save = original.now, original.save
DISCLOSURE = ('Post-observation administrative stopping-rule acknowledgement: the operator pause of 2026-10-19 (provider usage limit) '
              'left in-flight episodes whose transport returned unknown after resumption on 2026-10-21; those identities and the '
              'earlier acknowledged unknowns are retained with their recorded status and denominators, and only never-dispatched '
              'rows continue. Not a wholly blind original protocol.')


def unresolved_or_unknown(job):
    return job['status'].startswith('UNRESOLVED') or bool(job.get('requires_pause'))


def resolve_chain(base_dir):
    """Walk continuation_of links back to the first (frozen) continuation; return its original manifest and output plus every ledger directory in the chain."""
    chain = [base_dir]; st = read(base_dir / 'state.json')
    while 'continuation_freeze' not in st:
        prev = Path(st['continuation_of']); chain.append(prev); st = read(prev / 'state.json')
    declaration = read(Path(st['continuation_freeze']) / 'manifest.json')
    return Path(declaration['original_manifest']), Path(declaration['original_output']), chain


def run(args):
    base_dir = args.base.resolve(); base_state = read(base_dir / 'state.json')
    if base_state.get('coordinator_pid') is not None or not str(base_state.get('status', '')).startswith('PAUSED'):
        raise ValueError('The previous continuation must have drained and durably paused')
    manifest_path, original_output, chain = resolve_chain(base_dir); manifest = read(manifest_path)
    verify_implementation(manifest)
    expected = original.plan(manifest)
    jobs = copy.deepcopy(base_state['jobs'])
    if [identity(j) for j in jobs] != [identity(j) for j in expected] or len(jobs) != 360:
        raise ValueError('The paused ledger does not carry the original ordered 360 identities')
    acknowledged = [i for i, j in enumerate(jobs) if unresolved_or_unknown(j)]
    if sorted(acknowledged) != sorted(args.acknowledge):
        raise ValueError('Acknowledged indices differ from the unresolved/unknown rows: %s' % acknowledged)
    for i, j in enumerate(jobs):
        if i in acknowledged:
            continue
        if j['status'] == 'RECORDED':
            if j.get('post_freeze_status') != 'COMPLETE':
                raise ValueError('A recorded row that is not complete must be acknowledged explicitly: %d' % i)
        elif j['status'] != 'NOT_RUN' or any(k in j for k in ('pid', 'dispatch_record', 'started_at_utc')):
            raise ValueError('Only never-dispatched rows may continue: %d %s' % (i, j['status']))
    output = args.output.resolve()
    if output in (original_output, *chain) or any(d in output.parents for d in (original_output, *chain)):
        raise ValueError('Never write a paused ledger')
    output.mkdir(parents=True, exist_ok=True)
    held = [(d / 'coordinator.lock').open('r') for d in (original_output, *chain)]
    with (output / 'coordinator.lock').open('a') as lock:
        for h in held:
            fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = {'continuation_of': str(base_dir), 'original_output': str(original_output), 'original_manifest': str(manifest_path),
                'freeze_id': manifest['freeze_id'], 'cohort_id': base_state['cohort_id'], 'acknowledged_indices': sorted(acknowledged),
                'acknowledged': [{'index': i, 'identity': list(identity(jobs[i])), 'status': jobs[i]['status'],
                                  'post_freeze_status': jobs[i].get('post_freeze_status'), 'reason': jobs[i].get('reason')} for i in acknowledged],
                'reason': args.reason, 'protocol_disclosure': DISCLOSURE, 'jobs': [list(identity(j)) for j in jobs],
                'workers': args.workers, 'automatic_retry': False}
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
            state = {'status': 'RUNNING', 'continuation_of': str(base_dir), 'cohort_id': base_state['cohort_id'], 'freeze_id': manifest['freeze_id'],
                     'manifest': str(manifest_path), 'created_at_utc': now(), 'acknowledged_indices': sorted(acknowledged),
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
                running = child.poll() is None if child else original.alive(job)
                if running is True:
                    active.append(number); continue
                if running is None:
                    job.update(status='UNRESOLVED_PROCESS_OBSERVATION'); continue
                job['waited_returncode'] = child.returncode if child else None
                if child:
                    logs.pop(number).close()
                try:
                    original.collect(job, manifest)
                    retain_new_unknown(job, read(job['episode_json']))
                except Exception as error:
                    job.update(status='UNRESOLVED_RETURN', reason=type(error).__name__ + ': ' + str(error))
            new_pause = any(unresolved_or_unknown(j) and i not in acknowledged for i, j in enumerate(jobs))
            pause = new_pause or (output / 'PAUSE_REQUESTED').exists()
            pending = next((i for i, j in enumerate(jobs) if j['status'] == 'NOT_RUN'), None)
            if not active and (pending is None or pause):
                state['status'] = 'PAUSED_NEW_UNRESOLVED_OR_UNKNOWN' if new_pause else 'PAUSED' if pause else 'COMPLETE_CONTINUATION_UNKNOWNS_RETAINED'; break
            if not pause and pending is not None and len(active) < args.workers:
                sample = original.resources(); state['last_resource_sample'] = {**sample, 'at_utc': now()}
                if sample['disk_available_GiB'] < 4 and not active:
                    state['status'] = 'PAUSED_STORAGE'; break
                if sample['busy_cores'] + 2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_available_GiB'] >= 4:
                    job = jobs[pending]
                    name = '%03d_%s_%s_%s' % (pending, *identity(job))
                    if any((d / name).exists() for d in (output, original_output, *chain)):
                        job['status'] = 'UNRESOLVED_EXISTING_DIRECTORY'; continue
                    folder = output / name; folder.mkdir(); record = folder / 'client.json'
                    command = job_command(job, manifest['backend_manifest_path'], record)
                    save(folder / 'reservation.json', {'cohort_id': base_state['cohort_id'], 'continuation': output.name, 'argv': command, 'reserved_at_utc': now()})
                    (folder / 'reservation.json').chmod(0o444)
                    job.update(status='DISPATCH_RESERVED', argv=command, dispatch_record=str(record), resources_before_launch=sample, continuation=output.name)
                    save(state_file, state)
                    log = (folder / 'runner.log').open('x')
                    try:
                        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                                 env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
                        job.update(status='RUNNING', pid=child.pid, started_at_utc=now()); children[pending] = child; logs[pending] = log
                    except Exception as error:
                        log.close(); job.update(status='UNRESOLVED_LAUNCH', reason=str(error))
            state.update(updated_at_utc=now(), jobs=jobs); save(state_file, state); original.index(output, jobs); time.sleep(5)
        state.update(updated_at_utc=now(), coordinator_pid=None, jobs=jobs); save(state_file, state); original.index(output, jobs)
        return {'status': state['status'], 'planned': len(jobs), 'recorded': sum(j['status'] == 'RECORDED' for j in jobs),
                'acknowledged': sorted(acknowledged)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', type=Path, required=True, help='paused first-continuation output directory')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--acknowledge', type=int, nargs='+', required=True, help='indices of the unresolved/unknown rows being acknowledged')
    p.add_argument('--reason', required=True); p.add_argument('--workers', type=int, choices=range(1, 9), default=4)
    print(json.dumps(run(p.parse_args())), flush=True)
