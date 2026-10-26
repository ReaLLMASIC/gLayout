"""Development-only FVF full-module point, separate from main E3/E1 LIVE.

prepare copies a single independently bound capsule without EDA. run requires
separate operator authorization; this file has no model or formal dispatch path.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.prepare_fvf_supplement import SERVER,TASK,EDITABLE
from scripts.qualify_fvf_supplement import full_rc_audit,sha,read,save
from src.domain_runner import source_contents

CONTROL=SERVER/'runs/development/FVF_fullmodule_control/anchor_v2/control.json'
CONTROL_SHA='4f39321520caad72041d0b5ab426324f5514ae6e20cc34924e69d63ef9e49560'
AREA={'id':TASK+'_area_min','metric':'area','unit':'um2','direction':'min','corner_aggregation':'worst'}


def binding():
    if ROOT!=SERVER:raise ValueError('Only the original private execution endpoint')
    if sha(CONTROL)!=CONTROL_SHA:raise ValueError('The actually qualified anchor input binding changed')
    control=read(CONTROL);actual=read(CONTROL.parent/'run.json')
    if (actual['status']!='COMPLETE_POSITIVE_CONTROL' or not actual['geometry']['equal']
            or not actual['current_Store']['S2'] or actual['full_RC_audit']['status']!='RC_DEVICE_GRAPH_MATCH'):
        raise ValueError('The full-module/vendor transport control is not established')
    for name,value in control['implementation_sha256'].items():
        if sha(ROOT/name)!=value:raise ValueError('Qualified control implementation drifted: '+name)
    for name,value in control['trusted_sha256'].items():
        if sha(Path(control['trusted'])/name)!=value:raise ValueError('Actual qualified trusted bytes drifted: '+name)
    return control


def selected_point(task,ident):
    if (task['task_id']!=TASK or task['target']!='fvf' or task['editable_paths']!=[EDITABLE]
            or task['entrypoint']!='generator.py' or task['representation']!='G2'
            or task.get('formal_dispatch_allowed') is not False):
        raise ValueError('Only the separate development full-module FVF task is supported')
    original=read(Path(task['qualified_domain_origin'])/'private/task.json')
    if len(task['configurations'])!=25 or len({p['configuration_id'] for p in task['configurations']})!=25:
        raise ValueError('The original fixed25 domain is required')
    expected=copy.deepcopy(original['configurations'])
    for p in expected:p['contract'].update(task_id=TASK,objective=copy.deepcopy(AREA))
    if task['configurations']!=expected:raise ValueError('Independent N, parameters, roles, bench, specifications or analyses changed')
    matches=[p for p in task['configurations'] if p['configuration_id']==ident]
    if len(matches)!=1:raise ValueError('A single declared configuration is required')
    return matches[0]


def verify_source(task,control,source):
    if sorted(task['source_files'])!=sorted(control['source_files']):raise ValueError('Source closure changed')
    actual=source_contents(source,task['source_files'],binary=True)
    for name in task['source_files']:
        origin=task.get('source_overrides',{}).get(name) or task.get('frozen_source_overrides',{}).get(name)
        origin=Path(origin) if origin else Path(task['source_pack_base'])/name
        initial=origin.read_bytes()
        if hashlib.sha256(initial).hexdigest()!=control['source_sha256'][name]:raise ValueError('Initial full source/readonly closure differs: '+name)
        if name!=EDITABLE and actual[name]!=initial:raise ValueError('Frozen source/caller/library changed: '+name)
    return actual


def prepare_inputs(task_path,ident,output,source=None,*,supplement=None):
    control=binding();task=read(task_path)
    if supplement is None:point=selected_point(task,ident)
    else:
        # Only the separately verified fixed FVF manifest can use snapshotted
        # reference paths. The old development interface is unchanged.
        from scripts.fvf_supplement_episode import bound_task
        bound_task(supplement,task_path)
        point=next(p for p in task['configurations'] if p['configuration_id']==ident)
    output=Path(output);output.mkdir(parents=True,exist_ok=False);output.chmod(0o700)
    if source is None:
        from scripts.e3_task_prepare import capsule
        source=output/'source';capsule(Path(task_path),source)
    else:source=Path(source)
    expected=verify_source(task,control,source)
    origin=Path(supplement['trusted_template']) if supplement else Path(control['trusted'])
    if supplement:
        for name,value in control['trusted_sha256'].items():
            if sha(origin/name)!=value:raise ValueError('Frozen supplement changed its qualified trusted closure: '+name)
    trusted=output/'trusted';shutil.copytree(origin,trusted)
    for p in [trusted,*(x for x in trusted.rglob('*') if x.is_dir())]:p.chmod(p.stat().st_mode|0o700)
    for name,text in [('contract.json',json.dumps(point['contract'],indent=2)+'\n'),('reference.spice',Path(point['reference_file']).read_text())]:
        p=trusted/name;p.chmod(0o644);p.write_text(text)
    files=sorted(str(p.relative_to(trusted)) for p in trusted.rglob('*') if p.is_file())
    if files!=control['trusted_files']:raise ValueError('Qualified vendor trusted closure changed')
    meta=read(trusted/'meta.json')
    if meta['bench_kind']!='vendor_ota' or meta['circuit']!='fvf' or meta['top_cell']!=task['top_cell']:
        raise ValueError('Only the actual qualified vendor-FVF transport is supported')
    return task,point,source,trusted,files,expected


def stage_costs(run):
    manifest=read(run/'manifest.json');result={}
    for stage in ['candidate','trusted']:
        m=manifest.get(stage) or {};p=run/(stage+'_stage/resource_usage.json');u=read(p) if p.is_file() else None
        if not m and u is None:continue
        result[stage]={'wall_seconds':m.get('wall_seconds',u.get('wall_seconds') if u else None),
            'returncode':m.get('returncode',u.get('returncode') if u else None),
            'waited_child_CPU_seconds':u['child_user_cpu_seconds']+u['child_system_cpu_seconds'] if u else None,
            'CPU_scope':'actual waited child processes' if u else 'missing; no allocated-CPU estimate'}
    return result


def _evaluate(task_path,configuration_id,output,source=None,deadline=None,*,supplement=None):
    if ROOT!=SERVER:raise ValueError('Physical point runs only on the private execution endpoint')
    from src.candidate_executor import CandidateExecutor
    from src.domain_runner import inspect_point
    from src.training import TrustedPhysicalStore
    from scripts.qualify_telescopic_supplement import resource_gate
    from scripts.e1_matched_runner import visible_feedback
    started,cpu=time.monotonic(),time.process_time();end=time.time()+1800
    if deadline is not None:end=min(end,datetime.fromisoformat(deadline.replace('Z','+00:00')).timestamp())
    task,point,source,trusted,files,expected=prepare_inputs(task_path,configuration_id,output,source,
        **({'supplement':supplement} if supplement is not None else {}))
    formal=supplement is not None and supplement['status']=='FROZEN_E3_FVF_SUPPLEMENT'
    output=Path(output);run=None;result=None
    row={'task_id':task['task_id'],'configuration_id':configuration_id,'fidelity':'pex_spice',
        'objective':None,'objective_definition':AREA,'formal_trial':formal,'new_model_calls':0,
        'checked':{'S0':False,'S1':False,'S2':False,'execution_integrity':'incomplete','failure_class':'unknown'},
        'physical_feedback':None,'resource_samples':[],'physical_call_reservations':0}
    try:
        resource_gate(end,row['resource_samples'])
        row['physical_call_reservations']=1;save(output/'point.json',row)
        executor=CandidateExecutor(ROOT/'runtime/GLdev',output/'physical',ROOT/'runtime/magic-8.3.685',timeout=900)
        result=executor.execute(source_dir=source,source_paths=task['source_files'],entrypoint=task['entrypoint'],
            representation='G2',configuration={'parameters':point['parameters']},trusted_dir=trusted,trusted_paths=files,fidelity='pex_spice',
            # Existing frozen executor vocabulary is retained. The dedicated
            # API fixes the formal E3 role and adds the separate cohort identity;
            # callers cannot supply an arbitrary execution phase or source role.
            phase='formal_E3' if formal else 'development_FVF_supplement_point',context={
                **({'cohort_id':supplement['cohort_id'],'supplement_freeze_id':supplement.get('freeze_id')} if supplement else {}),
                'source_role':'formal_E3_candidate' if formal else 'trusted_evaluator_control','candidate_id':task['task_id'],
                'initial_state_id':task['task_id'],'parent_lineage':task['parent_lineage'],'configuration_id':configuration_id,
                'reference_id':point['reference_id'],'pdk_revision':'0fe599b2afb6708d281543108caf8310912f54af'},
            generation_timeout_seconds=240,evaluator_timeout_seconds=900,
            execution_deadline_utc=datetime.fromtimestamp(end,timezone.utc).isoformat())
        run=Path(result['run_directory'])
        if read(run/'manifest.json')['status']=='BUDGET_EXHAUSTED':
            row['checked']={'S0':False,'S1':False,'S2':False,'execution_integrity':'budget_exhausted',
                'failure_class':'budget','reason':'The absolute UTC deadline stopped this physical call'}
        else:row['checked']=inspect_point(result,point,expected,{'parameters':point['parameters']},gold_control_check=False)
        row['physical_feedback']=visible_feedback(result)
        if row['checked']['S1']:
            audit=full_rc_audit(run,point,output);row['full_RC_device_port_audit']=audit
            if audit['status']!='RC_DEVICE_GRAPH_MATCH':raise ValueError('Mandatory actual fullRC/deck audit did not pass')
        if row['checked']['S2']:
            dry={**point,'parameters':{'parameters':point['parameters']},'editable_paths':[EDITABLE],'lineage_editable_paths':[EDITABLE],
                'frozen_source_files':[n for n in task['source_files'] if n!=EDITABLE],'frozen_source_pack':str(source),
                'intent_reference_path':'reference.spice','trusted_evaluator_files':{n:(trusted/n).read_text() for n in files}}
            if formal:
                manifest=read(run/'manifest.json')
                if (manifest['phase']!='formal_E3' or manifest['source_role']!='formal_E3_candidate'
                        or manifest['context']['cohort_id']!=supplement['cohort_id']):
                    raise ValueError('Formal FVF executor provenance differs from the dedicated API')
                store={**TrustedPhysicalStore._inspect_execution_run(run,dry,{EDITABLE:(source/EDITABLE).read_text()}),
                    'admitted_to_formal_training':False,'source_role':'formal_E3_FVF_supplement_evaluation'}
            else:store=TrustedPhysicalStore.inspect_development_run(run,dry,{EDITABLE:(source/EDITABLE).read_text()})
            row['current_Store']=store
            if not store['S2']:raise ValueError('Current Store did not establish the same physical point')
            row['objective']=store['objective']
    except Exception as error:
        row.update(error=type(error).__name__+': '+str(error))
        budget=isinstance(error,TimeoutError) and time.time()>=end
        row['checked'].update(S2=False,execution_integrity='budget_exhausted' if budget else 'incomplete',
            failure_class='budget' if budget else 'unknown',reason=row['error'])
    finally:
        if run is None:
            found=list((output/'physical').glob('*/manifest.json'))
            if len(found)==1:run=found[0].parent
        if run is not None:
            row['run_directory']=str(run)
            try:row['actual_costs_by_stage']=stage_costs(run)
            except (ValueError,OSError,KeyError,TypeError) as error:row['cost_telemetry_error']=str(error)
        row.update(point_wall_seconds=time.monotonic()-started,point_parent_CPU_seconds=time.process_time()-cpu,
            created_at_utc=datetime.now(timezone.utc).isoformat(),automatic_retry=False)
        save(output/'point.json',row)
    return row


def evaluate(task_path,configuration_id,output,source=None,deadline=None):
    """Original development-only entry; existing inputs and records keep their meaning."""
    return _evaluate(task_path,configuration_id,output,source,deadline)


def evaluate_supplement(manifest_path,configuration_id,output,source=None,deadline=None,*,formal=False):
    """Fixed FVF cohort API; never accepts caller-defined phase/role/bench."""
    output=Path(output)
    if output.exists():raise ValueError('A prior point attempt is never overwritten or automatically retried')
    began,cpu=time.monotonic(),time.process_time();error=None;row=None
    try:
        from scripts.fvf_supplement_episode import verify_manifest
        manifest=verify_manifest(manifest_path,formal=formal)
        if formal:
            task=read(manifest['task']);point=next(p for p in task['configurations'] if p['configuration_id']==configuration_id)
            if point['role']=='hidden':
                from scripts.fvf_supplement_episode import require_hidden_source
                require_hidden_source(manifest,source)
        row=_evaluate(Path(manifest['task']),configuration_id,output,source,deadline,supplement=manifest)
        return row
    except Exception as failure:
        error=type(failure).__name__+': '+str(failure);raise
    finally:
        output.mkdir(parents=True,exist_ok=True)
        save(output/'point_api_invocation.json',{'formal_supplement':formal,'configuration_id':configuration_id,
            'wall_seconds':time.monotonic()-began,'parent_CPU_seconds':time.process_time()-cpu,
            'error':error,'returned_point':row is not None,
            'scope':'Inclusive API preparation/verification+point; overlaps point telemetry, do not add twice',
            'actual_physical_calls':row['physical_call_reservations'] if row is not None else None,
            'missing_physical_count_note':None if row is not None else 'No count inferred from an exception; inspect any retained executor invocation'})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=['prepare','run'],required=True)
    p.add_argument('--task',type=Path,required=True);p.add_argument('--configuration',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path);a=p.parse_args()
    if a.mode=='prepare':
        task,point,source,trusted,files,_=prepare_inputs(a.task,a.configuration,a.output,a.source)
        value={'status':'DEVELOPMENT_FVF_POINT_PREPARED_NO_EDA','task_id':task['task_id'],'source_files':len(task['source_files']),
            'trusted_files':len(files),'E1_binding_required':False,'new_EDA_or_model_calls':0,'formal_dispatch_supported':False}
    else:value=evaluate(a.task,a.configuration,a.output,a.source)
    print(json.dumps(value,indent=2,allow_nan=False))
