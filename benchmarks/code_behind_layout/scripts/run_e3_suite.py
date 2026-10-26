#!/usr/bin/env python3
"""Run one fixed E3 search part; test-oracle release is a separate operation."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e1_matched_runner import SSH, REMOTE
from scripts.e3_episode import verify
from scripts.run_e1_suite import resources
from src.e3_dispatch import PARTS, identity, plan


def now():
    return datetime.now(timezone.utc).isoformat()


def read(filename):
    return json.loads(Path(filename).read_text())


def save(filename, value):
    filename = Path(filename);temporary = filename.with_name(filename.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n');temporary.replace(filename)


def remote(code, payload, timeout=45):
    command = 'cd '+shlex.quote(REMOTE)+' && '+shlex.quote(REMOTE+'/runtime/GLdev/bin/python')+' -c '+shlex.quote(code)+' '+shlex.quote(json.dumps(payload))
    result = subprocess.run(SSH+[command], text=True, capture_output=True, check=True, timeout=timeout)
    return json.loads(result.stdout)


LOCAL_READY = '''import hashlib,json,sys,urllib.request
from pathlib import Path
args=json.loads(sys.argv[1]);root=Path.cwd();m=args['manifest'];name=Path(m['e4_methods_manifest']);name=name if name.is_absolute() else root/name
result={'ready':False,'status':'WAITING_FOR_FROZEN_E4_METHODS'}
try:
 if not name.is_file() or name.stat().st_mode&0o222:raise ValueError('Actual readonly E4 method freeze is absent')
 raw=name.read_bytes();methods=json.loads(raw);definition=methods['student_interface']
 if methods.get('status')!='FROZEN_E4_METHODS' or methods.get('formal_training_runs')!=12:raise ValueError('T1-T4 require12 actual trained runs')
 if methods.get('base_revision')!='381fc969f78efac66bc87ff7ddeadb7e73c218a7':raise ValueError('Wrong common base revision')
 if definition['max_context_tokens']!=m['budget']['maximum_context_tokens'] or definition['max_new_tokens']!=1024:raise ValueError('Actual GPT/local context differs')
 expected=hashlib.sha256(raw).hexdigest();known=args.get('known')
 if known:
  health=json.loads(Path(known['service_output'],'service.json').read_text())
  command=[x.decode() for x in Path('/proc/%d/cmdline'%known['pid']).read_bytes().split(b'\\0') if x]
  if command!=known['argv']:raise ValueError('Frozen service process identity changed')
 else:
  with urllib.request.urlopen('http://127.0.0.1:8117/health',timeout=5) as stream:health=json.load(stream)
 if health.get('status')!='READY' or health.get('phase')!='frozen_E4_policy_service' or health.get('native_tools')!=[]:raise ValueError('Actual8117service is not READY')
 if health.get('methods_manifest_sha256')!=expected or health.get('student_interface')!=definition:raise ValueError('READY service uses another frozen method/context')
 if health['settings']['maximum_context_tokens']!=m['budget']['maximum_context_tokens'] or health['settings']['max_new_tokens']!=1024:raise ValueError('Resident context/output differs')
 output=health['argv'][health['argv'].index('--output')+1]
 result={'ready':True,'status':'READY','methods_manifest_sha256':expected,'student_interface':definition,'pid':health['pid'],'argv':health['argv'],'service_output':output}
except Exception as error:result.update(reason=type(error).__name__+': '+str(error))
print(json.dumps(result))
'''


def local_ready(manifest, known=None):
    # One real loopback handshake establishes readiness. During inference the
    # single-request server can be busy; its exact process and live metadata are
    # checked without inserting health requests into the model queue.
    return remote(LOCAL_READY, {'manifest': manifest, 'known': known})


FIDELITY_READY = '''import json,sys
from pathlib import Path
m=json.loads(sys.argv[1]);name=Path(m['fidelity_manifest']);name=name if name.is_absolute() else Path.cwd()/name
result={'ready':False,'status':'WAITING_FOR_FROZEN_FIDELITY_METHOD'}
try:
 if not name.is_file() or name.stat().st_mode&0o222:raise ValueError('Readonly F3 method freeze is absent')
 f=json.loads(name.read_text())
 if f['status']!='FROZEN_E3_FIDELITY_METHOD' or f['formal_dispatch'] is not True or f['main_freeze_id']!=m['freeze_id']:raise ValueError('F3 method belongs to another/unfrozen main protocol')
 if f['budget']!=m['budget'] or f['risk_weights']!=m['risk_weights']:raise ValueError('F3 ablation changed the matched search budget/selector')
 expected={(task,str(trial)) for task in m['fidelity_task_ids'] for trial in range(1,6)}
 if len(f['search_plan'])!=10 or {(row['task_id'],str(row['trial_id'])) for row in f['search_plan']}!=expected:raise ValueError('F3 ten-search matrix differs')
 result={'ready':True,'status':'READY','backend_manifest_path':f['backend_manifest_path'],'fidelity_freeze_id':f['freeze_id']}
except Exception as error:result['reason']=type(error).__name__+': '+str(error)
print(json.dumps(result))
'''


def fidelity_ready(manifest):
    return remote(FIDELITY_READY, manifest)


INSTANCE_READY = '''import json,sys
from scripts.e3_episode import require_release
m=json.loads(sys.argv[1]);result={'ready':False,'status':'WAITING_FOR_SHARED_EVALUATION_RELEASE'}
try:
 release=require_release(m,baseline=True)
 if release is None:raise ValueError('Formal instance deployment requires the actual shared release')
 result={'ready':True,'status':'READY','freeze_id':release['freeze_id'],'original_baseline_plan':release['original_baseline_plan']}
except Exception as error:result['reason']=type(error).__name__+': '+str(error)
print(json.dumps(result))
'''


def instance_ready(manifest):
    return remote(INSTANCE_READY, manifest)


SEALED = '''import json,sys
from pathlib import Path
args=json.loads(sys.argv[1]);job=args['job'];client=args['client'];root=Path.cwd()
if job['part']=='instance':
 directory=Path(client['study_directory']).resolve();expected=root/'runs/formal/E3_instance'
else:
 directory=Path(client['episode_directory']).resolve();expected=root/'runs/formal/E3'
if directory.parent!=expected.resolve():raise ValueError('Backend directory is outside the actual E3 part')
private=directory/'private';value=json.loads((private/'state.json').read_text());task=json.loads((private/'task.json').read_text())
if value.get('formal_trial') is not True or task['task_id']!=job['task_id'] or str(value['trial_id'])!=job['trial_id']:raise ValueError('Backend source identity differs')
def source_proof(out,state):
 if not state.get('sealed') or state.get('in_flight'):raise ValueError('Source is unsealed or unresolved')
 revision=state['selected_revision'] if job['part']=='instance' else state['selection']['revision']
 folder=out/'private'/('revisions/%03d/source'%revision);paths=[folder/name for name in task['source_files']]
 if not all(path.is_file() and not path.is_symlink() for path in paths):raise ValueError('Selected full source is absent')
 return {'selected_revision':revision,'selected_source_files':len(paths),'selected_source_bytes':sum(path.stat().st_size for path in paths)}
if job['part']=='instance':
 if value.get('phase')!='formal_E3_I':raise ValueError('Actual instance phase differs')
 summary=json.loads((directory/'public/summary.json').read_text());order=json.loads((private/'arrival_order.json').read_text())
 if value['status']!='COMPLETE' or summary['status']!='COMPLETE' or value['current_arrival'] is not None or value['arrived']!=len(order):raise ValueError('Declared instance stream is not complete; remaining arrivals are NOT_RUN')
 for index in range(len(order)):
  arrival=private/('arrivals/%04d'%index);state=json.loads((arrival/'private/state.json').read_text())
  if not (arrival/'public/episode.json').is_file():raise ValueError('Instance deployment did not terminate')
  source_proof(arrival,state)
 result={'sealed':True,'study_directory':str(directory),'arrivals_completed':len(order),'phase':value['phase']}
else:
 search=json.loads((directory/'public/search.json').read_text())
 if value.get('phase')!=('formal_E3_P' if job['part']=='parameter' else 'formal_E3'):raise ValueError('Actual search phase differs')
 if value.get('post_freeze_started') is not False:raise ValueError('Search suite must not dispatch test-oracle evaluation')
 if value.get('policy_variant','GPT')!=job['policy_variant'] or value.get('evaluation_seed_slot')!=job['evaluation_seed_slot']:raise ValueError('Backend method/seed slot differs')
 if value.get('selector_variant','main')!=job.get('selector_variant','main'):raise ValueError('Backend signal ablation differs')
 if value.get('training_seed')!=(job['evaluation_seed_slot'] if job['policy_variant'] in ('T1','T2','T3','T4') else None):raise ValueError('Backend actual training seed differs')
 proof=source_proof(directory,value)
 result={'sealed':True,'episode_directory':str(directory),'search_status':search['status'],'phase':value['phase'],**proof}
print(json.dumps(result))
'''


def command(job, manifest, record):
    common = ['--manifest', manifest['backend_manifest_path'], '--task', job['task_id'],
        '--trial', job['trial_id'], '--formal', '--dispatch-record', str(record)]
    if job['part'] == 'instance':
        return [sys.executable, str(ROOT/'scripts/e3_instance_episode.py'), *common]
    if job['part'] == 'parameter':
        return [sys.executable, str(ROOT/'scripts/e3_parameter_episode.py'), *common,
            '--strategy', job['strategy'], '--selection-seed', str(job['selection_seed'])]
    if job['part'] == 'fidelity':
        return [sys.executable, str(ROOT/'scripts/e3_fidelity_episode.py'), *common, '--method', 'C',
            '--selection-seed', str(job['selection_seed']), '--variant', 'GPT', '--search-only']
    result = [sys.executable, str(ROOT/'scripts/e3_episode.py'), *common, '--method', job['method'],
        '--selection-seed', str(job['selection_seed']), '--variant', job['policy_variant'], '--search-only']
    if job['part'] == 'local':
        result += ['--training-seed', str(job['evaluation_seed_slot'])]
    if job['part'] == 'signals':
        result += ['--selector-variant', job['selector_variant']]
    return result


def validate_resume(state, frozen_plan):
    if state['plan_identity'] != frozen_plan['identity'] or len(state['jobs']) != len(frozen_plan['jobs']):
        raise ValueError('Resume requires the exact immutable E3 part/method freeze')
    for actual, expected in zip(state['jobs'], frozen_plan['jobs']):
        if any(actual.get(key) != value for key, value in expected.items() if key != 'status'):
            raise ValueError('A fixed E3 dispatch identity/order/selection seed changed')


def reserve(job, number, out, manifest, state_file, state, sample):
    folder = out/('%04d_%s' % (number, job['job_id']))
    if folder.exists():
        job.update(status='UNRESOLVED_EXISTING_RESERVATION', reason='Never launch an existing fixed job directory twice')
        save(state_file, state);return None
    folder.mkdir();record = folder/'client.json';argv = command(job, manifest, record)
    reservation = {'job_identity': list(identity(job)), 'argv': argv, 'dispatch_record': str(record),
        'reserved_at_utc': now(), 'resources_before_launch': sample}
    save(folder/'reservation.json', reservation);(folder/'reservation.json').chmod(0o444)
    job.update(status='DISPATCH_RESERVED', dispatch_record=str(record), argv=argv,
        reservation=str(folder/'reservation.json'), resources_before_launch=sample)
    save(state_file, state)  # durable before any child/backend/model start
    return folder


def process_alive(job):
    process = subprocess.run(['ps', '-p', str(job['pid']), '-o', 'command='], text=True, capture_output=True)
    if process.returncode and process.stderr.strip():
        return None
    return process.returncode == 0 and job['dispatch_record'] in process.stdout and Path(job['argv'][1]).name in process.stdout


def collect(job):
    record = Path(job['dispatch_record'])
    if not record.is_file():
        job.update(status='UNRESOLVED_NO_DISPATCH_RECORD', reason='No stdout inference or automatic new trial is allowed');return
    client = read(record)
    if ((client['task_id'], client['method'], str(client['trial_id']), client.get('policy_variant'), client.get('evaluation_seed_slot')) !=
            (job['task_id'], job['method'], job['trial_id'], job['policy_variant'], job['evaluation_seed_slot']) or client['formal'] is not True):
        raise ValueError('Child dispatch record differs from its fixed formal trial')
    if client.get('training_seed') != (job['evaluation_seed_slot'] if job['policy_variant'] in ('T1', 'T2', 'T3', 'T4') else None):
        raise ValueError('Child actual model-training seed differs from its evaluation slot')
    if client.get('selector_variant', 'main') != job.get('selector_variant', 'main'):
        raise ValueError('Child signal selector differs from the fixed ablation')
    job.update({key: client[key] for key in ('episode_directory', 'study_directory', 'local_output_directory') if key in client})
    filename = Path(client['local_output_directory'])/('summary.json' if job['part'] == 'instance' else 'search.json')
    if not filename.is_file():
        job.update(status='UNRESOLVED_NO_SEARCH_RECORD', reason='Real local search/stream summary is absent; raw retained');return
    row = read(filename)
    if (row['task_id'], row['method'], str(row['trial_id'])) != (job['task_id'], job['method'], job['trial_id']):
        raise ValueError('Local search identity differs from the fixed matrix')
    proof = remote(SEALED, {'job': job, 'client': client})
    if proof.get('sealed') is not True:
        raise ValueError('No actual sealed backend source was established')
    if job.get('waited_returncode') not in (None, 0):
        job.update(status='UNRESOLVED_CHILD_EXIT', sealed_backend=proof, reason='Child exited nonzero; do not silently relaunch');return
    storage = None
    if job['part'] != 'instance':
        argv = SSH+['cd '+shlex.quote(REMOTE)+' && '+shlex.quote(REMOTE+'/runtime/GLdev/bin/python')+
            ' scripts/archive_e3_evidence.py --sealed-search '+shlex.quote(job['episode_directory'])]
        stored = subprocess.run(argv, text=True, capture_output=True, check=True, timeout=120)
        storage = json.loads(stored.stdout)
        if storage['status'] != 'SEALED_E3_SEARCH_EVIDENCE_STORED' or storage['hidden_evaluation_dispatched'] is not False:
            raise ValueError('Sealed search evidence was not retained in a verified private archive')
    job.update(status='RECORDED', search_json=str(filename), search_status=row['status'], sealed_backend=proof,
        evidence_storage=storage, ended_at_utc=now())


def indices(out, jobs):
    index = [{key: job[key] for key in ('job_id', 'part', 'task_id', 'method', 'policy_variant', 'evaluation_seed_slot',
        'trial_id', 'selection_seed', 'selector_variant', 'execution_manifest', 'status', 'episode_directory', 'study_directory', 'local_output_directory',
        'search_json', 'search_status') if key in job} for job in jobs]
    save(out/'search_index.json', index)


def run(args):
    manifest_path = args.manifest.resolve();manifest = read(manifest_path);verify(manifest)
    jobs = plan(manifest, args.part)
    if not Path(manifest['backend_manifest_path']).is_absolute():
        raise ValueError('Freeze must identify its actual backend manifest')
    out = args.output.resolve();out.mkdir(parents=True, exist_ok=True)
    with (out/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        frozen_plan = {'identity': {'part': args.part, 'manifest': str(manifest_path), 'freeze_id': manifest['freeze_id'],
            'backend_manifest_path': manifest['backend_manifest_path'], 'source_revision': manifest['source_revision'],
            'implementation_sha256': manifest['implementation_sha256']}, 'jobs': jobs, 'automatic_retry': False}
        plan_file = out/'plan.json';state_file = out/'state.json'
        if plan_file.is_file():
            if read(plan_file) != frozen_plan or plan_file.stat().st_mode & 0o222:
                raise ValueError('Immutable dispatch plan differs or is writable')
        else:
            save(plan_file, frozen_plan);plan_file.chmod(0o444)
        if state_file.is_file():
            state = read(state_file);validate_resume(state, frozen_plan);jobs = state['jobs']
        else:
            state = {'status': 'RUNNING', 'plan_identity': frozen_plan['identity'], 'jobs': jobs,
                'created_at_utc': now(), 'declared_searches': len(jobs), 'automatic_retry': False,
                'hidden_evaluation_dispatched': False}
        # Finishing the collection of an already sealed trial is safe on resume;
        # it launches no model or physical execution and never replaces its ID.
        for job in jobs:
            if job['status'].startswith('UNRESOLVED') and job.get('waited_returncode') in (None, 0) and job.get('dispatch_record'):
                try:
                    collect(job)
                except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
                    job['reason'] = 'Retained reconciliation: '+type(error).__name__+': '+str(error)
        state.update(coordinator_pid=os.getpid(), maximum_simultaneous_episodes=args.workers,
            resource_rule='One2CPU physical worker per episode; new episode actualbusy+2<=24/RAMused<=190GiB/diskfree>=4GiB')
        children, logs, known_local = {}, {}, None
        while True:
            active = []
            for number, job in enumerate(jobs):
                if job['status'] == 'DISPATCH_RESERVED':
                    job.update(status='UNRESOLVED_DISPATCH_RESERVATION', reason='Interrupted before durable PID; never assume no backend start')
                if job['status'] != 'RUNNING':
                    continue
                child = children.get(number);alive = child.poll() is None if child else process_alive(job)
                if alive is True:
                    active.append(number);continue
                if alive is None:
                    job.update(status='UNRESOLVED_PROCESS_OBSERVATION', reason='Cannot establish whether the retained exact child is still running');continue
                job['waited_returncode'] = child.returncode if child else None
                if child:
                    logs.pop(number).close()
                try:
                    collect(job)
                except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
                    job.update(status='UNRESOLVED_COLLECTION', reason=type(error).__name__+': '+str(error))
            unresolved = any(job['status'].startswith('UNRESOLVED') for job in jobs)
            pending = next((i for i, job in enumerate(jobs) if job['status'] == 'NOT_RUN'), None)
            pause = unresolved or (out/'PAUSE_REQUESTED').is_file()
            if (pending is None or pause) and not active:
                state['status'] = 'PAUSED_UNRESOLVED' if unresolved else 'PAUSED' if pause else 'COMPLETED_SEARCH_PART'
                break
            if not pause and pending is not None and len(active) < args.workers:
                ready = True;effective_manifest = manifest
                if args.part == 'local':
                    try:
                        readiness = local_ready(manifest, known_local);state['local_method_readiness'] = {**readiness, 'checked_at_utc': now()}
                        ready = readiness['ready']
                        known_local = readiness if ready else None
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        ready = False;known_local = None
                        state['local_method_readiness'] = {'ready': False, 'status': 'WAITING', 'reason': str(error), 'checked_at_utc': now()}
                if args.part == 'fidelity':
                    try:
                        readiness = fidelity_ready(manifest);state['fidelity_method_readiness'] = {**readiness, 'checked_at_utc': now()}
                        ready = readiness['ready']
                        if ready:effective_manifest = {**manifest, 'backend_manifest_path': readiness['backend_manifest_path']}
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        ready = False;state['fidelity_method_readiness'] = {'ready': False, 'status': 'WAITING', 'reason': str(error)}
                if args.part == 'instance':
                    try:
                        readiness = instance_ready(manifest);state['instance_release_readiness'] = {**readiness, 'checked_at_utc': now()}
                        ready = readiness['ready']
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        ready = False;state['instance_release_readiness'] = {'ready': False, 'status': 'WAITING', 'reason': str(error)}
                if ready:
                    sample = resources();state['last_resource_sample'] = {**sample, 'at_utc': now()}
                    if sample['disk_available_GiB'] < 4 and not active:
                        state['status'] = 'PAUSED_STORAGE_CAPACITY';break
                    if sample['busy_cores']+2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_available_GiB'] >= 4:
                        job = jobs[pending];job['execution_manifest'] = effective_manifest['backend_manifest_path']
                        folder = reserve(job, pending, out, effective_manifest, state_file, state, sample)
                        if folder:
                            log = (folder/'runner.log').open('x')
                            try:
                                child = subprocess.Popen(job['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True, env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
                                job.update(status='RUNNING', pid=child.pid, started_at_utc=now())
                                state['status'] = 'RUNNING'
                                children[pending] = child;logs[pending] = log
                            except Exception as error:
                                log.close();job.update(status='UNRESOLVED_CHILD_LAUNCH', reason=type(error).__name__+': '+str(error))
                else:
                    state['status'] = ('WAITING_FOR_FROZEN_FIDELITY_METHOD' if args.part == 'fidelity'
                        else 'WAITING_FOR_SHARED_EVALUATION_RELEASE' if args.part == 'instance'
                        else 'WAITING_FOR_FROZEN_LOCAL_METHODS_AND_READY_MATCHED_CONTEXT')
            state.update(updated_at_utc=now(), jobs=jobs);save(state_file, state);indices(out, jobs)
            time.sleep(5)
        state.update(updated_at_utc=now(), coordinator_pid=None, jobs=jobs);save(state_file, state);indices(out, jobs)
        result = {'status': state['status'], 'part': args.part, 'declared_searches': len(jobs),
            'recorded_searches': sum(j['status'] == 'RECORDED' for j in jobs), 'output': str(out), 'hidden_calls': 0}
        print(json.dumps(result), flush=True)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--part', choices=PARTS, required=True)
    parser.add_argument('--manifest', type=Path, required=True);parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=range(1, 9), default=4);run(parser.parse_args())
