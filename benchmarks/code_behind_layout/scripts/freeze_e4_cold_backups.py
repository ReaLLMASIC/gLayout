#!/usr/bin/env python3
"""Sequential E4 cold completion. No GPU/EDA, symlinks or automatic retirement."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import resource
import shlex
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.prepare_training import SSH,REMOTE_ROOT,FORMAL_E4_CHECKPOINT_ROOT
from scripts.audit_e4_cold_run import (COMPLETION_FILES,CHECKPOINT_ROOT,check_closed,run_path,inventory,file_row,ordinary)
from src.e4_methods import IMPLEMENTATION_FILES,METHODS,SEEDS,REVISION,file_digest,read
from src.student_interface import interface_definition

MAC_ROOT=ROOT/'checkpoints/formal_e4'
GIB=1024**3


def now():return datetime.now(timezone.utc).isoformat()


@contextmanager
def restore_lock():
    """One explicit local coordinator may restore/audit/finalize at a time."""
    MAC_ROOT.mkdir(parents=True,exist_ok=True)
    with (MAC_ROOT/'.restore.lock').open('a')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.writing')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n');temporary.replace(path)


def static_draft(draft):
    if draft.get('status')!='DRAFT_E4_METHODS':raise ValueError('Actual prospective E4 methods draft required')
    definition=interface_definition(draft['student_interface']['version'],draft['student_interface']['max_context_tokens'],
        draft['student_interface']['max_new_tokens'])
    if definition!=draft['student_interface']:raise ValueError('Complete common ordinary interface required')
    entries=draft.get('formal_training_runs',[])
    if len(entries)!=12 or {(e['method'],e['seed'])for e in entries}!={(m,s)for m in METHODS for s in SEEDS}:
        raise ValueError('Exactly12 distinct method/seed declarations required')
    for entry in entries:run_path(entry)
    return entries


def code_bindings():
    return {'implementation_sha256':{n:file_digest(ROOT/n)for n in IMPLEMENTATION_FILES},
        'completion_implementation_sha256':{n:file_digest(ROOT/n)for n in COMPLETION_FILES}}


def prepare(draft_path,server_draft,output):
    output=ordinary(Path(output).resolve())
    if not output.is_relative_to(ROOT/'runtime/e4_cold_completion'):
        raise ValueError('Use this project runtime/e4_cold_completion for the private journal')
    server_draft=Path(server_draft)
    if not server_draft.is_absolute()or not server_draft.is_relative_to(Path(REMOTE_ROOT))or '..'in server_draft.parts:
        raise ValueError('Server methods draft must be inside this project')
    draft=read(draft_path);entries=static_draft(draft)
    if any(not entry.get(k)or not Path(entry[k]).is_absolute()for entry in entries
        for k in ('training_manifest','validation_selection','selected_checkpoint')):
        raise ValueError('Final journal requires all12 known original absolute manifest, selection and selected-checkpoint paths')
    if output.exists():raise ValueError('Preserve an existing cold completion journal')
    output.mkdir(parents=True,mode=0o700)
    # Keep the exact input bytes, including original absolute identities.
    (output/'draft.json').write_bytes(Path(draft_path).read_bytes());(output/'draft.json').chmod(0o444)
    plan={'status':'FIXED_E4_COLD_COMPLETION_JOURNAL','created_at_utc':now(),'server_draft':str(server_draft),
        'draft_sha256':file_digest(output/'draft.json'),'checkpoint_root':FORMAL_E4_CHECKPOINT_ROOT,
        'durable_root':str(MAC_ROOT),'session':output.name,'entries':entries,**code_bindings()}
    save(output/'plan.json',plan);(output/'plan.json').chmod(0o444)
    save(output/'state.json',{'status':'NOT_READY','runs':{},'events':[],'new_model_or_EDA_calls':0})
    return plan


def load(output):
    output=ordinary(Path(output).resolve());plan=read(output/'plan.json');state=read(output/'state.json')
    if (plan['checkpoint_root']!=FORMAL_E4_CHECKPOINT_ROOT or plan['durable_root']!=str(MAC_ROOT)
        or file_digest(output/'draft.json')!=plan['draft_sha256']or any(plan[k]!=v for k,v in code_bindings().items())):
        raise ValueError('Cold plan, original draft or bound implementations changed')
    static_draft(read(output/'draft.json'))
    return output,plan,state


def event(output,state,stage,started,cpu,**extra):
    row={'stage':stage,'ended_at_utc':now(),'wall_seconds':time.monotonic()-started,
        'local_process_CPU_seconds':time.process_time()-cpu,**extra}
    state['events'].append(row);save(output/'state.json',state);return row


def external(output,state,argv,stage,byte_count=0,body=None):
    number=len(state['events']);folder=output/'operations'/('%05d'%number);folder.mkdir(parents=True)
    started=time.monotonic();cpu=time.process_time();before=resource.getrusage(resource.RUSAGE_CHILDREN)
    save(folder/'invocation.json',{'argv':argv,'started_at_utc':now(),'stage':stage,'file_bytes':byte_count})
    if body is not None:save(folder/'request.json',body)
    try:
        result=subprocess.run(argv,input=None if body is None else json.dumps(body),text=True,capture_output=True,
            timeout=1800,check=False)
        (folder/'stdout.txt').write_text(result.stdout);(folder/'stderr.txt').write_text(result.stderr)
        returncode=result.returncode
    except Exception as error:
        result=None;returncode=None;(folder/'error.txt').write_text(type(error).__name__+': '+str(error))
        raise
    finally:
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        event(output,state,stage,started,cpu,local_child_CPU_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
            transferred_file_bytes=byte_count if returncode==0 else None,planned_file_bytes=byte_count,
            wire_bytes=None,remote_CPU_seconds=None,returncode=returncode,
            operation_directory=str(folder),scope='Local client CPU only; transfer wall is not CPU time')
    if result.returncode:raise RuntimeError('External cold operation failed; inspect '+str(folder))
    return result.stdout


def rpc(output,plan,state,operation,**fields):
    body={'operation':operation,'draft':plan['server_draft'],'draft_sha256':plan['draft_sha256'],
        'session':plan['session'],**fields}
    command='cd '+shlex.quote(REMOTE_ROOT)+' && '+shlex.quote(REMOTE_ROOT+'/runtime/GLdev/bin/python')+' scripts/audit_e4_cold_run.py --request'
    result=json.loads(external(output,state,SSH+[command],'remote_'+operation,body=body))
    if result.get('audit_operation_costs'):
        state['events'][-1]['observed_remote_audit_costs']=result['audit_operation_costs'];save(output/'state.json',state)
    return result


def matching_header(output,plan,state):
    result=rpc(output,plan,state,'header')
    if any(result[k]!=plan[k]for k in ('draft_sha256','implementation_sha256','completion_implementation_sha256')):
        raise ValueError('Actual server code/draft differs from the local committed consumer')
    return result


def local_run(entry):return MAC_ROOT/entry['method']/('seed-'+str(entry['seed']))


def verify_backups(entry,closed):
    """Read every real byte again; CHECKSUM_VERIFIED alone is never sufficient."""
    check_closed(closed,entry);rows=[]
    for row in closed['run_files']:
        path=ordinary(local_run(entry)/Path(row['path']).relative_to(run_path(entry)))
        actual=file_row(path);actual['path']=row['path']
        if actual!=row:raise ValueError('Actual closed root run/metrics/latest-checkpoint bytes missing/changed')
    for original in closed['checkpoints']:
        base=ordinary(local_run(entry)/Path(original['checkpoint']).name)
        marker=read(base/'backup_manifest.json')
        if marker.get('checkpoint')!=original['checkpoint']or marker.get('files')!=original['files']:
            raise ValueError('Cold backup is not the exact actual saved checkpoint')
        actual=inventory(base)
        actual=[r for r in actual if r['path']!='backup_manifest.json']
        if actual!=original['files']:raise ValueError('Actual local checkpoint bytes missing/changed')
        rows.append({'checkpoint':original['checkpoint'],'local_checkpoint':str(base),
            'files':actual,'bytes':sum(r['bytes']for r in actual)})
    return rows


def transfer_path(path):
    path=str(path)
    if not re.fullmatch(r'[A-Za-z0-9_./-]+',path)or '..'in Path(path).parts:
        raise ValueError('Unsupported transfer path; no shell/path rewriting')
    return path


def capture_run(draft_path,server_draft,method,seed):
    """Before retirement, back up the original completed root files, not CP metadata substitutes."""
    draft=read(draft_path);entries=static_draft(draft)
    entry=next(e for e in entries if e['method']==method and e['seed']==seed)
    output=local_run(entry)/'capture'
    if output.exists():raise ValueError('Preserve an existing run metadata capture; no automatic retry')
    output.mkdir(parents=True,mode=0o700)
    state={'events':[]};save(output/'state.json',state)
    plan={'server_draft':str(server_draft),'draft_sha256':file_digest(draft_path),'session':'capture',**code_bindings()}
    matching_header(output,plan,state)
    result=rpc(output,plan,state,'close',method=method,seed=seed);closed=check_closed(result['closed_inventory'],entry)
    if shutil.disk_usage(ROOT).free<result['closed_bytes']+sum(r['bytes']for r in closed['run_files'])+2*GIB:
        raise RuntimeError('Insufficient local durable space for actual closed run metadata')
    marker=local_run(entry)/'closed_inventory.json'
    if marker.exists():raise ValueError('Do not overwrite a previously captured closed inventory')
    external(output,state,['scp']+SSH[1:-1]+['cbl-server:'+transfer_path(result['closed_path']),str(marker)],
        'backup_closed_inventory',result['closed_bytes'])
    if file_digest(marker)!=result['closed_sha256']or read(marker)!=closed:raise ValueError('Actual closed inventory transfer differs')
    for row in closed['run_files']:
        path=ordinary(local_run(entry)/Path(row['path']).relative_to(run_path(entry)))
        if path.exists():raise ValueError('Do not overwrite an existing run metadata file')
        path.parent.mkdir(parents=True,exist_ok=True)
        external(output,state,['scp']+SSH[1:-1]+['cbl-server:'+transfer_path(row['path']),str(path)],
            'backup_closed_run_metadata',row['bytes'])
        actual=file_row(path);actual['path']=row['path']
        if actual!=row:raise ValueError('Actual closed run metadata transfer differs')
    state.update(status='ACTUAL_CLOSED_RUN_METADATA_BACKED_UP_NOT_MODEL_SELECTION',new_model_or_EDA_calls=0)
    save(output/'state.json',state);return {'status':state['status'],'closed_inventory':str(marker),'run_files':len(closed['run_files'])}


def audit_run(output,method,seed):
    output,plan,state=load(output);key=method+'_'+str(seed)
    entries=[e for e in plan['entries']if e['method']==method and e['seed']==seed]
    if len(entries)!=1:raise ValueError('One declared run required')
    entry=entries[0];previous=state['runs'].get(key,{})
    if previous.get('status')=='AUDITED':return previous
    if previous.get('status')in ('RESERVED','RESTORING','UNRESOLVED'):
        raise ValueError('Unresolved prior operation requires explicit review, never automatic retry')
    if previous.get('status','').startswith('WAITING_')and previous.get('waiting_since_utc'):
        state['events'].append({'stage':'operator_resource_wait','wall_seconds':max(0.,(datetime.now(timezone.utc)-datetime.fromisoformat(previous['waiting_since_utc'])).total_seconds()),
            'local_process_CPU_seconds':None,'remote_CPU_seconds':None,'scope':'Observed UTC gap between resource wait and explicit operator resume'})
    state['runs'][key]={'status':'RESERVED','reserved_at_utc':now(),'method':method,'seed':seed};save(output/'state.json',state)
    try:
        started=time.monotonic();cpu=time.process_time();backups=None
        try:
            closed=read(local_run(entry)/'closed_inventory.json');backups=verify_backups(entry,closed)
        finally:event(output,state,'reopen_actual_Mac_checkpoints',started,cpu,bytes_reopened=None if backups is None else sum(r['bytes']for r in backups))
        matching_header(output,plan,state)
        restored=rpc(output,plan,state,'restore-plan',method=method,seed=seed,closed_inventory=closed)
        if restored['status']!='READY':
            state['runs'][key].update(status=restored['status'],resource_gate=restored['resource_gate'],waiting_since_utc=now())
            save(output/'state.json',state);return state['runs'][key]
        state['runs'][key]['status']='RESTORING';save(output/'state.json',state)
        files={str(Path(r['checkpoint'])/f['path']):(r,f)for r in backups for f in r['files']}
        for row in closed['run_files']:
            files[row['path']]=({'local_checkpoint':str(local_run(entry))},{**row,'path':str(Path(row['path']).relative_to(run_path(entry)))})
        for row in restored['missing']:
            original,item=files[row['path']]
            source=Path(original['local_checkpoint'])/item['path'];destination=transfer_path(row['path'])
            external(output,state,['scp']+SSH[1:-1]+[str(source),'cbl-server:'+destination],
                'restore_checkpoint',item['bytes'])
        result=rpc(output,plan,state,'audit',method=method,seed=seed,closed_inventory=closed)
        actual=result['audit']
        if (actual['status']!='ACTUAL_E4_COLD_RUN_AUDIT_COMPLETE'or actual['closed_inventory']!=closed
            or any(actual[k]!=plan[k]for k in ('draft_sha256','implementation_sha256','completion_implementation_sha256'))):
            raise ValueError('Actual trusted audit differs from reopened original bytes')
        # Raw validation stays on the execution host. Its actual byte closure is
        # bound by the trusted audit and freshly reopened at finalization.
        save(output/'audits'/(key+'.json'),result)
        state['runs'][key].update(status='AUDITED',audit_path=result['audit_path'],audit_sha256=result['audit_sha256'],
            selected_adapter=actual['selection']['selected_adapter'],checkpoints=len(backups),ended_at_utc=now(),
            retention='No automatic deletion. Root must review exact redundant restored files before any retirement.')
        save(output/'state.json',state);return state['runs'][key]
    except Exception as error:
        state['runs'][key].update(status='UNRESOLVED',error=type(error).__name__+': '+str(error));save(output/'state.json',state);raise


def assemble(draft,header,audits):
    """Same cross-run predicates/ordinary serving schema as build_methods_freeze.

    Called only after this coordinator's fresh raw rechecks and actual local reads;
    never exposed as a CLI accepting user-supplied receipt flags.
    """
    entries=static_draft(draft);expected={(m,s)for m in METHODS for s in SEEDS}
    if len(audits)!=12 or {(a['method'],a['seed'])for a in audits}!=expected:
        raise ValueError('All12 actual complete run audits are required')
    trained={};selected={}
    for a in audits:
        if (a.get('status')!='ACTUAL_E4_COLD_RUN_AUDIT_COMPLETE'or a['draft_sha256']!=header['draft_sha256']
            or any(a[k]!=header[k]for k in ('implementation_sha256','completion_implementation_sha256','registry_sha256'))):
            raise ValueError('Unbound/unknown run audit cannot freeze models')
        key=a['method'],a['seed'];trained[key]=a['training'];selected[key]=a['selection']
    common=trained['T1',SEEDS[0]]
    if any(t['config']!=common['config']or t['run']['identities']['datasets']!=common['run']['identities']['datasets']for t in trained.values()):
        raise ValueError('Same frozen recipe and matched dataset bytes required')
    for seed in SEEDS:
        for left,right in [('T1','T2'),('T3','T4')]:
            a,b=trained[left,seed],trained[right,seed]
            if (a['config']!=b['config']or any(a['run'][k]!=b['run'][k]for k in ('updates','samples','allocated_sequence_tokens_per_epoch'))
                or a['run']['identities']['registry']!=b['run']['identities']['registry']):
                raise ValueError('Matched source/recipe/update allocation changed')
        for method in ('T3','T4'):
            if trained[method,seed]['run'].get('reference_checkpoint')!=selected['T1',seed]['selected_adapter']:
                raise ValueError('Same-seed selected T1 canonical reference identity changed')
    variants={'T0':{'base_revision':REVISION,'adapter':None,'actual_training_seeds':[],'actual_model_count':1,
        'matched_evaluation_seed_slots':list(SEEDS)}}
    for method in METHODS:
        variants[method]={'training_seeds':list(SEEDS),'seeds':{str(s):{'run_directory':trained[method,s]['run_directory'],
            'training_manifest':trained[method,s]['training_manifest'],**selected[method,s]}for s in SEEDS}}
    return {'status':'FROZEN_E4_METHODS','version':'e4_methods_v1','frozen_at_utc':now(),
        'backbone':'Qwen/Qwen2.5-Coder-32B-Instruct','base_revision':REVISION,'backbone_snapshot':common['manifest']['backbone_snapshot'],
        'tokenizer_revision':REVISION,'quantization':common['config']['quantization'],'adapter_architecture':common['config']['lora'],
        'formal_training_runs':12,'engineering_runs_counted':0,'training_seeds':list(SEEDS),'student_interface':header['definition'],
        'decoding_settings':draft['decoding_settings'],'variants':variants,'split_registry':header['registry_path'],
        'split_registry_sha256':header['registry_sha256'],'context_calibration':header['calibration'],
        'validation_plan':header['plan_path'],'validation_plan_sha256':header['validation_plan_sha256'],
        'implementation_sha256':header['implementation_sha256'],
        'hidden_evaluation_policy':'global_release_only_after_all_predeclared_searches_sealed_and_all_models_frozen',
        'hidden_evaluation_released':False}


def finalize(output,methods_output,validate_only=False):
    output,plan,state=load(output)
    if len(state['runs'])!=12 or any(r.get('status')!='AUDITED'for r in state['runs'].values()):
        return {'status':'NOT_READY_ALL12_ACTUAL_RUN_AUDITS_REQUIRED','audited_runs':sum(r.get('status')=='AUDITED'for r in state['runs'].values()),
            'declared_runs':12,'formal_methods_written':False}
    destination=Path(methods_output)
    if destination.exists():raise ValueError('Do not overwrite an existing actual methods freeze')
    header=matching_header(output,plan,state);audits=[];reopened=0
    for entry in plan['entries']:
        key=entry['method']+'_'+str(entry['seed']);response=read(output/'audits'/(key+'.json'));actual=response['audit']
        started=time.monotonic();cpu=time.process_time();rows=None
        try:
            rows=verify_backups(entry,actual['closed_inventory']);reopened+=sum(r['bytes']for r in rows)
        finally:event(output,state,'final_reopen_checkpoint_and_run_metadata_bytes',started,cpu,
            bytes_reopened=None if rows is None else sum(r['bytes']for r in rows)+sum(r['bytes']for r in actual['closed_inventory']['run_files']))
        checked=rpc(output,plan,state,'recheck',method=entry['method'],seed=entry['seed'],
            audit_path=response['audit_path'],audit_sha256=response['audit_sha256'])
        if (checked.get('status')!='ACTUAL_AUDITED_RAW_BYTES_REOPENED'
            or checked.get('audit_path')!=response['audit_path']or checked.get('audit_sha256')!=response['audit_sha256']):
            raise ValueError('Actual server raw recheck is incomplete or belongs to another audit')
        # Exactly the serialization used by the trusted server save_once.
        serialized=(json.dumps(actual,indent=2,allow_nan=False)+'\n').encode()
        if hashlib.sha256(serialized).hexdigest()!=checked['audit_sha256']:
            raise ValueError('Local audit differs from the original audit just reopened on the server')
        audits.append(actual)
    artifact=assemble(read(output/'draft.json'),header,audits)
    artifact['cold_completion']={'version':'e4_full_run_restore_v1','checkpoint_root':FORMAL_E4_CHECKPOINT_ROOT,
        'durable_root':str(MAC_ROOT),'plan_path':str(output/'plan.json'),'plan_sha256':file_digest(output/'plan.json'),
        'completion_implementation_sha256':header['completion_implementation_sha256'],
        'actual_checkpoint_bytes_reopened':reopened,'all_saved_checkpoints_retained':True,
        'run_audits':[{k:state['runs'][e['method']+'_'+str(e['seed'])][k]for k in ('method','seed','audit_path','audit_sha256','checkpoints')}for e in plan['entries']],
        'operation_ledger':str(output/'state.json'),'new_model_or_EDA_calls':0,'automatic_deletions':0}
    if not validate_only:
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('x')as stream:stream.write(json.dumps(artifact,indent=2,allow_nan=False)+'\n')
        destination.chmod(0o444)
    state['status']='ACTUAL_ALL12_VALIDATED'if validate_only else 'FROZEN_E4_METHODS';save(output/'state.json',state)
    return {'status':state['status'],'formal_methods_written':not validate_only,'methods_output':str(destination),
        'actual_checkpoint_bytes_reopened':reopened,'new_model_or_EDA_calls':0,'automatic_deletions':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--draft',type=Path,required=True);p.add_argument('--server-draft',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('capture-run');p.add_argument('--draft',type=Path,required=True);p.add_argument('--server-draft',required=True);p.add_argument('--method',choices=METHODS,required=True);p.add_argument('--seed',type=int,choices=SEEDS,required=True)
    p=sub.add_parser('audit-run');p.add_argument('--output',type=Path,required=True);p.add_argument('--method',choices=METHODS,required=True);p.add_argument('--seed',type=int,choices=SEEDS,required=True)
    p=sub.add_parser('finalize');p.add_argument('--output',type=Path,required=True);p.add_argument('--methods-output',type=Path,required=True);p.add_argument('--validate-only',action='store_true')
    args=parser.parse_args();started=time.monotonic();cpu=time.process_time();before=resource.getrusage(resource.RUSAGE_CHILDREN)
    directory=MAC_ROOT/args.method/('seed-'+str(args.seed))/'capture'if args.command=='capture-run'else args.output
    success=False
    try:
        if args.command=='prepare':result=prepare(args.draft,args.server_draft,args.output)
        elif args.command=='capture-run':result=capture_run(args.draft,args.server_draft,args.method,args.seed)
        elif args.command=='audit-run':
            with restore_lock():result=audit_run(args.output,args.method,args.seed)
        else:
            with restore_lock():result=finalize(args.output,args.methods_output,args.validate_only)
        success=True;print(json.dumps(result,allow_nan=False))
    finally:
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        totals={'command':args.command,'ended_at_utc':now(),'success':success,'wall_seconds':time.monotonic()-started,
            'local_process_CPU_seconds':time.process_time()-cpu,
            'local_child_CPU_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,'remote_CPU_seconds':None,
            'scope':'Whole CLI invocation totals; do not sum again with operation-level breakdown. Remote audit CPU is in state events; transfer CPU unavailable.'}
        if Path(directory).is_dir():
            with (Path(directory)/'invocation_telemetry.jsonl').open('a')as target:target.write(json.dumps(totals)+'\n')
        else:print(json.dumps({'invocation_telemetry':totals}),file=sys.stderr)


if __name__=='__main__':main()
