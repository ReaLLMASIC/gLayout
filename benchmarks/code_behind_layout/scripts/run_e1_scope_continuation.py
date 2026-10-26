#!/usr/bin/env python3
"""One fixed acknowledgement of two closed E1 unknowns; never retry an episode."""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_e1_scope_suite as original
from scripts.e1_matched_runner import verify_implementation

STATUS = 'FROZEN_E1_CONTINUATION_CLOSED_UNKNOWNS_ACKNOWLEDGEMENT'
ACKS = {14: ('draft_E1_five_t_s01', 'G2', '4'),
    28: ('draft_E1_five_t_s02', 'G2', '2')}
PREFIX = 34
WORKERS = 4
SELF = 'scripts/run_e1_scope_continuation.py'


def read(path):
    return json.loads(Path(path).read_text())


def identity(job):
    return job['task_id'], job['method'], str(job['trial_id'])


def validate_base_jobs(jobs, expected):
    keys = [identity(j) for j in jobs]
    if len(jobs) != 360 or len(set(keys)) != 360 or keys != [identity(j) for j in expected]:
        raise ValueError('The original ordered360 identities must be exact and unique')
    if any(identity(jobs[i]) != ident for i, ident in ACKS.items()):
        raise ValueError('Only the explicitly named old indices14 and28 may be acknowledged')
    for number, job in enumerate(jobs):
        if number < PREFIX:
            if job['status'] != 'RECORDED':
                raise ValueError('Every original first34 row must remain recorded')
            if number == 14:
                if job.get('post_freeze_status') != 'INCOMPLETE_UNKNOWN' or job.get('requires_pause') is not True:
                    raise ValueError('Old14 must remain the actual unknown, without relabeling')
            elif job.get('requires_pause') or job.get('post_freeze_status') != 'COMPLETE':
                raise ValueError('No other old unknown is acknowledged')
        elif job['status'] != 'NOT_RUN' or any(k in job for k in ('pid', 'dispatch_record', 'started_at_utc')):
            raise ValueError('Only original never-dispatched rows34..359 may be continued')


def needs_pause(jobs):
    return any(j['status'].startswith('UNRESOLVED') or
        (j.get('requires_pause') and i not in ACKS) for i, j in enumerate(jobs))


def retain_new_unknown(job, report):
    if (report.get('post_freeze_status') == 'INCOMPLETE_UNKNOWN' or
            report.get('status') == 'INCOMPLETE_UNKNOWN' or
            report.get('analysis_search_status') == 'INFRASTRUCTURE_PAUSED'):
        job.update(requires_pause=True,
            continuation_pause_reason='A new actual search/post-freeze unknown is not acknowledged')


def verify_old_bindings(folder, declaration):
    for binding in declaration['unchanged_old_files']:
        if Path(binding['original']).read_bytes() != (folder / binding['snapshot']).read_bytes():
            raise ValueError('An original paused ledger/report changed: '+binding['original'])
    manifest = read(declaration['original_manifest'])
    verify_implementation(manifest)
    if len(manifest['implementation_sha256']) != 29 or SELF in manifest['implementation_sha256']:
        raise ValueError('Use the unchanged original29 implementation, plus a separate controller')
    base = read(folder/'original_state.json')
    validate_old_reports(base['jobs'], [read(folder/('original_reports/%03d.json' % i)) for i in range(PREFIX)], manifest)
    return manifest


def validate_old_reports(jobs, reports, manifest):
    unknown = set()
    if len(reports) != PREFIX:
        raise ValueError('All original34 sealed reports are required')
    for i, row in enumerate(reports):
        if (not row.get('sealed') or row.get('freeze_id') != manifest['freeze_id'] or
                row.get('cohort_id') != manifest['cohort_id'] or identity(row) != identity(jobs[i])):
            raise ValueError('Old recorded source/report is not sealed under this exact freeze')
        if (row.get('post_freeze_status') == 'INCOMPLETE_UNKNOWN' or
                row.get('status') == 'INCOMPLETE_UNKNOWN' or
                row.get('analysis_search_status') == 'INFRASTRUCTURE_PAUSED'):
            unknown.add(i)
    if unknown != set(ACKS):
        raise ValueError('Actual old search/post-freeze unknowns must be exactly14 and28: '+str(sorted(unknown)))


def require_readonly(folder):
    for path in [folder, *folder.rglob('*')]:
        if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != (0o555 if path.is_dir() else 0o444):
            raise ValueError('Frozen continuation bundle must have files444 and directories555')


