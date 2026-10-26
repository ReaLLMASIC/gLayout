"""Finite local20-search FVF dispatcher; no hidden/model replacement calls.

Ordinary GPT uses the already frozen GptDecisionAdapter. Two FVF episodes may
run concurrently; the separate teacher transport gate is neither changed nor
claimed to gate ordinary CLI calls. Output plan/reservations survive restarts.
"""
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import fvf_supplement_episode as policy
from scripts.e1_scope_runner import resources


def now():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(Path(path).read_text())
def save(path,value):
    p=Path(path);temporary=p.with_name(p.name+'.pending')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n');temporary.replace(p)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan(manifest,workers):
    if workers not in (1,2):raise ValueError('The FVF supplement has at most two concurrent episodes')
    if (manifest.get('cohort_id')!=policy.COHORT or manifest.get('status') not in (policy.FROZEN,policy.DRAFT)
            or manifest.get('budget')!=policy.BUDGET or manifest.get('search_plan')!=policy.matrix()):
        raise ValueError('Use the exact one-task20-search independent FVF matrix/budgets')
    backend=Path(manifest['manifest_path'])
    if not backend.is_absolute():raise ValueError('Actual private endpoint manifest must be absolute')
    return [{**row,'cohort_id':policy.COHORT,'status':'NOT_RUN'} for row in manifest['search_plan']]


def command(job,manifest,record):
    return [sys.executable,str(ROOT/'scripts/fvf_supplement_episode.py'),
        '--manifest',manifest['manifest_path'],'--method',job['method'],'--trial',job['trial_id'],
        '--formal','--dispatch-record',str(record)]


def identity(manifest_path,manifest):
    return {'cohort_id':policy.COHORT,'freeze_id':manifest.get('freeze_id'),
        'manifest_path':str(Path(manifest_path).resolve()),'local_manifest_sha256':sha(manifest_path),
        'backend_manifest_path':manifest['manifest_path'],'source_revision':manifest.get('source_revision'),
        'implementation_sha256':manifest['implementation_sha256'],
        'coordinator_sha256':sha(Path(__file__)),
        'resource_reader_sha256':sha(ROOT/'scripts/e1_scope_runner.py')}


def check_only(args):
    manifest=read(args.manifest);jobs=plan(manifest,args.workers)
    policy.main.verify({'status':'FROZEN_E3','implementation_sha256':manifest['implementation_sha256']})
    ready=manifest['status']==policy.FROZEN and manifest.get('formal_dispatch') is True
    return {'status':'READY_FIXED_FVF20_SOFTWARE_CHECK' if ready else 'DRAFT_MATRIX_ONLY_NOT_READY',
        'cohort_id':policy.COHORT,'declared_searches':len(jobs),'maximum_simultaneous_episodes':args.workers,
        'methods':list(policy.METHODS),'trials':5,'search_UTC_seconds_per_episode':policy.BUDGET['wall_seconds'],
        'immutable_backend_manifest':manifest['manifest_path'],'initial_state_count':1,
        'ordinary_GPT':'Existing frozen GptDecisionAdapter, not teacher transport',
        'physical_or_model_calls':0,'remote_calls':0,'reservations_created':0,'hidden_calls':0,
        'maximum_dispatch_window_seconds':20*policy.BUDGET['wall_seconds'],
        'source_binding':identity(args.manifest,manifest)}


def reserve(job,number,out,manifest,state,persist,sample):
    folder=out/('%02d_%s_t%s'%(number,job['method'],job['trial_id']))
    if folder.exists():
        job.update(status='UNRESOLVED_EXISTING_RESERVATION',reason='Never replace an existing trial directory');persist();return None
    folder.mkdir();record=folder/'dispatch.json';argv=command(job,manifest,record)
    reservation={'task_id':job['task_id'],'method':job['method'],'trial_id':job['trial_id'],
        'selection_seed':job['selection_seed'],'cohort_id':policy.COHORT,'argv':argv,'dispatch_record':str(record),
        'reserved_at_utc':now(),'resources_before_launch':sample}
    save(folder/'reservation.json',reservation);(folder/'reservation.json').chmod(0o444)
    job.update(status='RESERVED',argv=argv,dispatch_record=str(record),reservation=str(folder/'reservation.json'))
    persist()  # before any client/backend/model process can start
    return folder


SEALED='''import json,sys,hashlib
from pathlib import Path
from scripts import fvf_supplement_episode as f
p=json.loads(sys.argv[1]);m=f.verify_manifest(p['manifest'],formal=True)
out=Path(p['episode_directory']).resolve()
if out.parent!=(f.ROOT/'runs/formal/E3_FVF_supplement').resolve():raise ValueError('Wrong private cohort directory')
if f.read(out/'private/manifest.json')!=m or f.read(out/'private/task.json')!=f.read(m['task']):raise ValueError('Search used another frozen task')
v=f.read(out/'private/state.json');r=f.read(out/'public/search.json');job=p['job']
if (v['phase']!='formal_E3_FVF_supplement' or v['method']!=job['method'] or v['trial_id']!=job['trial_id'] or v['seed']!=job['selection_seed']):raise ValueError('Wrong formal search identity')
if hashlib.sha256((out/'public/search.json').read_bytes()).hexdigest()!=p['local_search_sha256']:raise ValueError('Local report differs from actual backend report')
proof=f.source_proof(out)
print(json.dumps({'sealed':True,'search_status':r['status'],'phase':v['phase'],**proof}))
'''


