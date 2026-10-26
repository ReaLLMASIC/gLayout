#!/usr/bin/env python3
"""Independent16k E1 scope cohort; original frozen E1 code stays unchanged."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
from scripts import e1_matched_runner as original
from scripts.prepare_e1_scope_cohort import BUDGET, COHORT
from src.model_adapter import GptDecisionAdapter, check_utc_budget

SSH = original.SSH[:-1]+['-o', 'ControlPath=/tmp/cbl-ssh-control']+original.SSH[-1:]


class CandidateActionError(ValueError):
    pass


def bad_patch_error(error):
    return (isinstance(error, subprocess.CalledProcessError) and
        error.cmd == ['git', 'apply', '--check', '--whitespace=nowarn', '-'] and
        isinstance(error.stderr, str) and re.fullmatch(r'error: corrupt patch at line [0-9]+\s*', error.stderr) is not None)


def now():return datetime.now(timezone.utc)
def read(filename):return json.loads(Path(filename).read_text())
def project(filename):return Path(filename) if Path(filename).is_absolute() else ROOT/filename
def save(filename, value):
    filename = Path(filename);temporary = filename.with_name(filename.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n');temporary.replace(filename)


def initialize(request):
    manifest = read(project(request['manifest']));formal = request.get('formal', False);pilot = request.get('interface_pilot', False)
    if (manifest.get('cohort_id') != COHORT or manifest['interface_version'] != COHORT or manifest['budget'] != BUDGET
            or manifest['visible_history_policy'] != 'current_source_and_feedback_v1'):
        raise ValueError('Only the separately declared matched16k scope cohort is accepted')
    if formal and (pilot or manifest['status'] != 'FROZEN_E1' or manifest['formal_dispatch'] is not True):
        raise ValueError('Formal scope trials require their actual independent freeze')
    if not formal and manifest['status'] not in ('DRAFT_E1_RUNNER', 'FROZEN_E1'):
        raise ValueError('Unknown scope preparation state')
    original.verify_implementation(manifest)
    ident, method, trial = request['task_id'], request['method'], str(request['trial_id'])
    if (ident not in manifest['task_ids'] or method not in ('G0', 'G1', 'G2') or
            not re.fullmatch('[A-Za-z0-9_-]+', trial) or formal and trial not in ('1', '2', '3', '4', '5')):
        raise ValueError('Task/method/trial outside the declared fresh cohort')
    packets = project(manifest['packet_root']);task = read(packets/'private'/ident/'task.json')
    packet = read(packets/'public'/ident/(method+'.json'))
    if (task.get('cohort_id') != COHORT or packet['documents'].get('cohort_id') != COHORT or
            packet['documents']['action_gateway']['read_source_paths'] != list(packet['visible_sources']) or
            formal and task.get('formal_admission') is not True):
        raise ValueError('Packet scope or physical admission differs')
    stamp = now().strftime('%Y%m%dT%H%M%S%fZ_')+uuid.uuid4().hex[:8]
    out = ROOT/('runs/formal/E1' if formal else 'runs/development/E1_scope')/stamp
    private = out/'private';private.mkdir(parents=True, mode=0o700);(out/'public').mkdir();(private/'current_source').mkdir()
    (private/'current_source/generator.py').write_text(packet['visible_sources']['generator.py'])
    deadline = now()+timedelta(seconds=BUDGET['wall_seconds']);packet['budget'] = {**BUDGET, 'deadline_utc': deadline.isoformat()}
    if pilot:packet['budget'].update(decisions=2, physical_evaluations=1)
    model = read(project(manifest['model_config']));model['visible_history_policy'] = manifest['visible_history_policy']
    if model['max_context_tokens'] != 16384 or model['max_new_tokens'] != 1024:raise ValueError('Model/packet budgets differ')
    for name, value in [('freeze_manifest', manifest), ('task', task), ('packet', packet), ('model_config', model)]:save(private/(name+'.json'), value)
    # Development qualification also records the actual backend code before
    # inference; a later commit cannot retroactively stand in for that source.
    prior = read(project(manifest['prior_interface_manifest'])) if manifest.get('prior_interface_manifest') else {'implementation_sha256': {}}
    names = sorted(set(manifest.get('implementation_sha256', prior['implementation_sha256']))|
        {'scripts/e1_scope_runner.py', 'scripts/prepare_e1_scope_cohort.py', 'scripts/e1_scope_proposal_preflight.py'})
    bindings = {}
    for name in names:
        filename = ROOT/name;destination = private/'execution_implementation'/name;destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(filename, destination);bindings[name] = hashlib.sha256(filename.read_bytes()).hexdigest()
    state = {'episode_id': stamp, 'task_id': ident, 'method': method, 'trial_id': trial,
        'stratum': task['stratum'], 'source_group': task['logical_group'], 'merged_source_group': task['merge_sensitivity_group'],
        'phase': 'formal_E1' if formal else 'development_E1_scope_policy_interface', 'driver_role': 'tested_policy',
        'cohort_id': COHORT, 'interface_version': COHORT, 'freeze_id': manifest.get('freeze_id'),
        'interface_pilot': pilot, 'execution_implementation_sha256': bindings,
        'status': 'RUNNING', 'created_at_utc': now().isoformat(), 'deadline_utc': deadline.isoformat(),
        'decisions': 0, 'selection_calls': 0, 'events': [], 'points': {}, 'sealed': False,
        'first_verified_times_seconds': {'S0': None, 'S1': None, 'S2': None},
        'costs_by_stage': {stage: {'physical_calls': 0, 'stage_wall_seconds': 0., 'waited_child_CPU_seconds': 0.,
            'missing_CPU_records': 0, 'capsule_preparation_wall_seconds': 0., 'capsule_preparation_CPU_seconds': 0.,
            'primitive_geometry_wall_seconds': 0., 'primitive_geometry_CPU_seconds': 0.,
            'primitive_geometry_is_subset_of_capsule_preparation': True} for stage in original.STAGES},
        'post_freeze_status': 'NOT_STARTED', 'hidden_started': False, 'formal_trial': formal}
    save(private/'state.json', state)
    return {'episode_directory': str(out), 'packet': packet, 'model_config': model,
        'implementation_sha256': bindings, 'cohort_id': COHORT}


class Backend(original.Backend):
    def action(self, action):
        try:return super().action(action)
        except subprocess.CalledProcessError as error:
            if action.get('action') == 'propose_patch' and bad_patch_error(error):
                raise CandidateActionError('candidate_bad_patch: '+error.stderr.strip()) from error
            raise

    def summary(self):
        return {**super().summary(), 'cohort_id': self.state['cohort_id'], 'interface_version': COHORT,
            'freeze_id': self.state['freeze_id'], 'interface_pilot': self.state['interface_pilot']}


def backend(request):
    if request['op'] == 'start':return initialize(request)
    if request['op'] == 'resources':
        def cpu():return [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
        before = cpu();time.sleep(1);after = cpu();delta = [b-a for a, b in zip(before, after)]
        memory = {line.split(':')[0]: int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()
            if line.startswith(('MemTotal:', 'MemAvailable:'))}
        disk = os.statvfs(ROOT)
        return {'busy_cores': os.cpu_count()*(1-(delta[3]+delta[4])/sum(delta)),
            'RAM_used_GiB': (memory['MemTotal']-memory['MemAvailable'])/2**30,
            'disk_available_GiB': disk.f_bavail*disk.f_frsize/2**30}
    directory = project(request['episode_directory'])
    with (directory/'private/backend.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX);gateway = Backend(directory)
        if gateway.state.get('cohort_id') != COHORT:raise ValueError('The old cohort cannot enter this gateway')
        original.verify_implementation({'status': 'FROZEN_E1', 'implementation_sha256': gateway.state['execution_implementation_sha256']})
        if request['op'] == 'current':return gateway.current()
        if request['op'] == 'action':return gateway.action(request['action'])
        if request['op'] == 'seal':return gateway.seal(request['status'], request.get('policy_statistics'))
        if request['op'] == 'post_freeze':
            if gateway.state['interface_pilot']:raise ValueError('The bounded interface pilot never opens a hidden oracle')
            return gateway.post_freeze(False)
        raise ValueError('Unknown scope gateway operation')


def transport(request):
    command = SSH+['cd '+shlex.quote(original.REMOTE)+' && '+shlex.quote(original.REMOTE+'/runtime/GLdev/bin/python')+' scripts/e1_scope_runner.py --backend']
    process = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True)
    if process.returncode:raise original.BackendInfrastructureError(process.stderr[-1500:])
    result = json.loads(process.stdout)
    if result.get('error'):
        kind = {'TimeoutError': TimeoutError, 'ValueError': ValueError, 'CandidateActionError': CandidateActionError}.get(result['error_type'], original.BackendInfrastructureError)
        raise kind(result['error'])
    return result['result']


def resources():return transport({'op': 'resources'})


def run_policy(args):
    from transformers import AutoTokenizer
    initialized = transport({'op': 'start', 'manifest': args.manifest, 'task_id': args.task, 'method': args.method,
        'trial_id': str(args.trial), 'formal': args.formal, 'interface_pilot': args.pilot})
    directory = initialized['episode_directory'];packet = initialized['packet']
    out = ROOT/('runs/formal/E1_scope_policy' if args.formal else 'runs/development/E1_scope_policy')/Path(directory).name;out.mkdir(parents=True)
    save(out/'backend.json', {'episode_directory': directory, 'cohort_id': COHORT})
    if args.dispatch_record:save(args.dispatch_record, {'episode_directory': directory, 'local_output_directory': str(out),
        'task_id': args.task, 'method': args.method, 'trial_id': str(args.trial), 'formal': args.formal, 'cohort_id': COHORT})
    frozen = {'status': 'FROZEN_E1', 'implementation_sha256': initialized['implementation_sha256']}
    original.verify_implementation(frozen)
    tokenizer = AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer', local_files_only=True, trust_remote_code=False)
    adapter = GptDecisionAdapter(out/'decisions', tokenizer=tokenizer);session = adapter.start(packet, initialized['model_config'])
    observation = {'status': 'initial'};status = 'DECISION_BUDGET_EXHAUSTED'
    try:
        for index in range(packet['budget']['decisions']):
            original.verify_implementation(frozen);check_utc_budget(packet)
            current = transport({'op': 'current', 'episode_directory': directory})
            action = adapter.step(session, observation, current_sources=current['current_sources']);check_utc_budget(packet)
            try:observation = transport({'op': 'action', 'episode_directory': directory, 'action': action})
            except CandidateActionError:raise
            except ValueError as error:observation = {'error': type(error).__name__+': '+str(error)}
            save(out/'latest_observation.json', observation)
            if action['action'] == 'finish':status = 'SEARCH_FINISHED';break
            if args.pilot and action['action'] == 'request_evaluation':
                rows = [value for value in observation.values() if isinstance(value, dict)]
                status = ('BUDGET_EXHAUSTED' if any(value.get('failure_class') == 'budget' for value in rows)
                    else 'INCOMPLETE_UNKNOWN' if any(value.get('complete') is False for value in rows) else 'SEARCH_FINISHED')
                break
            if any(isinstance(value, dict) and value.get('execution_integrity') == 'incomplete' for value in observation.values()):
                status = 'INCOMPLETE_UNKNOWN';break
    except TimeoutError:status = 'BUDGET_EXHAUSTED'
    except CandidateActionError as error:
        status = 'MODEL_FAILED';save(out/'policy_error.json', {'failure_class': 'candidate_invalid_action', 'error': str(error)})
    except original.BackendInfrastructureError as error:
        status = 'INCOMPLETE_UNKNOWN';save(out/'backend_error.json', {'error': str(error)})
    except Exception as error:
        status = 'MODEL_FAILED';save(out/'policy_error.json', {'error': type(error).__name__+': '+str(error)})
    finally:
        session['closed'] = True;save(out/'session.json', session)
        report = transport({'op': 'seal', 'episode_directory': directory, 'status': status,
            'policy_statistics': original.policy_statistics(session, out)});save(out/'search_report.json', report)
    if not args.pilot:
        report = transport({'op': 'post_freeze', 'episode_directory': directory});save(out/'episode.json', report)
    print(json.dumps({'cohort_id': COHORT, 'episode_directory': directory, 'local_output_directory': str(out),
        'status': report['status'], 'pilot': args.pilot, 'hidden_calls': 0 if args.pilot else None}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--backend', action='store_true')
    p.add_argument('--manifest');p.add_argument('--task');p.add_argument('--method', choices=['G0', 'G1', 'G2'])
    p.add_argument('--trial', default='development');p.add_argument('--formal', action='store_true');p.add_argument('--pilot', action='store_true')
    p.add_argument('--dispatch-record', type=Path);a = p.parse_args()
    if a.backend:
        try:print(json.dumps({'result': backend(json.load(sys.stdin))}), flush=True)
        except Exception as error:print(json.dumps({'error': str(error), 'error_type': type(error).__name__}), flush=True)
    else:
        if not a.manifest or not a.task or not a.method:p.error('Manifest/task/method required')
        if a.formal and a.pilot:p.error('Development pilot cannot be formal')
        run_policy(a)