def prepare(args):
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    state_path = args.state.resolve()
    state = read(state_path)
    manifest_path = Path(state['manifest'])
    manifest = read(manifest_path)
    expected = original.plan(manifest)
    validate_base_jobs(state['jobs'], expected)
    if state['status'] != 'PAUSED_UNRESOLVED_OR_UNKNOWN' or state.get('coordinator_pid') is not None:
        raise ValueError('The original coordinator must have drained and durably paused')
    declaration = {'status': 'DRAFT_E1_CONTINUATION_NO_DISPATCH',
        'original_freeze_id': manifest['freeze_id'], 'original_manifest': str(manifest_path),
        'original_output': str(state_path.parent), 'original_cohort_id': state['cohort_id'],
        'created_at_utc': original.now(), 'unchanged_old_files': [],
        'acknowledgements': [{'original_index': i, 'identity': list(ident),
            'reason': ('Original SS transient reached the unchanged90s analysis wall limit; no completed same-configuration gold establishes a candidate numerical failure.' if i == 14 else
                'Candidate patch check command failed under original error classification, later diagnostic complete; original unknown retained.'),
            'result_stays_unknown': True, 'repeated_or_replaced': False} for i, ident in ACKS.items()],
        'continuation_indices': list(range(PREFIX, 360)), 'ordered_identities': [list(identity(j)) for j in expected],
        'workers': WORKERS, 'new_unknown_rule': 'Pause new dispatch and drain every active episode; only old indices14 and28 are acknowledged.',
        'protocol_disclosure': 'Post-observation administrative stopping-rule acknowledgement; not a wholly blind original protocol.',
        'analysis_rule': 'Keep all360 denominators and original unknown/costs; original paired/hidden completeness gates remain. No imputed zero or replacement trial.',
        'model_or_EDA_calls_in_prepare': 0}
    files = [(manifest_path, 'original_manifest.json'), (state_path, 'original_state.json'),
        (state_path.parent/'plan.json', 'original_plan.json'),
        (state_path.parent/'episode_index.jsonl', 'original_episode_index.jsonl')]
    reports = [read(j['episode_json']) for j in state['jobs'][:PREFIX]]
    validate_old_reports(state['jobs'], reports, manifest)
    for i, job in enumerate(state['jobs'][:PREFIX]):
        report = Path(job['episode_json'])
        files.append((report, 'original_reports/%03d.json' % i))
    for source, relative in files:
        target = folder/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o444)
        declaration['unchanged_old_files'].append({'original': str(source), 'snapshot': relative})
    verify_old_bindings(folder, declaration)
    original.save(folder/'manifest.json', declaration)
    return {'status': declaration['status'], 'manifest': str(folder/'manifest.json'), 'old_recorded': PREFIX, 'new_dispatch_maximum': 326}


def verify(folder):
    require_readonly(folder)
    declaration = read(folder/'manifest.json')
    if declaration['status'] != STATUS or [(a['original_index'], tuple(a['identity'])) for a in declaration['acknowledgements']] != list(ACKS.items()):
        raise ValueError('An explicit independent continuation freeze is required')
    if hashlib.sha256((ROOT/SELF).read_bytes()).hexdigest() != declaration['controller_sha256']:
        raise ValueError('The separately frozen controller changed')
    manifest = verify_old_bindings(folder, declaration)
    base = read(folder/'original_state.json')
    validate_base_jobs(base['jobs'], original.plan(manifest))
    if (declaration['continuation_indices'] != list(range(PREFIX, 360)) or
            declaration['ordered_identities'] != [list(identity(j)) for j in base['jobs']] or
            declaration['workers'] != WORKERS):
        raise ValueError('Continuation identity/order or acknowledgement changed')
    return declaration, base, manifest


def freeze(args):
    draft = args.draft.resolve()
    declaration = read(draft/'manifest.json')
    if declaration['status'] != 'DRAFT_E1_CONTINUATION_NO_DISPATCH':
        raise ValueError('Freeze only the reviewed unexecuted draft')
    verify_old_bindings(draft, declaration)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    committed = subprocess.check_output(['git', 'show', revision+':'+SELF], cwd=ROOT)
    if committed != (ROOT/SELF).read_bytes():
        raise ValueError('Commit this exact controller before freezing it')
    output = args.output.resolve()
    shutil.copytree(draft, output)
    declaration.update(status=STATUS, frozen_at_utc=original.now(), source_revision=revision,
        controller_sha256=hashlib.sha256(committed).hexdigest())
    original.save(output/'manifest.json', declaration)
    for path in output.rglob('*'):
        if path.is_file():
            path.chmod(0o444)
    for path in sorted([p for p in output.rglob('*') if p.is_dir()], key=lambda p:len(p.parts), reverse=True):
        path.chmod(0o555)
    output.chmod(0o555)
    verify(output)
    return {'status': STATUS, 'manifest': str(output/'manifest.json'), 'new_dispatch_maximum': 326}


def job_command(job, backend_manifest, record):
    return [sys.executable, str(ROOT/'scripts/e1_scope_runner.py'), '--manifest', backend_manifest,
        '--task', job['task_id'], '--method', job['method'], '--trial', str(job['trial_id']),
        '--formal', '--dispatch-record', str(record)]


