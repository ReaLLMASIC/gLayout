"""Drain the own T0 state, calibrate an explicit context, restore exact serving."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sequence-length',type=int,choices=[12288,16384],default=12288)
parser.add_argument('--inspect-only',action='store_true',help='Read current service identity and actual received-request/client state; no files, signals or GPU work')
parser.add_argument('--idle-no-future-t0-clients',action='store_true',help='Coordinator has independently prevented future T0 dispatch; permits maintenance when no current T0 collector exists')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
out=None if args.inspect_only else ROOT/('runs/development/gpu_context_'+str(args.sequence_length))/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
if out is not None:out.mkdir(parents=True)
state={'scope':'engineering_'+str(args.sequence_length)+'_feasibility_not_formal_training','pid':os.getpid(),'started_at_utc':datetime.now(timezone.utc).isoformat(),'status':'WAITING_FOR_T0_STATE_DRAIN','events':[],'formal_training_runs':0}
paused=[];service_stopped=False;metadata=None

def event(kind,**values):
    state['events'].append({'at_utc':datetime.now(timezone.utc).isoformat(),'event':kind,**values});(out/'maintenance.json').write_text(json.dumps(state,indent=2)+'\n')

def command(pid):
    try:return [v.decode() for v in Path('/proc/%d/cmdline'%pid).read_bytes().split(b'\0') if v]
    except FileNotFoundError:return None

def clients():
    result=[]
    for p in Path('/proc').glob('[0-9]*/cmdline'):
        try:argv=[v.decode() for v in p.read_bytes().split(b'\0') if v]
        except (OSError,UnicodeDecodeError):continue
        if len(argv)==5 and Path(argv[1]).name=='collect_training.py' and argv[2]=='--manifest' and argv[4]=='--execute' and Path(argv[3]).parent.name in ['c05_collection_v1','c08_collection_v1']:
            result.append((int(p.parent.name),argv,Path(json.loads(Path(argv[3]).read_text())['output_root'])))
    return result

def pending():
    output=Path(metadata['output']);return [p.parent.name for p in (output/'requests').glob('*/request.json') if not (p.parent/'invocation.json').exists()]

if args.inspect_only:
    metadata=json.loads((ROOT/'runs/development/local_policy_service/current.json').read_text());active=clients()
    snapshots=[]
    for pid,argv,raw in active:
        path=raw/'attempts.json';attempts=json.loads(path.read_text()) if path.exists() else []
        snapshots.append({'pid':pid,'argv':argv,'output':str(raw),'returned_attempts':len(attempts),'at_eight_request_boundary':len(attempts)%8==0})
    print(json.dumps({'scope':'read_only_no_signals_no_GPU','service_pid':metadata['pid'],
        'service_exact_argv_matches':command(metadata['pid'])==metadata['argv'],
        'pending_received_requests':pending(),'actual_T0_clients':snapshots,
        'unreceived_TCP_backlog_empty_established':False,
        'empty_client_maintenance_requires_coordinator_no_future_dispatch_assertion':True},indent=2))
    raise SystemExit(0)

try:
    metadata=json.loads((ROOT/'runs/development/local_policy_service/current.json').read_text())
    service_pid=metadata['pid'];expected=metadata['argv']
    if command(service_pid)!=expected:raise ValueError('Service exact argv mismatch before maintenance; no signal sent')
    private=ROOT/'runtime/service_restore'/('local_policy_'+str(args.sequence_length)+'_'+out.name);private.mkdir(mode=0o700)
    (private/'restart.json').write_text(json.dumps({**metadata,'cwd':os.readlink('/proc/%d/cwd'%service_pid)},indent=2)+'\n');(private/'restart.json').chmod(0o600)
    event('EXACT_RESTART_CONFIGURATION_SAVED_PRIVATE',path=str(private/'restart.json'),service_pid=service_pid)
    deadline=time.monotonic()+3*3600
    while True:
        active=clients();safe=(bool(active) or args.idle_no_future_t0_clients) and not pending()
        for pid,argv,raw in active:
            a=raw/'attempts.json';attempts=json.loads(a.read_text()) if a.exists() else []
            # An eight-request boundary leaves EDA or the next fresh baseline
            # before the following state. Never pause an in-flight HTTP client.
            safe=safe and len(attempts)%8==0
        if safe:
            for pid,argv,raw in active:
                if command(pid)!=argv:raise ValueError('T0 client identity changed during drain')
                os.kill(pid,signal.SIGSTOP);paused.append((pid,argv))
            time.sleep(.15)
            if pending():
                for pid,_ in paused:os.kill(pid,signal.SIGCONT)
                paused=[];safe=False
            else:
                with urllib.request.urlopen('http://127.0.0.1:8114/health',timeout=5) as response:health=json.load(response)
                if health['status']!='READY':raise ValueError('Service not ready at drained boundary')
                (out/'premaintenance_health.json').write_text(json.dumps(health,indent=2)+'\n')
                break
        if time.monotonic()>deadline:raise TimeoutError('No safe T0 eight-request boundary; original service unchanged')
        time.sleep(1)
    event('T0_STATE_BOUNDARY_DRAINED_CLIENTS_PAUSED',clients=[{'pid':pid,'argv':argv} for pid,argv in paused],pending_received_requests=[])
    if command(service_pid)!=expected:raise ValueError('Service exact argv changed before stop')
    os.kill(service_pid,signal.SIGTERM);event('OWN_8114_GRACEFUL_STOP_REQUESTED',service_pid=service_pid)
    stop_deadline=time.monotonic()+60
    while command(service_pid):
        if time.monotonic()>stop_deadline:raise TimeoutError('Service did not stop gracefully; no GPU calibration launched')
        time.sleep(.5)
    service_stopped=True;event('OWN_8114_STOPPED')
    import shutil
    if shutil.disk_usage(ROOT).free<8*1024**3:raise RuntimeError('Insufficient research disk reserve for complete engineering checkpoint')
    snapshot=json.loads((ROOT/'configs/training/backbone_cache.json').read_text())['snapshot']
    checkpoint=ROOT/'checkpoints'/('development_gpu_'+str(args.sequence_length)+'_'+out.name)
    argv=[str(ROOT/'runtime/training-venv/bin/python'),'scripts/training_gpu_calibration.py','--snapshot',snapshot,'--output',str(checkpoint),'--sequence-length',str(args.sequence_length)]
    event('ACTUAL_'+str(args.sequence_length)+'_CALIBRATION_STARTING',argv=argv,checkpoint=str(checkpoint))
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2','TOKENIZERS_PARALLELISM':'false','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
    with (out/'calibration.log').open('x') as stream:
        process=subprocess.Popen(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        try:returncode=process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            process.terminate();returncode=process.wait(timeout=60);event('ENGINEERING_CALIBRATION_TIMEOUT_RAW_RETAINED')
    state.update(calibration_returncode=returncode,calibration_path=str(checkpoint/'calibration.json'));event('CALIBRATION_PROCESS_EXITED',returncode=returncode)
except BaseException as exc:
    state.update(error_type=type(exc).__name__,error=str(exc));event('MAINTENANCE_ERROR_RAW_RETAINED',error_type=type(exc).__name__,error=str(exc))
finally:
    try:
        if service_stopped:
            restored_output=ROOT/'runs/development/local_policy_service'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');argv=list(metadata['argv']);index=argv.index('--output');argv[index+1]=str(restored_output)
            env={**os.environ,**metadata['environment_overrides']}
            with (out/'restored_service.log').open('x') as stream:restored=subprocess.Popen(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            current={**metadata,'pid':restored.pid,'argv':argv,'output':str(restored_output),'started_at_utc':datetime.now(timezone.utc).isoformat(),'replaces_pid':metadata['pid'],'restart_reason':str(args.sequence_length)+' engineering calibration maintenance; exact model/adapter/settings restored; fresh log directory only'}
            (ROOT/'runs/development/local_policy_service/current.json').write_text(json.dumps(current,indent=2)+'\n')
            ready_deadline=time.monotonic()+180
            while True:
                p=restored_output/'service.json';ready=json.loads(p.read_text()) if p.exists() else {}
                if ready.get('status')=='READY':break
                if restored.poll() is not None or time.monotonic()>ready_deadline:raise RuntimeError('Original local-policy configuration failed to restore READY; clients remain paused')
                time.sleep(1)
            before=json.loads((out/'premaintenance_health.json').read_text())
            keys=['settings','teacher_source_settings','variants','base_revision','tokenizer_revision','native_tools']
            if any(before[key]!=ready[key] for key in keys):raise RuntimeError('Restored policy settings differ; clients remain paused')
            state['restored_service_pid']=restored.pid;event('OWN_8114_RESTORED_READY_SAME_MODEL_SETTINGS',pid=restored.pid,output=str(restored_output))
        for pid,argv in paused:
            if command(pid)==argv:os.kill(pid,signal.SIGCONT);event('ORIGINAL_T0_CLIENT_RESUMED',pid=pid)
        state['status']='COMPLETED_ENGINEERING_MAINTENANCE' if 'error' not in state and state.get('calibration_returncode')==0 else 'FAILED_CALIBRATION_OR_DRAIN_OR_RESTORE_RAW_RETAINED'
    except BaseException as exc:
        state.update(status='RESTORE_REQUIRED_CLIENTS_PAUSED',restore_error=str(exc));event('RESTORE_ERROR',error=str(exc))
    state['ended_at_utc']=datetime.now(timezone.utc).isoformat();event('MAINTENANCE_TERMINAL_STATE',status=state['status'])
