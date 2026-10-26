#!/usr/bin/env python3
"""Trusted-server E3 post-release evaluation, baseline collection and joins.

No model is loaded or called. A durable episode reservation precedes the one
post-freeze gateway call. Interrupted or unknown execution stops new dispatch;
resume may collect an already returned report but never repeats physical work.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.archive_e3_evidence import archive_episode
from scripts.e3_episode import project, read, require_release, verify
from scripts.e3_original_baseline import collect as collect_baseline, join as join_baseline
from src.e3_dispatch import identity, plan

PARTS = ('gpt', 'parameter', 'local', 'signals', 'fidelity')
COUNTS = {'gpt': 480, 'parameter': 80, 'local': 1080, 'signals': 80, 'fidelity': 10}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(filename, value):
    filename = Path(filename);filename.parent.mkdir(parents=True, exist_ok=True)
    temporary = filename.with_name(filename.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n');temporary.replace(filename)


def released_plan(manifest_path):
    filename = project(manifest_path).resolve()
    if filename.is_symlink() or not filename.is_file() or filename.stat().st_mode & 0o222:
        raise ValueError('Evaluation requires the actual readonly main E3 freeze')
    manifest = read(filename)
    if manifest['status'] != 'FROZEN_E3' or manifest['formal_dispatch'] is not True:
        raise ValueError('No evaluation from a draft or non-E3 method')
    verify(manifest);release = require_release(manifest, baseline=True)
    released_file = project(manifest['hidden_release_file'])
    if released_file.is_symlink() or release['search_counts'] != COUNTS:
        raise ValueError('The actual global release must bind all1730 shared searches')
    expected = {identity(row): row for part in PARTS for row in plan(manifest, part)}
    rows, episodes = {}, set()
    for row in release['sealed_searches']:
        key = identity(row);episode = project(row['episode_directory']).resolve()
        if key not in expected or key in rows or episode in episodes:
            raise ValueError('Unknown, duplicate or multiply assigned released source')
        if row['selection_seed'] != expected[key]['selection_seed']:
            raise ValueError('A released configuration-selection seed changed')
        rows[key] = {**row, 'episode_directory': str(episode), 'status': 'NOT_EVALUATED'};episodes.add(episode)
    if set(rows) != set(expected) or len(rows) != 1730:
        raise ValueError('The immutable post-freeze plan has exactly1730 sealed searches')
    return filename, manifest, {'status': 'IMMUTABLE_E3_POST_RELEASE_PLAN',
        'manifest': str(filename), 'release': str(released_file.resolve()), 'freeze_id': manifest['freeze_id'],
        'declared_episodes': 1730, 'declared_selected_source_points': 43250,
        'declared_original_baseline_points': 600, 'automatic_physical_retries': False,
        'single_worker_CPUs': 2, 'jobs': [rows[identity(row)] for part in PARTS for row in plan(manifest, part)]}


def episode_context(job, manifest):
    out = project(job['episode_directory']).resolve();private = out/'private'
    if out.parent != (ROOT/'runs/formal/E3').resolve():
        raise ValueError('Released evaluation directory is outside formal E3')
    own = read(private/'manifest.json');state = read(private/'state.json');task = read(private/'task.json')
    expected = read(project(manifest['fidelity_manifest'])) if job['part'] == 'fidelity' else manifest
    if own != expected or not state.get('formal_trial') or not state.get('sealed') or state.get('in_flight'):
        raise ValueError('Actual source is unsealed, unresolved or from another freeze')
    if (task['task_id'] != job['task_id'] or str(state['trial_id']) != job['trial_id'] or
            state['selection']['revision'] != job['selected_revision'] or
            state.get('policy_variant', 'GPT') != job['policy_variant'] or
            state.get('evaluation_seed_slot') != job['evaluation_seed_slot'] or
            state.get('selector_variant', 'main') != job.get('selector_variant', 'main')):
        raise ValueError('Backend identity differs from the globally released source')
    if len(task['configurations']) != 25:
        raise ValueError('Each selected-source evaluation retains its full25-point domain')
    verify(own);require_release(own, out)
    return out, state


def invoke(job):
    if job['part'] == 'parameter':
        from scripts.e3_parameter_episode import backend
    elif job['part'] == 'fidelity':
        from scripts.e3_fidelity_episode import backend
    else:
        from scripts.e3_episode import backend
    # Each existing gateway owns its backend lock and performs the same actual
    # per-point two-CPU/resource/disk gate. No additional model/interface path.
    return backend({'op': 'post_freeze', 'episode_directory': job['episode_directory']})


def returned(job, manifest):
    out, state = episode_context(job, manifest);filename = out/'public/episode.json'
    if not filename.is_file():
        return False
    report = read(filename)
    if state.get('post_freeze_started') is not True or report['task_id'] != job['task_id']:
        raise ValueError('A public report does not establish an actual post-freeze return')
    if job['part'] == 'parameter':
        parameter = out/'public/parameter_episode.json'
        if not parameter.is_file():
            raise ValueError('P stopped before its actual parameter post-freeze report returned')
        if read(parameter)['hidden'] != {'declared': report['hidden_domain_size'],
                'known': report['hidden_domain_size']-report['hidden_incomplete'], 'S2_passed': report['hidden_S2_verified']}:
            raise ValueError('P post-freeze aggregate differs from its actual common evaluation')
    job.update(status='EVALUATED' if report['post_freeze_complete'] is True else 'PAUSED_UNKNOWN',
        report=str(filename), post_freeze_complete=report['post_freeze_complete'],
        hidden={'declared': 16, 'known': 16-report['hidden_incomplete'], 'S2_passed': report['hidden_S2_verified']},
        costs_by_stage=report.get('costs_by_stage'), returned_at_utc=now())
    job['evidence_archive'] = archive_episode(out)
    return True


def aggregate(state):
    counts = Counter(row['status'] for row in state['jobs'])
    return {'status': state['status'], 'freeze_id': state['freeze_id'], 'declared_episodes': 1730,
        'declared_selected_source_points': 43250, 'declared_original_baseline_points': 600,
        'episode_status_counts': dict(counts), 'new_model_calls': 0,
        'private_point_vectors_exported': False, 'automatic_physical_retries': False,
        'private_ledger': str(state['ledger']),
        'scope': 'One complete25-point pass per released source; interrupted/unknown sources never automatically repeat.'}


def post(manifest_path, output):
    filename, manifest, fixed = released_plan(manifest_path)
    output = Path(output).resolve()
    if output.is_relative_to(filename.parent):
        raise ValueError('Mutable evaluation records belong outside the method freeze')
    private = output/'private';private.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (private/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan_file = private/'plan.json';ledger = private/'state.json'
        if plan_file.is_file():
            if read(plan_file) != fixed or plan_file.stat().st_mode & 0o222:
                raise ValueError('The immutable post-release plan changed')
        else:
            save(plan_file, fixed);plan_file.chmod(0o444)
        state = read(ledger) if ledger.is_file() else {**fixed, 'ledger': str(ledger), 'status': 'RUNNING', 'created_at_utc': now()}
        if len(state['jobs']) != len(fixed['jobs']) or any(
                any(actual.get(key) != value for key, value in expected.items() if key != 'status')
                for actual, expected in zip(state['jobs'], fixed['jobs'])):
            raise ValueError('Mutable ledger differs from its immutable source/identity plan')
        for number, job in enumerate(state['jobs']):
            if job['status'] == 'EVALUATED':
                if not returned(job, manifest):raise ValueError('A previously returned physical report disappeared')
                continue
            if job['status'] != 'NOT_EVALUATED':
                # A process may have returned after its last ledger write. Read
                # that real report only; an absent return never opens a retry.
                try:
                    completed = returned(job, manifest)
                except Exception as error:
                    completed = False;job['reason'] = type(error).__name__+': '+str(error)
                if not completed or job['status'] != 'EVALUATED':
                    if not completed:
                        job.update(status='UNRESOLVED_PRIOR_DISPATCH', reason=job.get('reason',
                            'No actual returned episode record; this reserved source is never automatically evaluated again'))
                    state['status'] = 'PAUSED_UNRESOLVED_OR_UNKNOWN';break
                continue
            out, source_state = episode_context(job, manifest)
            if source_state.get('post_freeze_started') or (out/'public/episode.json').exists():
                job.update(status='UNRESOLVED_EXISTING_POST_FREEZE', reason='No automatic adoption of an unreserved physical invocation')
                state['status'] = 'PAUSED_UNRESOLVED_OR_UNKNOWN';break
            if shutil.disk_usage(ROOT).free < 4*1024**3:
                state['status'] = 'PAUSED_STORAGE_NO_NEW_DISPATCH';break
            reservation = private/'reservations'/('%04d.json' % number)
            if reservation.exists():
                job.update(status='UNRESOLVED_EXISTING_RESERVATION');state['status'] = 'PAUSED_UNRESOLVED_OR_UNKNOWN';break
            save(reservation, {'episode_directory': str(out), 'identity': list(identity(job)), 'created_at_utc': now(),
                'operation': 'post_freeze', 'actual_physical_phase': source_state['phase'], 'new_model_calls': 0})
            reservation.chmod(0o444)
            job.update(status='DISPATCH_RESERVED', reservation=str(reservation), started_at_utc=now())
            save(ledger, state)  # durable before any trusted gateway/EDA call
            try:
                invoke(job)
                if not returned(job, manifest):raise RuntimeError('Gateway returned without its real public episode record')
            except Exception as error:
                job.update(status='UNRESOLVED_EXECUTION', reason=type(error).__name__+': '+str(error))
            save(ledger, state)
            if job['status'] != 'EVALUATED':
                state['status'] = 'PAUSED_UNRESOLVED_OR_UNKNOWN';break
            if (output/'PAUSE_REQUESTED').exists():
                state['status'] = 'PAUSED_REQUESTED';break
        else:
            state['status'] = 'COMPLETE_SELECTED_SOURCE_EVALUATION'
        state['updated_at_utc'] = now();save(ledger, state)
        report = aggregate(state);save(output/'public/summary.json', report)
        return report


def baseline(manifest_path, output, evidence):
    released_plan(manifest_path)
    return collect_baseline(project(manifest_path), Path(output), [project(path) for path in evidence])


def joins(manifest_path, baseline_output, output):
    _, manifest, fixed = released_plan(manifest_path);output = Path(output).resolve()
    if output.is_relative_to(project(manifest_path).resolve().parent):
        raise ValueError('Derived join outputs belong outside the method freeze')
    with_output = [];missing = 0
    for number, job in enumerate(fixed['jobs']):
        directory, _ = episode_context(job, manifest)
        if not (directory/'public/episode.json').is_file():
            missing += 1;continue
        destination = output/'private/joins'/('%04d.json' % number)
        value = join_baseline(Path(baseline_output), directory, destination)
        with_output.append({'part': job['part'], 'task_id': job['task_id'], 'method': job['method'],
            'policy_variant': job['policy_variant'], 'selector_variant': job.get('selector_variant', 'main'),
            'evaluation_seed_slot': job['evaluation_seed_slot'], 'trial_id': job['trial_id'],
            'status': value['status'], 'regression_aggregate': str(destination)})
    save(output/'private/index.json', with_output)
    report = {'status': 'COMPLETE' if not missing and all(row['status'] == 'COMPLETE' for row in with_output) else 'INCOMPLETE_UNKNOWN',
        'declared_episodes': 1730, 'joined_episodes': len(with_output), 'not_evaluated_episodes': missing,
        'complete_regression_aggregates': sum(row['status'] == 'COMPLETE' for row in with_output),
        'new_physical_calls': 0, 'new_model_calls': 0, 'private_point_vectors_exported': False}
    save(output/'public/summary.json', report);return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('post', 'baseline', 'join'):
        p = sub.add_parser(name);p.add_argument('--manifest', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
        if name == 'baseline':p.add_argument('--anchor-evidence', type=Path, action='append', default=[])
        if name == 'join':p.add_argument('--baseline-output', type=Path, required=True)
    args = parser.parse_args()
    result = (post(args.manifest, args.output) if args.command == 'post' else
        baseline(args.manifest, args.output, args.anchor_evidence) if args.command == 'baseline' else
        joins(args.manifest, args.baseline_output, args.output))
    print(json.dumps(result, allow_nan=False), flush=True)