def run(args):
    folder = args.freeze.resolve()
    declaration, base, manifest = verify(folder)
    output = args.output.resolve()
    if output == Path(declaration['original_output']) or Path(declaration['original_output']) in output.parents:
        raise ValueError('Never write the original paused coordinator state')
    output.mkdir(parents=True, exist_ok=True)
    with (Path(declaration['original_output'])/'coordinator.lock').open('r') as old_lock, (output/'coordinator.lock').open('a') as lock:
        fcntl.flock(old_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_file = output/'state.json'
        if state_file.exists():
            state = read(state_file)
            if state['continuation_freeze'] != str(folder) or state['jobs'][:PREFIX] != base['jobs'][:PREFIX]:
                raise ValueError('Existing continuation belongs to another old ledger')
            jobs = state['jobs']
        else:
            jobs = copy.deepcopy(base['jobs'])
            state = {'status': 'RUNNING', 'continuation_freeze': str(folder), 'created_at_utc': original.now(),
                'cohort_id': base['cohort_id'], 'freeze_id': base['freeze_id'], 'jobs': jobs,
                'original_recorded_preserved': PREFIX, 'new_dispatch_maximum': 326, 'automatic_retry': False}
        if [identity(j) for j in jobs] != [identity(j) for j in base['jobs']]:
            raise ValueError('An existing/duplicate identity cannot enter the continued matrix')
        children, logs = {}, {}
        state['coordinator_pid'] = os.getpid()
        while True:
            verify(folder)
            active = []
            for number, job in enumerate(jobs[PREFIX:], PREFIX):
                if job['status'] == 'DISPATCH_RESERVED':
                    job.update(status='UNRESOLVED_RESERVATION', reason='A reserved identity is never automatically repeated')
                if job['status'] != 'RUNNING':
                    continue
                child = children.get(number)
                running = child.poll() is None if child else original.alive(job)
                if running is True:
                    active.append(number)
                    continue
                if running is None:
                    job['status'] = 'UNRESOLVED_PROCESS_OBSERVATION'
                    continue
                job['waited_returncode'] = child.returncode if child else None
                if child:
                    logs.pop(number).close()
                try:
                    original.collect(job, manifest)
                    retain_new_unknown(job, read(job['episode_json']))
                except Exception as error:
                    job.update(status='UNRESOLVED_RETURN', reason=type(error).__name__+': '+str(error))
            pause = needs_pause(jobs) or (output/'PAUSE_REQUESTED').exists()
            pending = next((i for i in range(PREFIX, 360) if jobs[i]['status'] == 'NOT_RUN'), None)
            if not active and (pending is None or pause):
                state['status'] = 'PAUSED_NEW_UNRESOLVED_OR_UNKNOWN' if needs_pause(jobs) else 'PAUSED' if pause else 'COMPLETE_CONTINUATION_ORIGINAL_UNKNOWNS_RETAINED'
                break
            if not pause and pending is not None and len(active) < WORKERS:
                sample = original.resources()
                state['last_resource_sample'] = {**sample, 'at_utc': original.now()}
                if sample['disk_available_GiB'] < 4 and not active:
                    state['status'] = 'PAUSED_STORAGE'
                    break
                if sample['busy_cores']+2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_available_GiB'] >= 4:
                    job = jobs[pending]
                    target = output/('%03d_%s_%s_%s' % (pending, *identity(job)))
                    original_target = Path(declaration['original_output'])/target.name
                    if target.exists() or original_target.exists():
                        job['status'] = 'UNRESOLVED_EXISTING_DIRECTORY'
                        continue
                    target.mkdir()
                    record = target/'client.json'
                    command = job_command(job, manifest['backend_manifest_path'], record)
                    original.save(target/'reservation.json', {'cohort_id': base['cohort_id'], 'argv': command, 'reserved_at_utc': original.now()})
                    (target/'reservation.json').chmod(0o444)
                    job.update(status='DISPATCH_RESERVED', argv=command, dispatch_record=str(record), resources_before_launch=sample)
                    original.save(state_file, state)
                    log = (target/'runner.log').open('x')
                    try:
                        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                            env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
                        job.update(status='RUNNING', pid=child.pid, started_at_utc=original.now())
                        children[pending], logs[pending] = child, log
                    except Exception as error:
                        log.close()
                        job.update(status='UNRESOLVED_LAUNCH', reason=str(error))
            state.update(updated_at_utc=original.now(), jobs=jobs)
            original.save(state_file, state)
            original.index(output, jobs)
            time.sleep(5)
        state.update(updated_at_utc=original.now(), coordinator_pid=None, jobs=jobs)
        original.save(state_file, state)
        original.index(output, jobs)
    return {'status': state['status'], 'planned_total': 360, 'recorded_total': sum(j['status'] == 'RECORDED' for j in jobs), 'original_unknowns_preserved': [14, 28]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('prepare');p.add_argument('--state', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('freeze');p.add_argument('--draft', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('verify');p.add_argument('--freeze', type=Path, required=True)
    p = sub.add_parser('run');p.add_argument('--freeze', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'verify':
        verify(args.freeze.resolve())
        result = {'status': 'VERIFIED_NO_DISPATCH'}
    else:
        result = {'prepare': prepare, 'freeze': freeze, 'run': run}[args.mode](args)
    print(json.dumps(result), flush=True)