def backend_proof(manifest,job,client,report_file):
    payload={'manifest':manifest['manifest_path'],'job':{k:job[k] for k in ('method','trial_id','selection_seed')},
        'episode_directory':client['episode_directory'],'local_search_sha256':sha(report_file)}
    code='cd '+shlex.quote(policy.main.REMOTE)+' && '+shlex.quote(policy.main.REMOTE+'/runtime/GLdev/bin/python')+' -c '+shlex.quote(SEALED)+' '+shlex.quote(json.dumps(payload))
    run=subprocess.run(policy.SSH+[code],text=True,capture_output=True,check=True,timeout=45)
    return json.loads(run.stdout)


def collect(job,manifest):
    path=Path(job['dispatch_record'])
    if not path.is_file():raise ValueError('No durable client dispatch record; stdout is not completion')
    client=read(path)
    expected=(job['task_id'],job['method'],job['trial_id'],policy.COHORT,True)
    actual=tuple(client.get(k) for k in ('task_id','method','trial_id','cohort_id','formal'))
    if actual!=expected:raise ValueError('Client identity differs from fixed formal matrix')
    job.update(episode_directory=client['episode_directory'],local_output_directory=client['local_output_directory'])
    report_file=Path(client['local_output_directory'])/'search.json'
    if not report_file.is_file():raise ValueError('No real local sealed search report')
    report=read(report_file)
    if (report['task_id'],report['method'],str(report['trial_id']),report['cohort_id'])!=expected[:4]:
        raise ValueError('Wrong local sealed report')
    proof=backend_proof(manifest,job,client,report_file)
    if proof.get('sealed') is not True:raise ValueError('Actual private source is unsealed')
    if job.get('waited_returncode') not in (None,0):raise ValueError('Nonzero child exit; retain source without replacing trial')
    job.update(status='RECORDED',search_status=report['status'],search_json=str(report_file),
        sealed_backend=proof,ended_at_utc=now())
    # A sealed numerical/model unknown is retained as unknown, never success or
    # a circuit failure. It may not dispatch its own hidden evaluation. A truly
    # unresolved source halts new suite dispatch instead.


def process_alive(job):
    r=subprocess.run(['ps','-p',str(job['pid']),'-o','command='],text=True,capture_output=True)
    if r.returncode and r.stderr.strip():return None
    return r.returncode==0 and 'fvf_supplement_episode.py' in r.stdout and job['dispatch_record'] in r.stdout


