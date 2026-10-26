"""Dispatch authorized collection stages; preserve existing collectors and raw plans."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_frozen_training_collection import load_definition as load
PLANNING_COLLECTIONS=[c+'_planning_trajectories_context_v2' for c in ('c01','c02','c05','c07')]


def now():return datetime.now(timezone.utc).isoformat()


def existing_collector(root,identifier):
    """Find only an exact already-running collector for this immutable manifest."""
    manifest=str(root/'runtime/train_collections'/identifier/'collection.json')
    matches=[]
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:argv=[value.decode() for value in path.read_bytes().split(b'\0') if value]
        except (OSError,UnicodeDecodeError):continue
        if len(argv)==5 and Path(argv[1]).name in ['collect_training.py','run_frozen_training_collection.py'] and argv[2:]==['--manifest',manifest,'--execute']:
            matches.append({'pid':int(path.parent.name),'argv':argv})
    if len(matches)>1:raise ValueError('Multiple collectors already own '+identifier)
    return matches[0] if matches else None


def planning_workers(root):
    """The new fixed batch has at most two one-worker collectors at once."""
    active=[]
    for identifier in PLANNING_COLLECTIONS:
        owner=existing_collector(root,identifier)
        if owner:
            data=json.loads((root/'runtime/train_collections'/identifier/'collection.json').read_text())
            if data['physical']['workers']!=1:raise ValueError('The fixed planning batch must have one physical worker per collection')
            active.append({'collection':identifier,'physical_workers':1,'owner':owner})
    return active


def resource_sample():
    def cpu():
        fields=[int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
        return sum(fields),fields[3]+fields[4]
    first=cpu();time.sleep(1);second=cpu();total=second[0]-first[0]
    busy=(1-(second[1]-first[1])/total)*os.cpu_count() if total else float(os.cpu_count())
    memory={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))}
    return {'sampled_at_utc':now(),'logical_cores':os.cpu_count(),'actual_busy_cores':busy,'available_cores':os.cpu_count()-busy,
            'RAM_used_GiB':(memory['MemTotal']-memory['MemAvailable'])/1024**3,'available_disk_GiB':shutil.disk_usage(ROOT).free/1024**3}


def run(args):
    out=ROOT/'runs/train_collection_queues'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
    lanes={'GPT':{'predecessor':'c01_gpt_teacher_v1','collections':['c01_failure_minimal_gpt_teacher_v1','c05_minimal_gpt_teacher_v1','c08_minimal_gpt_teacher_v1']},
           'T0':{'predecessor':'c01_collection_v2','collections':['c05_collection_v1','c08_collection_v1']}}
    if args.include_action_teacher or args.include_c07_action or args.overlap_teacher_stages or args.include_planning_trajectories:
        # Adopt the last actually dispatched collection without restarting any
        # child. New collections are appended in the authorized fixed order.
        exists=lambda name:(ROOT/'runs/train_collection'/name).exists()
        ordered=['c05_minimal_gpt_teacher_v1','c01_planning_action_gpt_teacher_v1','c08_minimal_gpt_teacher_v1']
        if args.include_c07_action:ordered.append('c07_action_v1')
        if args.overlap_teacher_stages:ordered=['c05_minimal_gpt_teacher_v1','c01_planning_action_gpt_teacher_v1','c07_action_v1','c08_minimal_gpt_teacher_v1']
        if args.include_natural_c05_action:ordered.append('c05_natural_action_teacher_v1')
        if args.include_trajectory_c02:ordered+=['c01_enumeration_action_v1','c01_natural_action_repair_v1','c02_action_v1']
        dispatched=[index for index,name in enumerate(ordered) if exists(name)]
        if not dispatched:raise ValueError('Expected the acknowledged running C05 source-teacher boundary')
        latest=max(dispatched)
        lanes['GPT']={'predecessor':ordered[latest],'collections':ordered[latest+1:]}
        if exists('c08_collection_v1'):lanes['T0']={'predecessor':'c08_collection_v1','collections':[]}
        elif exists('c05_collection_v1'):lanes['T0']={'predecessor':'c05_collection_v1','collections':['c08_collection_v1']}
    if args.include_planning_trajectories:
        lanes['PLANNING']={'predecessor':None,'collections':PLANNING_COLLECTIONS}
    for lane in lanes.values():
        for name in ([lane['predecessor']] if lane['predecessor'] else [])+lane['collections']:load(ROOT/'runtime/train_collections'/name/'collection.json')
    state={'status':'RUNNING','started_at_utc':now(),'pid':os.getpid(),'maximum_dispatch_hours':args.max_hours,
        'schedule':lanes,'jobs':[],'events':[],'constraints':'Each lane serial; GPT global broker2slots; do not alter running jobs. Dispatch only with >=2 actual free cores and <=190GiB RAM used.'}
    lock=threading.Lock();deadline=time.monotonic()+args.max_hours*3600
    def event(lane,kind,**values):
        with lock:
            state['events'].append({'at_utc':now(),'lane':lane,'event':kind,**values})
            (out/'queue.json').write_text(json.dumps(state,indent=2)+'\n')
        print(json.dumps({'lane':lane,'event':kind,**values}),flush=True)
    def wait_collection(lane,name):
        path=ROOT/'runs/train_collection'/name/'completion.json';event(lane,'WAITING_FOR_COMPLETION',collection=name)
        while True:
            if path.exists():
                completion=json.loads(path.read_text())
                if completion.get('status')=='COMPLETED_INITIAL_BATCH':event(lane,'PREDECESSOR_COMPLETED',collection=name);return
                if completion.get('status')=='EARLY_TERMINATED_AFTER_COMPLETED_INITIAL_STATE_FOR_STUDENT_INTERFACE_BUDGET':
                    event(lane,'PREDECESSOR_AUTHORIZED_EARLY_TERMINATION',collection=name,
                          original_planned_attempts=completion['original_planned_attempts'],actual_proposals=completion['actual_proposals'],
                          remaining_not_run=completion['remaining_not_run']);return
                raise RuntimeError(name+' is paused/failed: '+str(completion.get('status')))
            raw=path.parent
            if raw.exists() and existing_collector(ROOT,name) is None:
                event(lane,'LANE_PAUSED_UNKNOWN',collection=name,raw_output=str(raw),missing_terminal_record=str(path),
                    reason='Existing predecessor has no exact live collector and no terminal record; never redispatch or infer completion')
                raise RuntimeError('Exited predecessor has unknown terminal state; retain original raw records: '+str(raw))
            if time.monotonic()>=deadline:raise TimeoutError('Queue dispatch deadline reached while waiting for '+name)
            time.sleep(15)
    def launch(lane,identifier):
        manifest=ROOT/'runtime/train_collections'/identifier/'collection.json';data,_,_,_=load(manifest)
        required=data['physical']['workers']*data['physical']['cpus_per_job']
        while time.monotonic()<deadline:
            if identifier in PLANNING_COLLECTIONS:
                active=planning_workers(ROOT)
                if len(active)>=2:
                    event(lane,'WAITING_FOR_FIXED_PLANNING_BATCH_WORKER_CAP',collection=identifier,active=active,maximum=2)
                    time.sleep(15);continue
            sample=resource_sample()
            if sample['actual_busy_cores']+required<=24 and sample['RAM_used_GiB']<=190 and sample['available_disk_GiB']>=4:break
            event(lane,'WAITING_FOR_ACTUAL_RESOURCES',collection=identifier,resources=sample,required_physical_CPU_limit=required);time.sleep(15)
        else:raise TimeoutError('Queue dispatch deadline reached before '+identifier)
        existing=Path(data['output_root'])
        if existing.exists():raise RuntimeError('Existing collection output requires reconciliation; never launch a duplicate: '+identifier)
        entry='run_frozen_training_collection.py' if data.get('frozen_collector_entrypoint') else 'collect_training.py'
        command=[str(ROOT/'runtime/training-venv/bin/python'),str(ROOT/'scripts'/entry),'--manifest',str(manifest),'--execute']
        log=out/(identifier+'.log')
        with log.open('w') as stream:
            process=subprocess.Popen(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'2','TOKENIZERS_PARALLELISM':'false'})
        job={'lane':lane,'collection':identifier,'pid':process.pid,'argv':command,'started_at_utc':now(),'log':str(log),'resource_sample_before_launch':sample,'status':'RUNNING','frozen_physical_workers':data['physical']['workers']}
        with lock:state['jobs'].append(job)
        event(lane,'COLLECTION_STARTED',collection=identifier,pid=process.pid,resources=sample)
        return process,job
    def wait_requests(lane,name):
        root=ROOT/'runs/train_collection'/name
        event(lane,'WAITING_FOR_EIGHT_REQUEST_RETURNS',collection=name)
        while time.monotonic()<deadline:
            path=root/'attempts.json'
            attempts=json.loads(path.read_text()) if path.exists() else []
            if len(attempts)>=8:
                event(lane,'EIGHT_REQUESTS_RETURNED_EDA_MAY_CONTINUE',collection=name,returned_attempts=len(attempts),
                    actual_inference_ids=len({a['inference_id'] for a in attempts if a.get('inference_id')}));return
            complete=root/'completion.json'
            if complete.exists() and json.loads(complete.read_text()).get('status')!='COMPLETED_INITIAL_BATCH':
                raise RuntimeError('Collection stopped before its eight request returns: '+name)
            time.sleep(3)
        raise TimeoutError('Queue dispatch deadline waiting for inference phase '+name)
    def overlap_gpt():
        try:
            import urllib.request
            with urllib.request.urlopen('http://127.0.0.1:8116/transport-health',timeout=10) as response:transport=json.load(response)
            if transport.get('global_teacher_slots')!=2:raise ValueError('Stage overlap requires the actual shared two-slot source/ACTION transport')
            event('GPT','SHARED_TWO_SLOT_TRANSPORT_VERIFIED',transport={key:transport[key] for key in ['global_teacher_slots','listeners','active_forwards','peak_concurrent_forwards']})
            wait_requests('GPT','c05_minimal_gpt_teacher_v1')
            ordered=['c01_planning_action_gpt_teacher_v1','c07_action_v1','c08_minimal_gpt_teacher_v1']
            if args.include_natural_c05_action:ordered.append('c05_natural_action_teacher_v1')
            if args.include_trajectory_c02:ordered+=['c01_enumeration_action_v1','c01_natural_action_repair_v1','c02_action_v1']
            for name in ordered:
                existing=ROOT/'runs/train_collection'/name
                if existing.exists():
                    owner=existing_collector(ROOT,name)
                    if not owner and not (existing/'completion.json').exists():
                        raise RuntimeError('Existing output has no live owner or terminal record: '+name)
                    event('GPT','EXISTING_COLLECTOR_ADOPTED_WITHOUT_RESTART',collection=name,owner=owner)
                else:launch('GPT',name)
                # Prospective collections have independent frozen contexts.
                # Prepare their baselines concurrently; whichever becomes
                # ready uses the unchanged shared two-slot GPT transport.
            for name in ordered:wait_requests('GPT',name)
            # EDA collectors keep their complete planned denominators. Nothing
            # is cancelled when the next model stage is dispatched.
            for name in ['c05_minimal_gpt_teacher_v1']+ordered:
                path=ROOT/'runs/train_collection'/name/'completion.json'
                while not path.exists():
                    if time.monotonic()>=deadline:raise TimeoutError('Queue monitoring deadline; collector remains running: '+name)
                    if not existing_collector(ROOT,name):raise RuntimeError('Collector exited without terminal record: '+name)
                    time.sleep(10)
                completion=json.loads(path.read_text())
                event('GPT','COLLECTION_TERMINAL_RECORD_RETAINED',collection=name,completion=completion)
                if completion.get('status')!='COMPLETED_INITIAL_BATCH':
                    event('GPT','PAUSED_COLLECTION_RETAINED_WITHOUT_CANCELLING_OTHER_COLLECTIONS',collection=name,status=completion.get('status'))
            event('GPT','LANE_COMPLETED')
        except Exception as exc:event('GPT','LANE_PAUSED',reason=type(exc).__name__+': '+str(exc))
    def lane(name,plan):
        try:
            wait_collection(name,plan['predecessor'])
            for identifier in plan['collections']:
                process,job=launch(name,identifier)
                while process.poll() is None:time.sleep(10)
                job.update(status='PROCESS_EXITED',returncode=process.returncode,ended_at_utc=now())
                event(name,'COLLECTION_PROCESS_EXITED',collection=identifier,returncode=process.returncode)
                if process.returncode:raise RuntimeError('Collection failed; raw retained: '+identifier)
                wait_collection(name,identifier)
            event(name,'LANE_COMPLETED')
        except Exception as exc:event(name,'LANE_PAUSED',reason=type(exc).__name__+': '+str(exc))
    def planning_lane():
        # These newly frozen contexts are independent of an exited older
        # collector. Its unknown terminal remains unchanged in the old lane.
        try:
            import urllib.request
            with urllib.request.urlopen('http://127.0.0.1:8116/transport-health',timeout=10) as response:transport=json.load(response)
            if transport.get('global_teacher_slots')!=2 or transport.get('context16384_route_enabled') is not True:
                raise ValueError('The fixed batch requires the explicit16k route sharing exactly two actual inference slots')
            event('PLANNING','SHARED_TWO_SLOT_16K_ROUTE_VERIFIED',transport=transport)
            for identifier in PLANNING_COLLECTIONS:
                existing=ROOT/'runs/train_collection'/identifier
                if existing.exists():
                    owner=existing_collector(ROOT,identifier)
                    event('PLANNING','EXISTING_COLLECTOR_ADOPTED_WITHOUT_RESTART',collection=identifier,owner=owner,
                        terminal_record_present=(existing/'completion.json').exists())
                    if not owner and not (existing/'completion.json').exists():
                        event('PLANNING','PAUSED_COLLECTION_RETAINED_WITHOUT_CANCELLING_OTHER_COLLECTIONS',collection=identifier,
                            status='EXITED_WITHOUT_TERMINAL_UNKNOWN_NO_REDISPATCH')
                else:launch('PLANNING',identifier)
            for identifier in PLANNING_COLLECTIONS:
                output=ROOT/'runs/train_collection'/identifier;terminal=output/'completion.json'
                while not terminal.exists() and existing_collector(ROOT,identifier):
                    if time.monotonic()>=deadline:raise TimeoutError('Planning monitoring deadline; running collectors remain alive')
                    time.sleep(10)
                if not terminal.exists():
                    event('PLANNING','PAUSED_COLLECTION_RETAINED_WITHOUT_CANCELLING_OTHER_COLLECTIONS',collection=identifier,
                        status='EXITED_WITHOUT_TERMINAL_UNKNOWN_NO_REDISPATCH');continue
                completion=json.loads(terminal.read_text())
                event('PLANNING','COLLECTION_TERMINAL_RECORD_RETAINED',collection=identifier,completion=completion)
                if completion.get('status')!='COMPLETED_INITIAL_BATCH':
                    event('PLANNING','PAUSED_COLLECTION_RETAINED_WITHOUT_CANCELLING_OTHER_COLLECTIONS',collection=identifier,status=completion.get('status'))
            event('PLANNING','LANE_COMPLETED')
        except Exception as exc:event('PLANNING','LANE_PAUSED',reason=type(exc).__name__+': '+str(exc))
    threads=[threading.Thread(target=planning_lane) if name=='PLANNING' else threading.Thread(target=overlap_gpt) if name=='GPT' and args.overlap_teacher_stages else threading.Thread(target=lane,args=(name,plan)) for name,plan in lanes.items()]
    event('coordinator','QUEUE_STARTED',output=str(out))
    for thread in threads:thread.start()
    for thread in threads:thread.join()
    status='PAUSED' if any(row['event']=='LANE_PAUSED' for row in state['events']) else 'COMPLETED_WITH_PAUSED_COLLECTIONS' if any(row['event']=='PAUSED_COLLECTION_RETAINED_WITHOUT_CANCELLING_OTHER_COLLECTIONS' for row in state['events']) else 'COMPLETED'
    state.update(status=status,ended_at_utc=now())
    event('coordinator','QUEUE_FINISHED',status=state['status'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true',required=True);p.add_argument('--max-hours',type=float,default=8)
    p.add_argument('--include-action-teacher',action='store_true',help='Adopt current C05/C08 collectors, insert the separately frozen ACTION teacher at the next GPT collection boundary')
    p.add_argument('--include-c07-action',action='store_true',help='Append the independently frozen qualified C07 ACTION collection after C05 minimal, C01 ACTION8 and C08 minimal')
    p.add_argument('--overlap-teacher-stages',action='store_true',help='With shared global2 transport, dispatch C01 ACTION8 then C07 after each eight-request phase while earlier physical collectors continue')
    p.add_argument('--include-natural-c05-action',action='store_true',help='Append the separately frozen three natural C05 failure ACTION states after C08 begins returning requests')
    p.add_argument('--include-trajectory-c02',action='store_true',help='Append the separately frozen C01 enumeration, four natural C01 failures and qualified C02 collections')
    p.add_argument('--include-planning-trajectories',action='store_true',help='Append the separately frozen16k twelve-context planning batch; at most two one-worker batch collectors overlap')
    args=p.parse_args()
    if not 0<args.max_hours<=8:raise ValueError('This queue has an explicit maximum eight-hour dispatch window; it never kills running jobs')
    run(args)
