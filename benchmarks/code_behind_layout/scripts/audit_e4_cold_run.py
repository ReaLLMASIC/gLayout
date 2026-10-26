#!/usr/bin/env python3
"""CPU-only audits of one restored formal E4 run; never train or delete files."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.prepare_training import FORMAL_E4_CHECKPOINT_ROOT,REMOTE_ROOT
from src.e4_methods import (IMPLEMENTATION_FILES,METHODS,SEEDS,SELECTION_RULE,REVISION,
    file_digest,inspect_formal_run,validate_selection,validate_context_calibration,resolve,read)
from src.student_interface import interface_definition
from src.training import frozen_train_registry

CHECKPOINT_ROOT=Path(FORMAL_E4_CHECKPOINT_ROOT)
COMPLETION_FILES=('scripts/prepare_training.py','scripts/audit_e4_cold_run.py','scripts/freeze_e4_cold_backups.py')
AUDIT_ROOT=Path(REMOTE_ROOT)/'runtime/e4_cold_completion'
GIB=1024**3


def now():return datetime.now(timezone.utc).isoformat()


def ordinary(path):
    path=Path(path)
    if '..' in path.parts or path.is_symlink():raise ValueError('Ordinary contained files required')
    for parent in path.parents:
        if parent.is_symlink():raise ValueError('No directory aliases in cold evidence')
    return path


def file_row(path):
    path=ordinary(path)
    if not path.is_file():raise ValueError('Missing actual audit input: '+str(path))
    return {'path':str(path),'bytes':path.stat().st_size,'sha256':file_digest(path)}


def inventory(directory):
    directory=ordinary(directory)
    if not directory.is_dir():raise ValueError('Missing actual checkpoint directory')
    rows=[]
    for path in sorted(directory.rglob('*')):
        ordinary(path)
        if path.is_file():
            row=file_row(path);row['path']=path.relative_to(directory).as_posix();rows.append(row)
    return rows


def expected_updates(config,method,samples):
    recipe=config['dpo' if method in ('T3','T4') else 'sft']
    values=(samples,config['gradient_accumulation'],recipe['epochs'],config['checkpoint_interval_updates'])
    if any(type(v)is not int or v<=0 for v in values):raise ValueError('Positive actual cadence inputs required')
    n,a,e,i=values;u=math.ceil(n/a);return sorted(set(range(i,e*u+1,i))|{u*k for k in range(1,e+1)})


def run_path(entry):
    if entry.get('method') not in METHODS or type(entry.get('seed'))is not int or entry['seed'] not in SEEDS:
        raise ValueError('One declared actual E4 method/seed required')
    path=CHECKPOINT_ROOT/entry['method']/('seed-'+str(entry['seed']))
    if Path(entry['run_directory'])!=path:raise ValueError('Run must use its original fixed owned shm path')
    return ordinary(path)


def bindings():
    return {'implementation_sha256':{n:file_digest(ROOT/n) for n in IMPLEMENTATION_FILES},
        'completion_implementation_sha256':{n:file_digest(ROOT/n) for n in COMPLETION_FILES}}


def header(draft_path,expected_sha=None):
    draft_path=ordinary(Path(draft_path))
    if not draft_path.is_absolute() or not draft_path.is_relative_to(Path(REMOTE_ROOT)):
        raise ValueError('The methods draft must stay in this server project')
    if expected_sha and file_digest(draft_path)!=expected_sha:raise ValueError('Local/server methods draft bytes differ')
    draft=read(draft_path)
    if draft.get('status')!='DRAFT_E4_METHODS':raise ValueError('An actual methods draft is required')
    definition=interface_definition(**dict(zip(('version','max_context_tokens','max_new_tokens'),
        (draft['student_interface'][k] for k in ('version','max_context_tokens','max_new_tokens')))))
    if definition!=draft['student_interface']:raise ValueError('Exact ordinary student interface required')
    # Absolute metadata paths keep storage identities independent of the local cwd.
    for key in ('split_registry','validation_plan','context_calibration'):
        if not Path(draft[key]).is_absolute():raise ValueError('Cold methods draft paths must be absolute')
    registry_path=ordinary(draft['split_registry']);registry=read(registry_path);frozen_train_registry(registry)
    digest=file_digest(registry_path);plan_path=ordinary(draft['validation_plan']);plan=read(plan_path)
    if (plan.get('status')!='FROZEN_E4_VALIDATION_PLAN' or plan_path.stat().st_mode&0o222
        or plan.get('selection_rule')!=SELECTION_RULE or plan.get('split_registry_sha256')!=digest or not plan.get('points')):
        raise ValueError('The actual readonly validation-only plan is not ready')
    from src.e4_validation import validate_plan
    validate_plan(plan,plan_path)
    calibration=validate_context_calibration(draft['context_calibration'],definition)
    entries=draft.get('formal_training_runs',[])
    if len(entries)!=12 or {(e['method'],e['seed']) for e in entries}!={(m,s)for m in METHODS for s in SEEDS}:
        raise ValueError('Exactly12 distinct actual method/seed entries are required')
    for entry in entries:
        run_path(entry)
        for key in ('training_manifest','validation_selection','selected_checkpoint'):
            if entry.get(key) and not Path(entry[key]).is_absolute():raise ValueError('Original absolute run identities required')
    if draft.get('decoding_settings')!={'do_sample':False,'max_new_tokens':1024}:
        raise ValueError('Common ordinary greedy1024 decoding required')
    return {'draft':draft,'draft_sha256':file_digest(draft_path),'definition':definition,'registry':registry,
        'registry_path':str(registry_path),'registry_sha256':digest,'plan':plan,'plan_path':str(plan_path),
        'validation_plan_sha256':file_digest(plan_path),'calibration':calibration,**bindings()}


def entry_for(value,method,seed):
    rows=[r for r in value['draft']['formal_training_runs'] if r['method']==method and r['seed']==seed]
    if len(rows)!=1:raise ValueError('One exact method/seed entry required')
    return rows[0]


def close_run(entry,value):
    """Run the unchanged complete trainer gate before recording the full inventory."""
    training=inspect_formal_run(entry,ROOT,value['definition'],value['registry_sha256'])
    updates=expected_updates(training['config'],entry['method'],training['run']['samples'])
    names=['checkpoint-%07d'%u for u in updates]
    found=sorted(p.name for p in run_path(entry).glob('checkpoint-*'))
    if found!=names or training['run']['updates']!=updates[-1]:
        raise ValueError('Closed run omitted/added a saved checkpoint or changed its frozen cadence')
    rows=[{'checkpoint':str(run_path(entry)/name),'files':inventory(run_path(entry)/name)} for name in names]
    run=run_path(entry)/'run.json'
    run_files=[file_row(p)for p in sorted(run_path(entry).rglob('*'))if p.is_file()
        and not any(part.startswith('checkpoint-')for part in p.relative_to(run_path(entry)).parts)]
    return training,{'status':'CLOSED_ACTUAL_E4_RUN_INVENTORY','method':entry['method'],'seed':entry['seed'],
        'run_directory':str(run_path(entry)),'run_file':file_row(run),'run_text':run.read_text(),
        'run_files':run_files,'identities':training['run']['identities'],'expected_updates':updates,'checkpoints':rows}


def check_closed(closed,entry):
    if (closed.get('status')!='CLOSED_ACTUAL_E4_RUN_INVENTORY' or closed.get('method')!=entry['method']
        or closed.get('seed')!=entry['seed'] or closed.get('run_directory')!=str(run_path(entry))):
        raise ValueError('Closed inventory belongs to another run')
    updates=closed.get('expected_updates',[]);rows=closed.get('checkpoints',[])
    expected=[str(run_path(entry)/('checkpoint-%07d'%u))for u in updates]
    if (not updates or any(type(u)is not int or u<=0 for u in updates)or updates!=sorted(set(updates))
        or [r['checkpoint']for r in rows]!=expected):
        raise ValueError('Full ordered checkpoint denominator required')
    root_files=closed.get('run_files',[])
    if closed.get('run_file')not in root_files or not root_files or len({r['path']for r in root_files})!=len(root_files):
        raise ValueError('The original closed root run.json/metadata inventory is required')
    for row in root_files:
        name=Path(row['path'])
        if not name.is_relative_to(run_path(entry))or '..'in name.parts or any(p.startswith('checkpoint-')for p in name.relative_to(run_path(entry)).parts):
            raise ValueError('Run-level files must retain original non-checkpoint paths')
    for row in rows:
        names=[r['path']for r in row['files']]
        if not names or len(set(names))!=len(names):raise ValueError('Distinct complete byte inventory required')
        for name in names:
            path=Path(name)
            if path.is_absolute() or '..'in path.parts or not path.parts:raise ValueError('Contained checkpoint files required')
    return closed


def capacity(required):
    """Observe resources once. Waiting is durable state, never automatic deletion."""
    def stat():
        values=list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        return sum(values),values[3]+values[4]
    a=stat();time.sleep(.2);b=stat();delta=b[0]-a[0]
    if delta<=0:raise ValueError('Actual CPU availability could not be sampled')
    busy=(1-(b[1]-a[1])/delta)*(os.cpu_count()or 1)
    memory={r.split(':')[0]:int(r.split()[1])*1024 for r in Path('/proc/meminfo').read_text().splitlines()if r.split()[1].isdigit()}
    used=memory['MemTotal']-memory['MemAvailable'];root_free=shutil.disk_usage(REMOTE_ROOT).free
    shm_free=shutil.disk_usage(CHECKPOINT_ROOT.parent if CHECKPOINT_ROOT.parent.exists()else '/dev/shm').free
    status='READY'
    if required>shm_free:status='WAITING_RETIREMENT'
    elif used+required>190*GIB:status='WAITING_RAM'
    elif root_free<4*GIB:status='WAITING_DISK'
    elif busy+2>24:status='WAITING_CPU'
    return {'status':status,'missing_bytes':required,'shm_free_bytes':shm_free,'root_free_bytes':root_free,
        'RAM_used_bytes':used,'busy_cores':busy,'observed_at_utc':now()}


def restore_plan(entry,closed):
    closed=check_closed(closed,entry)
    actual=sorted(p.name for p in run_path(entry).glob('checkpoint-*'))
    expected=[Path(r['checkpoint']).name for r in closed['checkpoints']]
    if set(actual)-set(expected):raise ValueError('Undeclared saved checkpoint cannot be dropped')
    missing=[]
    for checkpoint in closed['checkpoints']:
        base=ordinary(checkpoint['checkpoint'])
        declared={r['path']:r for r in checkpoint['files']}
        if base.exists() and {p.relative_to(base).as_posix()for p in base.rglob('*')if p.is_file()}-set(declared):
            raise ValueError('Restored checkpoint contains undeclared files')
        for name,row in declared.items():
            path=ordinary(base/name)
            if path.exists():
                actual=file_row(path);actual['path']=name
                if actual!=row:raise ValueError('Existing restored bytes differ; no overwrite or automatic retry')
            else:missing.append({'path':str(path),**{k:row[k]for k in ('bytes','sha256')}})
    for row in closed['run_files']:
        path=ordinary(row['path'])
        if path.exists():
            if file_row(path)!=row:raise ValueError('Original completed run-level bytes changed')
        else:missing.append(row)
    gate=capacity(sum(r['bytes']for r in missing))
    if gate['status']=='READY':
        for row in missing:Path(row['path']).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    return {'status':gate['status'],'resource_gate':gate,'missing':missing,'deleted_files':0}


def verification_files(entry,value,training,selection):
    """Bind the actual raw closure so cold rechecks cannot trust summary flags."""
    files=set()
    def add(path):
        path=ordinary(path)
        if not path.is_absolute() or not any(path.is_relative_to(p)for p in (Path(REMOTE_ROOT),CHECKPOINT_ROOT)):
            raise ValueError('Audit evidence is outside the two explicit project roots')
        if path.is_dir():
            files.update(p for p in path.rglob('*')if p.is_file())
        else:files.add(path)
    for path in run_path(entry).rglob('*'):
        if not any(p.startswith('checkpoint-')for p in path.relative_to(run_path(entry)).parts):
            if path.is_file():add(path)
    manifest_path=Path(training['training_manifest']);manifest=training['manifest']
    add(manifest_path)
    for name in ('training_config','split_registry','trusted_evidence_manifest','context_calibration'):
        if manifest.get(name):add(resolve(manifest_path.parent,manifest[name]))
    add(resolve(manifest_path.parent,manifest['student_interface']['selection_report']))
    for row in manifest['methods'].values():
        if row.get('samples'):add(resolve(manifest_path.parent,row['samples']))
    for path in (value['registry_path'],value['plan_path'],value['calibration']['path'],entry['validation_selection']):add(path)
    add(AUDIT_ROOT/'closed'/(entry['method']+'_'+str(entry['seed'])+'.json'))
    for declaration in value['plan']['tasks']:
        task_path=Path(declaration['task_file']);task=read(task_path);add(task_path)
        add(resolve(task_path.parent,task['source_pack']));add(resolve(task_path.parent,task['packet']))
    from src.e4_validation import validate_editing_ledger
    selected=read(entry['validation_selection'])
    for evaluation in selected['checkpoint_evaluations']:
        ledger_path=resolve(Path(entry['validation_selection']).parent,evaluation['editing_ledger'])
        ledger=validate_editing_ledger(ledger_path,value['plan'],evaluation['checkpoint'],entry['method'],entry['seed']);add(ledger_path)
        if ledger['points']!=evaluation['points'] or {k:r['final_sources']for k,r in ledger['tasks'].items()}!=evaluation['task_sources']:
            raise ValueError('Selection does not match the actual editing/physical ledger')
        for task in ledger['tasks'].values():
            session=resolve(ledger_path.parent,task['session_json']);add(session.parent)
        for row in evaluation['points']:add(resolve(Path(entry['validation_selection']).parent,row['run_directory']))
    declared={(p['task_id'],p['configuration_id'])for p in value['plan']['points']}
    for point in value['registry']['configurations']:
        if (point['contract']['task_id'],point['configuration_id'])in declared:
            if point.get('frozen_source_pack'):add(point['frozen_source_pack'])
            if point.get('gold_control'):add(point['gold_control']['run_directory'])
    return [file_row(p)for p in sorted(files)]


def audit(entry,value,closed):
    training,current=close_run(entry,value)
    if current!=check_closed(closed,entry):raise ValueError('Actual closed run/checkpoint bytes changed')
    selected=validate_selection(entry,training,ROOT,value['registry'],value['plan'],Path(value['plan_path']))
    raw=verification_files(entry,value,training,selected)
    return {'status':'ACTUAL_E4_COLD_RUN_AUDIT_COMPLETE','audited_at_utc':now(),'method':entry['method'],'seed':entry['seed'],
        'draft_sha256':value['draft_sha256'],'closed_inventory':current,
        'training':{k:v for k,v in training.items()if k!='checkpoints'},'selection':selected,
        'verification_files':raw,'registry_sha256':value['registry_sha256'],
        'implementation_sha256':value['implementation_sha256'],
        'completion_implementation_sha256':value['completion_implementation_sha256'],
        'new_model_or_EDA_calls':0,'deleted_files':0}


def save_once(path,value):
    path=ordinary(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x')as stream:stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')
    path.chmod(0o444)


def request(body):
    value=header(body['draft'],body['draft_sha256']);operation=body['operation']
    if operation=='header':return {k:v for k,v in value.items()if k not in ('registry','plan')}
    entry=entry_for(value,body['method'],body['seed']);key=entry['method']+'_'+str(entry['seed'])
    if operation=='close':
        _,closed=close_run(entry,value);path=AUDIT_ROOT/'closed'/(key+'.json')
        if path.exists():
            if read(path)!=closed:raise ValueError('The previously closed original inventory changed')
        else:save_once(path,closed)
        return {'closed_inventory':closed,'closed_path':str(path),'closed_sha256':file_digest(path),'closed_bytes':path.stat().st_size}
    if operation in ('restore-plan','audit'):
        path=AUDIT_ROOT/'closed'/(key+'.json')
        if path.stat().st_mode&0o222 or read(path)!=body['closed_inventory']:
            raise ValueError('Restore must match the independently closed server inventory')
    if operation=='restore-plan':return restore_plan(entry,body['closed_inventory'])
    if operation=='audit':
        result=audit(entry,value,body['closed_inventory']);path=AUDIT_ROOT/'audits'/body['session']/key/'audit.json'
        # An explicit new audit session is required; never overwrite old results.
        save_once(path,result);return {'audit':result,'audit_path':str(path),'audit_sha256':file_digest(path)}
    if operation=='recheck':
        path=ordinary(body['audit_path'])
        if not path.is_relative_to(AUDIT_ROOT/'audits')or file_digest(path)!=body['audit_sha256']:
            raise ValueError('The trusted actual audit is absent or changed')
        result=read(path)
        if (result['status']!='ACTUAL_E4_COLD_RUN_AUDIT_COMPLETE' or result['draft_sha256']!=value['draft_sha256']
            or result['method']!=entry['method']or result['seed']!=entry['seed']
            or any(result[k]!=value[k]for k in ('implementation_sha256','completion_implementation_sha256','registry_sha256'))):
            raise ValueError('Actual audit identity/code/registry changed')
        for row in result['verification_files']:
            if file_row(row['path'])!=row:raise ValueError('Audited raw/input bytes changed; completion is blocked')
        for name,keyname in [('adapter_model.safetensors','adapter_sha256'),('adapter_config.json','adapter_config_sha256')]:
            if file_digest(Path(result['selection']['selected_adapter'])/name)!=result['selection'][keyname]:
                raise ValueError('The selected actual adapter is not present with its original identity')
        return {'status':'ACTUAL_AUDITED_RAW_BYTES_REOPENED','audit_path':str(path),'audit_sha256':body['audit_sha256'],
            'raw_files_reopened':len(result['verification_files']),'new_model_or_EDA_calls':0}
    raise ValueError('Unknown cold-audit operation')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',action='store_true',required=True)
    args=parser.parse_args();started=time.monotonic();cpu=time.process_time()
    body=json.load(sys.stdin)
    if body.get('session') and (not body['session'].replace('_','').replace('-','').isalnum()or len(body['session'])>80):
        raise ValueError('One plain audit session ID required')
    if hasattr(os,'sched_getaffinity'):
        os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2])
    result=request(body);result['audit_operation_costs']={'wall_seconds':time.monotonic()-started,
        'process_CPU_seconds':time.process_time()-cpu,'GPU_seconds':0.,'scope':'This CPU audit/restore-plan invocation only'}
    print(json.dumps(result,allow_nan=False))


if __name__=='__main__':main()