def run(args):
    began,parent_cpu=time.monotonic(),time.process_time()
    manifest=read(args.manifest);jobs=plan(manifest,args.workers)
    if manifest['status']!=policy.FROZEN or manifest.get('formal_dispatch') is not True:
        raise ValueError('DRAFT never dispatches formal searches')
    policy.main.verify({'status':'FROZEN_E3','implementation_sha256':manifest['implementation_sha256']})
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    with (out/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        frozen={'identity':identity(args.manifest,manifest),'jobs':jobs,'maximum_simultaneous_episodes':args.workers,
            'automatic_retry':False,'hidden_calls':0,'fixed_order':'Declared trial1..5, A/R/B/C order',
            'maximum_dispatch_window_seconds':20*policy.BUDGET['wall_seconds']}
        if (out/'plan.json').exists():
            if read(out/'plan.json')!=frozen or (out/'plan.json').stat().st_mode&0o222:raise ValueError('Immutable plan or coordinator changed')
        else:save(out/'plan.json',frozen);(out/'plan.json').chmod(0o444)
        if (out/'state.json').exists():
            state=read(out/'state.json')
            if state['identity']!=frozen['identity'] or len(state['jobs'])!=20:raise ValueError('Wrong resumable cohort')
            for actual,expected in zip(state['jobs'],jobs):
                if any(actual.get(k)!=v for k,v in expected.items() if k!='status'):raise ValueError('Trial identity/order changed')
            jobs=state['jobs']
        else:state={'identity':frozen['identity'],'jobs':jobs,'created_at_utc':now(),'status':'RUNNING','automatic_retry':False,'hidden_calls':0}
        state['coordinator_pid']=os.getpid();children={};logs={}
        invocation={'started_at_utc':now(),'PID':os.getpid(),'resource_checks':0,
            'blocked_resource_checks':0,'resource_observation_wall_seconds':0.,'remote_resource_reader_CPU_seconds':None}
        state.setdefault('coordinator_invocations',[]).append(invocation)
        def persist():
            invocation.update(wall_seconds=time.monotonic()-began,Mac_parent_CPU_seconds=time.process_time()-parent_cpu,
                CPU_scope='Actual coordinator parent only; SSH/network wall is not CPU')
            state.update(jobs=jobs,updated_at_utc=now());save(out/'state.json',state)
            recorded=[{k:j[k] for k in ('task_id','method','trial_id','selection_seed','status','search_status','episode_directory','local_output_directory','search_json') if k in j} for j in jobs if j['status']=='RECORDED']
            save(out/'search_index.json',{'cohort_id':policy.COHORT,'declared_searches':20,'searches':recorded,'matrix':jobs,'hidden_calls':0})
        for job in jobs:
            if job['status'].startswith('UNRESOLVED') and job.get('dispatch_record'):
                if job.get('pid') and process_alive(job) is not False:continue
                try:
                    old=job['status'];collect(job,manifest);job['reconciled_from_status']=old
                except (ValueError,KeyError,OSError,subprocess.SubprocessError) as error:
                    job['reconciliation_error']=str(error)
        while True:
            active=[];overrun=False
            for i,job in enumerate(jobs):
                if job['status']=='RESERVED':job.update(status='UNRESOLVED_RESERVED_WITHOUT_PID',reason='No automatic relaunch after reservation')
                if job['status']!='RUNNING':continue
                child=children.get(i);alive=child.poll() is None if child else process_alive(job)
                if alive is None:job.update(status='UNRESOLVED_PROCESS_OBSERVATION');continue
                if alive:
                    if time.time()-job['started_epoch']>policy.BUDGET['wall_seconds']+1800:
                        job.update(status='UNRESOLVED_CHILD_OVERRUN',reason='Own child exceeded search plus transport/seal grace; retained PID/argv, no replacement or hidden');overrun=True
                    else:active.append(i)
                    continue
                if child:job['waited_returncode']=child.returncode;logs.pop(i).close()
                try:collect(job,manifest)
                except (ValueError,KeyError,OSError,subprocess.SubprocessError) as error:
                    job.update(status='UNRESOLVED_COLLECTION',reason=type(error).__name__+': '+str(error))
            unresolved=any(j['status'].startswith('UNRESOLVED') for j in jobs)
            pending=next((i for i,j in enumerate(jobs) if j['status']=='NOT_RUN'),None)
            elapsed=time.time()-datetime.fromisoformat(state['created_at_utc']).timestamp()
            expired=elapsed>=frozen['maximum_dispatch_window_seconds']
            pause=(out/'PAUSE_REQUESTED').exists()
            if overrun or ((unresolved or pause or expired or pending is None) and not active):
                state['status']='PAUSED_UNRESOLVED' if unresolved else 'PAUSE_REQUESTED' if pause else 'DISPATCH_WINDOW_EXHAUSTED' if expired else 'COMPLETED_FIXED20_SEARCHES'
                break
            if not(unresolved or pause or expired) and pending is not None and len(active)<args.workers:
                try:
                    measured=time.monotonic();sample=resources()
                    invocation['resource_observation_wall_seconds']+=time.monotonic()-measured
                    invocation['resource_checks']+=1;state['last_resource_sample']={**sample,'at_utc':now()}
                    allowed=sample['busy_cores']+2<=24 and sample['RAM_used_GiB']<=190 and sample['disk_available_GiB']>=4
                    if not allowed:invocation['blocked_resource_checks']+=1
                    if sample['disk_available_GiB']<4 and not active:state['status']='PAUSED_STORAGE_CAPACITY';break
                    if allowed:
                        job=jobs[pending];folder=reserve(job,pending,out,manifest,state,persist,sample)
                        if folder:
                            log=(folder/'runner.log').open('x')
                            try:
                                child=subprocess.Popen(job['argv'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
                                    env={**os.environ,'TOKENIZERS_PARALLELISM':'false','OMP_NUM_THREADS':'1'})
                                job.update(status='RUNNING',pid=child.pid,started_at_utc=now(),started_epoch=time.time())
                                children[pending]=child;logs[pending]=log;persist()
                            except Exception as error:
                                log.close();job.update(status='UNRESOLVED_CHILD_START',reason=type(error).__name__+': '+str(error))
                    state['status']='RUNNING' if allowed else 'WAITING_RESOURCE_GATE'
                except (ValueError,OSError,subprocess.SubprocessError) as error:
                    state['status']='WAITING_RESOURCE_OBSERVATION';state['last_resource_error']=str(error)
            persist();time.sleep(5)
        state['coordinator_pid']=None;persist()
        return {'status':state['status'],'cohort_id':policy.COHORT,'declared_searches':20,
            'recorded_searches':sum(j['status']=='RECORDED' for j in jobs),'hidden_calls':0,'output':str(out)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path);p.add_argument('--workers',type=int,choices=[1,2],default=2)
    p.add_argument('--check-only',action='store_true');a=p.parse_args()
    if not a.check_only and not a.output:p.error('A dedicated fixed-cohort output is required')
    print(json.dumps(check_only(a) if a.check_only else run(a),indent=2,allow_nan=False),flush=True)
