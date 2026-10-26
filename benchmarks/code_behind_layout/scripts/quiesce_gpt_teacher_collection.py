"""One maintenance boundary for the existing eight-trial GPT collectors.

Only exact research collector parents and the explicitly authorized queue PID
are signalled. Docker, physical children, T0 and broker/transport processes are
never signalled here. The local gate swap remains a separate root operation.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
QUEUE_PID=1456867
QUEUE_ARGV=['python3','scripts/train_collection_queue.py','--execute','--max-hours','8',
    '--include-action-teacher','--include-c07-action','--overlap-teacher-stages',
    '--include-natural-c05-action','--include-trajectory-c02']
BROKERS=[('source',38052,'runs/development/gpt_teacher_service/20261019T014702128868Z','request.json','invocation.json'),
    ('action',48730,'runs/development/gpt_action_teacher_service/20261019T025406200999Z','teacher_request.json','teacher_invocation.json')]
OLD_TRANSPORT='runs/development/gpt_teacher_transport/20261019T031736550588Z'


def now():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(Path(path).read_text())


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(path.name+'.pending')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')
    temporary.chmod(0o600);temporary.replace(path);path.chmod(0o600)


def process(pid):
    base=Path('/proc')/str(pid)
    try:
        stat=(base/'stat').read_text().rsplit(')',1)[1].split()
        if stat[0]=='Z':return None
        argv=[value.decode() for value in (base/'cmdline').read_bytes().split(b'\0') if value]
        return {'pid':int(pid),'argv':argv,'start_ticks':stat[19],'state':stat[0],
            'cwd':str((base/'cwd').resolve())}
    except (FileNotFoundError,ProcessLookupError):return None


def same_process(before,after):
    return bool(after and all(before[key]==after[key] for key in ('pid','argv','start_ticks','cwd')))


def collector(item):
    argv=item['argv'];cwd=Path(item['cwd'])
    if len(argv)!=5 or argv[2]!='--manifest' or argv[4]!='--execute':return None
    script=Path(argv[1]);script=script if script.is_absolute() else cwd/script
    if script.resolve() not in [ROOT/'scripts/collect_training.py',ROOT/'scripts/run_frozen_training_collection.py']:return None
    if not cwd.is_relative_to(ROOT):return None
    manifest=Path(argv[3]);manifest=manifest if manifest.is_absolute() else cwd/manifest
    manifest=manifest.resolve()
    if not manifest.is_relative_to(ROOT/'runtime/train_collections') or manifest.name!='collection.json':return None
    data=read(manifest)
    if data.get('status')!='frozen' or data.get('role')!='train_collection' or data.get('sampling',{}).get('backend')!='isolated_gpt_cli':return None
    if data['sampling'].get('trials')!=list(range(1,9)):
        raise ValueError('Matched GPT collector does not use the declared eight-trial boundary: '+str(manifest))
    output=Path(data['output_root']).resolve()
    if not output.is_relative_to(ROOT/'runs/train_collection'):raise ValueError('Collector output escapes the research training root')
    return {**item,'kind':'GPT_collector_parent','manifest':str(manifest),'output':str(output),
        'sampling_mode':data['sampling']['mode'],'backend':'isolated_gpt_cli'}


def boundary(output):
    output=Path(output);attempts=read(output/'attempts.json') if (output/'attempts.json').is_file() else []
    if not isinstance(attempts,list):raise ValueError('Collector attempts are not an actual list')
    proposals=sorted(path for path in output.glob('*/*__trial_*') if path.is_dir())
    if any(not re.search(r'__trial_[1-8]$',p.name) for p in proposals):raise ValueError('Unexpected trial directory')
    counts={name:sum((p/name).is_file() for p in proposals) for name in ['request.json','response.json','attempt.json']}
    pending=[{'proposal':str(p),'HTTP_stage':'not_yet_sent' if not (p/'request.json').exists()
        else 'awaiting_HTTP_response' if not (p/'response.json').exists()
        else 'client_validation_pending'} for p in proposals if not (p/'attempt.json').is_file()]
    ready=len(attempts)%8==0 and len(proposals)==len(attempts) and all(count==len(attempts) for count in counts.values())
    return {'attempt_count':len(attempts),'attempt_mod8':len(attempts)%8,'proposal_directories':len(proposals),
        'request_count':counts['request.json'],'response_count':counts['response.json'],
        'terminal_client_attempts':counts['attempt.json'],'pending_HTTP_or_queued_proposals':pending,
        'safe_eight_trial_boundary':ready,'physical_children_may_still_run':True}


def snapshot():
    matched=[];errors=[]
    for filename in sorted(Path('/proc').glob('[0-9]*/cmdline')):
        item=None
        try:
            item=process(int(filename.parent.name))
            if item:
                found=collector(item)
                if found:
                    try:found['boundary']=boundary(found['output'])
                    except (OSError,ValueError) as exc:found['boundary']={'safe_eight_trial_boundary':False,'read_error':str(exc)}
                    matched.append(found)
        except (FileNotFoundError,ProcessLookupError):continue
        except (OSError,ValueError,UnicodeError) as exc:
            # Only a matching collector read error can block a boundary. Other
            # host processes are out of this helper's scope and never signalled.
            if item and len(item['argv'])>=2 and Path(item['argv'][1]).name in ['collect_training.py','run_frozen_training_collection.py']:
                errors.append({'pid':item['pid'],'error':str(exc)})
    queue=process(QUEUE_PID)
    if queue and (queue['argv']!=QUEUE_ARGV or Path(queue['cwd'])!=ROOT):
        raise ValueError('Authorized queue PID now belongs to a different exact argv/cwd; no signals permitted')
    return {'at_utc':now(),'root':str(ROOT),'queue':queue,'collectors':matched,'read_errors':errors,
        'signals_sent':False,'excluded':'Docker/physical children, T0, reverse SSH51739, local transport51687, brokers38052/48730 and8113 are not signal targets'}


def tcp_requests():
    connections=[]
    for table in [Path('/proc/net/tcp'),Path('/proc/net/tcp6')]:
        if not table.exists():continue
        for line in table.read_text().splitlines()[1:]:
            fields=line.split();left,right,state=fields[1:4]
            if (int(left.rsplit(':',1)[1],16) in [8115,8116] or int(right.rsplit(':',1)[1],16) in [8115,8116]) and state not in ['0A','06','07']:
                connections.append({'table':table.name,'local':left,'remote':right,'TCP_state_hex':state})
    return connections


def transport_health():
    rows=[]
    for port in [8115,8116]:
        with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/transport-health',timeout=5) as stream:value=json.load(stream)
        rows.append({'remote_port':port,**{key:value.get(key) for key in ['status','global_teacher_slots','active_forwards','started_at_utc']},
            'context16384_route_enabled':value.get('context16384_route_enabled',False)})
    return rows


def verify_stopped(record):
    live=[]
    for row in record['processes']:
        current=process(row['pid'])
        if current is None:continue
        if not same_process(row,current):raise ValueError('Recorded PID identity changed; do not signal or claim drain')
        if current['state'] not in ['T','t']:raise ValueError('Recorded maintenance parent is not stopped')
        live.append(current)
    present=snapshot()
    if present['read_errors']:raise ValueError('A possible GPT collector cannot be read unambiguously')
    known={p['pid'] for p in record['processes']}
    if any(p['pid'] not in known for p in present['collectors']):raise ValueError('A new unmatched GPT collector appeared after dispatch quiesce')
    return live


def status(record_path):
    record=read(record_path);live=verify_stopped(record)
    # Inspect before our own short GETs, so their TCP close propagation does
    # not create a false pending POST in this same sample.
    connections=tcp_requests();health=transport_health()
    ready=not connections and all(r['status']=='READY' and r['global_teacher_slots']==2 and r['active_forwards']==0 for r in health)
    return {'at_utc':now(),'status':'REMOTE_QUIESCED_AWAIT_LOCAL_DRAIN' if ready else 'REMOTE_HTTP_NOT_DRAINED',
        'all_recorded_parents_stopped_or_exited':True,'live_stopped_parents':len(live),
        'remote_transport_health':health,'remote_broker_TCP_connections':connections,
        'ready_for_local_drain_proof':ready,'one_remote_active0_is_not_upgrade_authorization':True}


def prepare(record_path,wait_seconds):
    record_path=Path(record_path)
    if record_path.exists():raise ValueError('Existing recovery record must be inspected/restored, never overwritten')
    before=snapshot()
    if before['read_errors']:raise ValueError('Read-only collector inspection is incomplete; no process signalled')
    record={'scope':'one_GPT_transport16k_maintenance','started_at_utc':now(),
        'status':'PREPARING','original_inspection':before,'processes':[],'events':[],'signals_are_individual_PIDs_only':True}
    save(record_path,record)
    def stop(item):
        current=process(item['pid'])
        if current is None:return
        if not same_process(item,current):raise ValueError('PID changed before stop')
        row={**item,'original_state':current['state'],'changed_by_this_helper':current['state'] not in ['T','t'],'stop_requested_at_utc':now()}
        record['processes'].append(row);save(record_path,record)
        if row['changed_by_this_helper']:os.kill(row['pid'],signal.SIGSTOP)
        for _ in range(20):
            current=process(row['pid'])
            if current is None or current['state'] in ['T','t']:break
            time.sleep(.01)
        else:raise RuntimeError('Exact parent did not enter stopped state')
        record['events'].append({'event':'PARENT_STOPPED','pid':row['pid'],'at_utc':now()});save(record_path,record)
    if before['queue']:stop({**before['queue'],'kind':'authorized_dispatch_queue'})
    deadline=time.monotonic()+wait_seconds
    try:
        while True:
            seen=snapshot();known={p['pid'] for p in record['processes']}
            if seen['read_errors']:raise ValueError('Collector identity became unreadable; retain recovery record')
            todo=[p for p in seen['collectors'] if p['pid'] not in known]
            for item in todo:
                if not item['boundary']['safe_eight_trial_boundary']:continue
                stop(item)
                try:after=boundary(item['output'])
                except (OSError,ValueError) as exc:after={'safe_eight_trial_boundary':False,'read_error':str(exc)}
                if not after['safe_eight_trial_boundary']:
                    row=record['processes'][-1]
                    if row['changed_by_this_helper'] and same_process(row,process(row['pid'])):os.kill(row['pid'],signal.SIGCONT)
                    record['processes'].pop();record['events'].append({'event':'BOUNDARY_RACE_RESTORED_IMMEDIATELY','pid':item['pid'],'boundary_after_stop':after,'at_utc':now()});save(record_path,record)
            seen=snapshot();record['latest_inspection']=seen;save(record_path,record)
            if all(p['pid'] in {r['pid'] for r in record['processes']} for p in seen['collectors']):break
            if time.monotonic()>=deadline:raise TimeoutError('Finite wait expired before all actual eight-trial boundaries; keep recovery record and resume old route or inspect')
            time.sleep(2)
        record['status']='PARENTS_QUIESCED';record['remote_status']=status(record_path);save(record_path,record)
    except Exception as exc:
        record.update(status='MAINTENANCE_PAUSED_NEEDS_INSPECTION_OR_RESTORE',error=type(exc).__name__+': '+str(exc));save(record_path,record);raise
    return record['remote_status']


def restore(record_path,route):
    record=read(record_path)
    if record.get('status')=='RESTORED':raise ValueError('Recovery record already restored; do not signal again')
    health=transport_health();expected=route=='new16k'
    if any(r['status']!='READY' or r['global_teacher_slots']!=2 or r['context16384_route_enabled'] is not expected for r in health):
        raise ValueError('The explicitly selected new16k/old8k transport route is not READY')
    # Restore collectors before their queue; children were never stopped.
    for row in sorted(record['processes'],key=lambda r:r['kind']=='authorized_dispatch_queue'):
        if row.get('continued_at_utc') or not row['changed_by_this_helper']:continue
        current=process(row['pid'])
        if current is None:row['restore_disposition']='EXITED_NO_SIGNAL';continue
        if not same_process(row,current):raise ValueError('Exact PID/argv/starttime changed; refuse SIGCONT')
        if row['kind']=='authorized_dispatch_queue':
            if current['pid']!=QUEUE_PID or current['argv']!=QUEUE_ARGV or Path(current['cwd'])!=ROOT:
                raise ValueError('Restore record does not bind the one authorized queue')
        elif row['kind']!='GPT_collector_parent' or collector(current) is None:
            raise ValueError('Restore target is not an exact current GPT collector parent')
        if current['state'] not in ['T','t']:raise ValueError('A recorded parent resumed outside this helper; reconcile explicitly')
        os.kill(row['pid'],signal.SIGCONT);row['continued_at_utc']=now();save(record_path,record)
    record.update(status='RESTORED',restored_at_utc=now(),restored_transport_route=route);save(record_path,record)
    return {'status':'RESTORED','route':route,'processes':record['processes'],'children_or_brokers_signalled':False}


def local_drain(record_path):
    # Execute on the local broker host only after the remote record is fetched.
    record=read(record_path)
    if record.get('status')!='PARENTS_QUIESCED':raise ValueError('Actual remote parent-quiesce record required')
    transport=read(ROOT/OLD_TRANSPORT/'transport.json')
    broker_rows=[]
    for name,pid,folder,accepted,terminal in BROKERS:
        base=ROOT/folder;metadata=read(base/'service.json')
        pending=[];accepted_count=terminal_count=0
        for session in sorted((base/'sessions').glob('*')):
            if not session.is_dir():continue
            if (session/accepted).exists():accepted_count+=1
            finished=read(session/terminal) if (session/terminal).is_file() else None
            if finished and finished.get('status') in ['COMPLETED','FAILED','TIMEOUT'] and finished.get('ended_at_utc'):terminal_count+=1
            else:pending.append(str(session))
        broker_rows.append({'name':name,'expected_pid':pid,'metadata_pid':metadata.get('pid'),'status':metadata.get('status'),
            'accepted_requests':accepted_count,'terminal_invocations':terminal_count,'accepted_or_prebody_pending_sessions':pending})
    connections=subprocess.run(['lsof','-nP','-a','-p','51687','-iTCP','-sTCP:ESTABLISHED'],text=True,capture_output=True,timeout=10)
    if connections.returncode not in [0,1] or connections.stderr.strip():raise RuntimeError('Cannot establish local gate socket drain: '+connections.stderr)
    process_state=subprocess.run(['ps','-p','51687','-o','command='],text=True,capture_output=True,timeout=10)
    if process_state.returncode or 'scripts/gpt_teacher_transport_gate.py' not in process_state.stdout or OLD_TRANSPORT not in process_state.stdout:
        raise ValueError('The exact old local transport PID/argv is not present; do not swap another service')
    ready=(transport['status']=='READY' and transport['active_forwards']==0 and not connections.stdout.strip()
        and all(r['status']=='READY' and r['metadata_pid']==r['expected_pid'] and not r['accepted_or_prebody_pending_sessions'] for r in broker_rows))
    return {'at_utc':now(),'status':'LOCAL_DRAIN_SAMPLE_PASS' if ready else 'LOCAL_HTTP_NOT_DRAINED','ready':ready,
        'old_transport_pid':51687,'old_transport_argv':process_state.stdout.strip(),'transport_active_forwards':transport['active_forwards'],
        'local_gate_ESTABLISHED_sockets':connections.stdout,'brokers':broker_rows,
        'required_next_action':'Root must obtain three consecutive remote status and local drain PASS samples after all parents stopped, then replace only oldlocalgate. No single active0 sample is sufficient.',
        'signals_sent':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('op',choices=['inspect','prepare','status','restore','local-drain'])
    parser.add_argument('--record',type=Path);parser.add_argument('--wait-seconds',type=int,default=1200)
    parser.add_argument('--route',choices=['new16k','old8k']);args=parser.parse_args()
    if args.op!='inspect' and args.record is None:parser.error('--record is required')
    if args.op=='prepare' and not 1<=args.wait_seconds<=1800:parser.error('The one maintenance wait is bounded to1..1800seconds')
    if args.op=='restore' and args.route is None:parser.error('Explicit --route new16k or old8k required')
    result=(snapshot() if args.op=='inspect' else prepare(args.record,args.wait_seconds) if args.op=='prepare'
        else status(args.record) if args.op=='status' else restore(args.record,args.route) if args.op=='restore' else local_drain(args.record))
    print(json.dumps(result,indent=2,allow_nan=False),flush=True)
