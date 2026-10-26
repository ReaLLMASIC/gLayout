#!/usr/bin/env python3
"""Matched E1 policy bridge and trusted point/domain execution.

The backend alone reads task tables and independent evaluators. Development is
available now; formal dispatch requires an explicit separate FROZEN_E1 manifest.
"""
import argparse
import copy
from datetime import datetime,timedelta,timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.model_adapter import check_utc_budget,validate_action
from src.candidate_executor import CandidateExecutor,apply_source_patch
from src.domain_runner import inspect_point,source_contents
from src.measurement import assess

SSH=['ssh','-i','~/.ssh/cbl_server_key','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=12','cbl-server']
REMOTE='/srv/code-behind-layout'
STAGES=('search','post_freeze_diagnostic','hidden')

class BackendInfrastructureError(RuntimeError):pass


def now():return datetime.now(timezone.utc)
def save(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def read(path):return json.loads(path.read_text())
def project(path):return Path(path) if Path(path).is_absolute() else ROOT/path

def budget_check(manifest):
    expected={'wall_seconds':1200,'decisions':10,'physical_evaluations':3,'maximum_context_tokens':8192,'maximum_output_tokens':1024}
    if manifest['budget']!=expected:raise ValueError('The calibrated matched E1 budget changed')
    if manifest['visible_history_policy']!='current_source_and_feedback_v1':raise ValueError('Unknown common visible state')


def verify_implementation(manifest):
    if manifest['status']!='FROZEN_E1':return
    bindings=manifest.get('implementation_sha256')
    if not isinstance(bindings,dict) or not bindings:raise BackendInfrastructureError('Frozen E1 manifest has no implementation binding')
    for name,expected in bindings.items():
        filename=ROOT/name
        if not filename.is_file() or hashlib.sha256(filename.read_bytes()).hexdigest()!=expected:
            raise BackendInfrastructureError('Frozen E1 implementation differs from live source: '+name)


def initialize(request):
    manifest_path=project(request['manifest']);manifest=read(manifest_path);budget_check(manifest)
    formal=request.get('formal',False)
    role=request.get('driver_role','tested_policy')
    if role not in ('tested_policy','engineering_mechanical_control') or formal and role!='tested_policy':raise ValueError('Unknown driver role')
    if formal and not (manifest['status']=='FROZEN_E1' and manifest['formal_dispatch'] is True):raise ValueError('Formal E1 dispatch requires its explicit reviewed freeze')
    if not formal and manifest['status'] not in ('DRAFT_E1_RUNNER','FROZEN_E1'):raise ValueError('Unknown manifest state')
    verify_implementation(manifest)
    task_id=request['task_id'];method=request['method'];trial=str(request['trial_id'])
    if not re.fullmatch(r'[A-Za-z0-9_]+',task_id) or not re.fullmatch(r'[A-Za-z0-9_-]+',trial):raise ValueError('Invalid task/trial identifier')
    if method not in manifest['methods'] or method not in ('G0','G1','G2'):raise ValueError('Unknown method')
    if manifest['task_ids'] and task_id not in manifest['task_ids']:raise ValueError('Task is outside the freeze')
    packet_root=project(manifest['packet_root']);task=read(packet_root/'private'/task_id/'task.json');packet=read(packet_root/'public'/task_id/(method+'.json'))
    if any(not p['contract'].get('analysis_contracts') for p in task['configurations']):raise ValueError('Every point needs complete declared analysis coverage')
    if formal and not task.get('formal_admission'):raise ValueError('The frozen task has not been admitted')
    ident=now().strftime('%Y%m%dT%H%M%S%fZ_')+uuid.uuid4().hex[:8]
    out=ROOT/('runs/formal/E1' if formal else 'runs/development/E1_matched')/ident
    private=out/'private';private.mkdir(parents=True,mode=0o700);(out/'public').mkdir();(private/'current_source').mkdir()
    (private/'current_source/generator.py').write_text(packet['visible_sources']['generator.py'])
    deadline=now()+timedelta(seconds=manifest['budget']['wall_seconds']);packet['budget']={**manifest['budget'],'deadline_utc':deadline.isoformat()}
    model=read(project(manifest['model_config']));model['visible_history_policy']=manifest['visible_history_policy']
    save(private/'freeze_manifest.json',manifest);save(private/'task.json',task);save(private/'packet.json',packet);save(private/'model_config.json',model)
    state={'episode_id':ident,'task_id':task_id,'method':method,'trial_id':trial,'stratum':task['stratum'],
        'source_group':task['logical_group'],'merged_source_group':task['merge_sensitivity_group'],
        'phase':'formal_E1' if formal else 'development_E1_'+role,'driver_role':role,'status':'RUNNING','created_at_utc':now().isoformat(),
        'deadline_utc':deadline.isoformat(),'decisions':0,'selection_calls':0,'events':[],'points':{},'sealed':False,
        'first_verified_times_seconds':{'S0':None,'S1':None,'S2':None},'costs_by_stage':{s:{'physical_calls':0,'stage_wall_seconds':0.,'waited_child_CPU_seconds':0.,'missing_CPU_records':0,'capsule_preparation_wall_seconds':0.,'capsule_preparation_CPU_seconds':0.,'primitive_geometry_wall_seconds':0.,'primitive_geometry_CPU_seconds':0.,'primitive_geometry_is_subset_of_capsule_preparation':True} for s in STAGES},
        'post_freeze_status':'NOT_STARTED','hidden_started':False,'formal_trial':formal}
    save(private/'state.json',state);return {'episode_directory':str(out),'packet':packet,'model_config':model,
        'implementation_sha256':manifest.get('implementation_sha256')}


class Backend:
    def __init__(self,directory):
        self.out=project(directory);self.private=self.out/'private';self.task=read(self.private/'task.json');self.packet=read(self.private/'packet.json');self.state=read(self.private/'state.json')
        self.points={p['configuration_id']:p for p in self.task['configurations']}
        if self.state.get('in_flight_point'):raise RuntimeError('A prior physical point is unfinished; reconcile its retained execution before resuming; never repeat hidden silently')

    def write(self):save(self.private/'state.json',self.state);save(self.out/'public/episode.json',self.summary())
    def sources(self):return {'generator.py':(self.private/'current_source/generator.py').read_text()}
    def elapsed(self):return (now()-datetime.fromisoformat(self.state['created_at_utc'])).total_seconds()

    def current(self):return {'current_sources':self.sources(),'status':self.state['status']}

    def prepare_capsule(self,ident,stage):
        capsule=self.private/'capsules'/ident
        if not capsule.exists():
            command=[sys.executable,str(ROOT/'scripts/run_eda_probe.py'),'--script','materialize_e1_packets.py','--timeout','300','--',
                '--capsule',str(self.private/'task.json'),'--configuration',ident,'--method',self.state['method'],'--output',str(capsule)]
            logs=self.private/'preparation_logs';logs.mkdir(exist_ok=True)
            with (logs/(ident+'.log')).open('w') as log:run=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
            first=json.loads((logs/(ident+'.log')).read_text().splitlines()[0]);producer=Path(first['output'])
            usage=read(producer/'resource_usage.json');costs=self.state['costs_by_stage'][stage]
            costs['capsule_preparation_wall_seconds']+=usage['wall_seconds']
            costs['capsule_preparation_CPU_seconds']+=sum(usage[k] for k in ('self_user_cpu_seconds','self_system_cpu_seconds','children_user_cpu_seconds','children_system_cpu_seconds'))
            if run.returncode:
                self.write();raise RuntimeError('Current-z primitive capsule preparation failed; see '+str(logs/(ident+'.log')))
            generated=read(capsule/'backend_manifest.json').get('library_generation_cost')
            if generated:
                costs['primitive_geometry_wall_seconds']+=generated['wall_seconds'];costs['primitive_geometry_CPU_seconds']+=generated['process_CPU_seconds']
            save(capsule/'producer.json',{'run':str(producer),'usage':usage});self.write()
        return capsule

    def inspect(self,result,point,source,configuration,fidelity):
        run=Path(result['run_directory']);record=result.get('physical_result') or {}
        if record.get('observation',{}).get('interface_error'):
            provenance=read(run/'evidence/provenance.json')
            if provenance['producer']!='trusted_container' or provenance['candidate_container_stopped'] is not True:raise ValueError('Missing trusted boundary')
            return {'S0':True,'S1':False,'S2':False,'execution_integrity':'valid','failure_class':'candidate','reason':record['observation']['interface_error']}
        if fidelity=='basic' and record and record['assessment']['S1']:
            from src.device_intent import compare_device_intent
            from src.report_parsers import magic_drc_report,netgen_lvs_report
            if source_contents(run/'source',read(run/'manifest.json')['source_files'],binary=True)!=source:raise ValueError('Executed source differs')
            evidence=run/'evidence';drc=read(evidence/'drc/metadata.json')
            intent=compare_device_intent((evidence/'extracted_lvs.spice').read_text(),(evidence/'reference.spice').read_text())
            clean=(drc['completed'] and drc['style']=='drc(full)' and magic_drc_report((evidence/'drc/direct_drc.rpt').read_text())['is_clean']
                and netgen_lvs_report((evidence/'lvs.rpt').read_text())['is_clean'] and intent['is_clean'])
            if not clean:raise ValueError('Basic summary contradicts actual independent physical reports')
            return {'S0':True,'S1':True,'S2':False,'execution_integrity':'valid','failure_class':None,'reason':'Completed requested basic correctness checks; S2 not evaluated'}
        return inspect_point(result,point,source,configuration)

    def evaluate(self,ident,fidelity,stage):
        manifest=read(self.private/'freeze_manifest.json');verify_implementation(manifest)
        if stage=='search':
            if self.state['sealed']:raise ValueError('Sealed source cannot return to policy search')
            check_utc_budget(self.packet)
            if self.state['selection_calls']>=self.packet['budget']['physical_evaluations']:raise ValueError('Physical point budget exhausted')
            if ident not in self.packet['visible_configurations']:raise ValueError('Policy cannot select hidden configurations')
        point=self.points[ident];capsule=self.prepare_capsule(ident,stage)
        if stage=='search':check_utc_budget(self.packet)
        source=capsule/'source';(source/'generator.py').chmod(0o644);(source/'generator.py').write_text(self.sources()['generator.py'])
        expected=source_contents(source,read(capsule/'backend_manifest.json')['source_paths'],binary=True)
        configuration=read(capsule/'configuration.json');call=len(self.state['events']);work=self.private/'point_inputs'/('%04d_'%call+ident+'_'+uuid.uuid4().hex[:8])
        from src.e1_benchmarks import build_trusted
        trusted=work/'trusted';files=build_trusted(self.task,point,trusted)
        executor=CandidateExecutor(ROOT/'runtime/GLdev',self.private/'physical',ROOT/'runtime/magic-8.3.685',timeout=720)
        before=now();source_text=self.sources()['generator.py']
        verify_implementation(manifest)
        if stage=='search':check_utc_budget(self.packet);self.state['selection_calls']+=1
        self.state['in_flight_point']={'configuration_id':ident,'stage':stage,'started_at_utc':before.isoformat()}
        self.state['costs_by_stage'][stage]['physical_calls']+=1;self.write()
        result=executor.execute(source_dir=source,source_paths=list(expected),entrypoint='generator.py',representation=self.state['method'],
            configuration=configuration,trusted_dir=trusted,trusted_paths=files,library_dir=capsule/'library',
            library_paths=read(capsule/'backend_manifest.json')['library_paths'],fidelity=fidelity,phase=self.state['phase'],
            context={'source_role':'formal_E1_candidate' if self.state['formal_trial'] else 'development_E1_candidate','candidate_id':self.state['episode_id'],
                'initial_state_id':self.task['task_id'],'parent_lineage':self.task['target_logic_id'],'configuration_id':ident,'reference_id':point['reference_id'],
                'pdk_revision':'0fe599b2afb6708d281543108caf8310912f54af','stage':stage},
            generation_timeout_seconds=240,evaluator_timeout_seconds=720,
            **({'execution_deadline_utc':self.state['deadline_utc']} if stage=='search' else {}))
        finished=now();run=Path(result['run_directory']);manifest=read(run/'manifest.json')
        try:
            if manifest['status']=='BUDGET_EXHAUSTED':
                checked={'S0':False,'S1':False,'S2':False,'execution_integrity':'budget_exhausted','failure_class':'budget','reason':'The actual common UTC search budget stopped physical execution; no circuit failure label'}
            else:checked=self.inspect(result,point,expected,configuration,fidelity)
        except (KeyError,ValueError,OSError,TypeError) as error:
            checked={'S0':False,'S1':False,'S2':False,'execution_integrity':'incomplete','failure_class':'unknown','reason':str(error)}
        costs=self.state['costs_by_stage'][stage]
        for name in ('candidate','trusted'):
            if name not in manifest:continue
            costs['stage_wall_seconds']+=manifest[name]['wall_seconds'];usage=run/(name+'_stage/resource_usage.json')
            if usage.exists():
                u=read(usage);costs['waited_child_CPU_seconds']+=u['child_user_cpu_seconds']+u['child_system_cpu_seconds']
            else:costs['missing_CPU_records']+=1
        complete=checked['execution_integrity']=='valid' and checked['failure_class'] in (None,'candidate')
        record={'configuration_id':ident,'role':point['role'],'fidelity':fidelity,'stage':stage,'run_directory':str(run),
            'source_text':source_text,'started_at_utc':before.isoformat(),'ended_at_utc':finished.isoformat(),'complete':complete,**checked}
        self.state['events'].append(record);self.state['points'][ident]=record;self.state['in_flight_point']=None
        if stage=='search' and finished<=datetime.fromisoformat(self.state['deadline_utc']):
            elapsed=(finished-datetime.fromisoformat(self.state['created_at_utc'])).total_seconds()
            for tier in ('S0','S1','S2'):
                if checked[tier] and self.state['first_verified_times_seconds'][tier] is None:self.state['first_verified_times_seconds'][tier]=elapsed
        self.write()
        if not complete and stage=='search':
            self.state['status']='BUDGET_EXHAUSTED' if checked['failure_class']=='budget' else 'INCOMPLETE_UNKNOWN';self.write()
        return {k:record[k] for k in ('configuration_id','fidelity','complete','S0','S1','S2','execution_integrity','failure_class','reason') if k in record}|{'physical_feedback':visible_feedback(result)}

    def action(self,action):
        if self.state['sealed']:raise ValueError('Search is sealed')
        check_utc_budget(self.packet);validate_action(action,self.packet)
        if self.state['decisions']>=self.packet['budget']['decisions']:raise ValueError('Decision budget exhausted')
        self.state['decisions']+=1;kind=action['action']
        actions=self.private/'actions';actions.mkdir(exist_ok=True);save(actions/('%03d.json'%self.state['decisions']),action);self.write()
        if kind=='read_source':response={'path':action['path'],'content':self.sources()[action['path']]}
        elif kind=='propose_patch':apply_source_patch(self.private/'current_source',action['patch'],['generator.py']);response={'patch_applied':True}
        elif kind=='request_evaluation':
            if len(action['configuration_ids'])>self.packet['budget']['physical_evaluations']-self.state['selection_calls']:raise ValueError('Request exceeds remaining point budget')
            response={}
            for ident in action['configuration_ids']:
                response[ident]=self.evaluate(ident,action['fidelity'],'search')
                if not response[ident]['complete']:break
        else:self.seal('SEARCH_FINISHED');response={'finished':True}
        self.write();return response

    def seal(self,status,policy_statistics=None):
        if policy_statistics is not None:self.state['costs_by_stage']['policy']=policy_statistics
        if not self.state['sealed']:
            (self.private/'sealed_generator.py').write_text(self.sources()['generator.py']);self.state['sealed']=True
            self.state['status']=status;self.state['search_ended_at_utc']=now().isoformat();self.state['observed_search_wall_seconds']=self.elapsed();self.write()
        self.write();return self.summary()

    def post_freeze(self,anchor_only=False):
        if not self.state['sealed']:raise ValueError('Seal one immutable final source before diagnostics or hidden evaluation')
        if self.sources()['generator.py']!=(self.private/'sealed_generator.py').read_text():raise ValueError('Frozen source changed')
        self.state['post_freeze_status']='RUNNING';self.write()
        selected=[self.points['anchor']] if anchor_only else list(self.points.values())
        for point in selected:
            ident=point['configuration_id'];previous=self.state['points'].get(ident)
            if previous and previous['source_text']==self.sources()['generator.py'] and not previous['complete'] and previous['failure_class']!='budget':
                self.state['post_freeze_status']='INCOMPLETE_UNKNOWN';self.write();return self.summary()
            if previous and previous['source_text']==self.sources()['generator.py'] and previous['complete'] and (previous['fidelity']=='pex_spice' or not previous['S1']):continue
            if point['role']=='hidden':
                if self.state.get('hidden_complete'):raise ValueError('Hidden domain cannot be evaluated twice')
                self.state['hidden_started']=True
            record=self.evaluate(ident,'pex_spice','hidden' if point['role']=='hidden' else 'post_freeze_diagnostic')
            if not record['complete']:
                self.state['post_freeze_status']='INCOMPLETE_UNKNOWN';self.write();return self.summary()
        self.state['post_freeze_status']='ANCHOR_ONLY_DEVELOPMENT_SMOKE' if anchor_only else 'COMPLETE'
        if not anchor_only:self.state['hidden_complete']=True
        self.write();return self.summary()

    def summary(self):
        sealed_source=(self.private/'sealed_generator.py').read_text() if self.state['sealed'] else None
        anchor=self.state['points'].get('anchor',{})
        if anchor.get('source_text')!=sealed_source:anchor={}
        hidden=[v for v in self.state['points'].values() if v['role']=='hidden' and v['source_text']==sealed_source]
        normalized={'SEARCH_FINISHED':'COMPLETED','ENGINEERING_MECHANICAL_CONTROL_COMPLETE':'COMPLETED',
            'DECISION_BUDGET_EXHAUSTED':'BUDGET_EXHAUSTED','BUDGET_EXHAUSTED':'BUDGET_EXHAUSTED','MODEL_FAILED':'MODEL_FAILURE',
            'INCOMPLETE_UNKNOWN':'INFRASTRUCTURE_PAUSED','RUNNING':'NOT_RUN'}.get(self.state['status'],'INFRASTRUCTURE_PAUSED')
        return {k:self.state[k] for k in ('task_id','method','trial_id','stratum','source_group','merged_source_group','status','first_verified_times_seconds','costs_by_stage','post_freeze_status')}|{
            'analysis_search_status':normalized,'driver_role':self.state['driver_role'],
            'episode_directory':str(self.out),'phase':self.state['phase'],'search_budget_seconds':self.packet['budget']['wall_seconds'],
            'observed_search_wall_seconds':self.state.get('observed_search_wall_seconds',self.elapsed()),
            'final_anchor':{**{k:bool(anchor.get(k,False)) for k in ('S0','S1','S2')},'complete':bool(anchor.get('complete',False))},
            'hidden':{'declared':16,'known':sum(v['complete'] for v in hidden),'S2_passed':sum(v['S2'] and v['complete'] for v in hidden)},
            'selection_calls':self.state['selection_calls'],'decisions':self.state['decisions'],'sealed':self.state['sealed']}


def failure_diagnostics(result):
    """Bounded actual diagnostic samples; full reports remain in trusted raw."""
    run=Path(result['run_directory']);raw=result.get('physical_result') or {}
    checks=raw.get('observation',{}).get('checks',{});diagnostics={}
    if result['status'] in ('CANDIDATE_FAILED','REJECTED_OUTPUT'):
        console=run/'candidate_stage/console.log'
        if console.is_file():
            text=console.read_text(errors='replace');lines=text.splitlines()
            starts=[i for i,line in enumerate(lines) if line.startswith('Traceback (most recent call last):')]
            trace=lines[starts[-1]:] if starts else lines
            shown='\n'.join(trace[-12:])[-2000:]
            diagnostics['generation']={'status':result['status'],'trace_tail':shown,
                'total_console_lines':len(lines),'total_diagnostic_lines':len(trace),
                'diagnostic_lines_omitted':max(0,len(trace)-12),
                'diagnostic_characters_shown':len(shown),'diagnostic_characters_total':len('\n'.join(trace)),
                'sampling':'Last12 diagnostic lines, at most2000characters; not a failure reclassification'}
    report=run/'evidence/drc/direct_drc.rpt'
    if checks.get('drc') is False and report.is_file():
        from src.report_parsers import magic_drc_report
        text=report.read_text();parsed=magic_drc_report(text);groups=[]
        for line in text.splitlines()[2:]:
            if not line.strip() or set(line.strip())=={'-'}:continue
            if re.fullmatch(r'(?:[-+]?\d+(?:\.\d+)?um\s*){4}',line.strip()):
                if groups:groups[-1]['coordinate_boxes'].append(line.strip())
            else:groups.append({'rule':line.strip(),'coordinate_boxes':[]})
        sample=[{'rule':g['rule'],'coordinate_boxes':g['coordinate_boxes'][:2],
            'coordinate_boxes_total':len(g['coordinate_boxes'])} for g in groups[:4]]
        diagnostics['drc']={'error_count':parsed['error_count'],'coordinate_boxes_total':parsed.get('coordinate_boxes'),
            'rule_groups_total':len(groups),'rule_groups_omitted':max(0,len(groups)-4),
            'coordinate_boxes_omitted':sum(len(g['coordinate_boxes']) for g in groups)-sum(len(g['coordinate_boxes']) for g in sample),
            'samples':sample,'sampling':'First4 report rule groups and first2 coordinate boxes per group; complete raw report retained'}
    report=run/'evidence/lvs.rpt'
    if checks.get('lvs') is False and report.is_file():
        from src.report_parsers import netgen_lvs_report
        text=report.read_text();lines=text.splitlines();shown='\n'.join(lines[-12:])[-1600:]
        diagnostics['lvs']={**netgen_lvs_report(text),'report_tail':shown,'total_lines':len(lines),
            'lines_omitted':max(0,len(lines)-12),'characters_shown':len(shown),
            'sampling':'Last12 report lines, at most1600characters; complete raw report retained'}
    report=run/'evidence/device_intent.json'
    if checks.get('intent') is False and report.is_file():
        value=read(report)
        diagnostics['device_intent']={k:value[k] for k in ('per_device_dimensions_match','ports_match',
            'device_terminal_graph_match','expected_expanded_devices','actual_expanded_devices')}
        for key in ('missing','extra'):
            diagnostics['device_intent'][key]=value[key][:2]
            diagnostics['device_intent'][key+'_groups_omitted']=max(0,len(value[key])-2)
    return diagnostics


def visible_feedback(result):
    raw=result.get('physical_result') or {};observation=raw.get('observation',{})
    value={'status':result['status'],'checks':observation.get('checks',{}),'pex':observation.get('pex',{}),
        'corners':observation.get('corners',{}),'interface_error':observation.get('interface_error')}
    diagnostics=failure_diagnostics(result)
    if diagnostics:value['diagnostic_samples']=diagnostics
    return value


def backend(request):
    if request['op']=='start':return initialize(request)
    directory=project(request['episode_directory']);lock=directory/'private/backend.lock'
    with lock.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX);runner=Backend(directory);op=request['op']
        if op=='current':return runner.current()
        if op=='action':return runner.action(request['action'])
        if op=='seal':return runner.seal(request['status'],request.get('policy_statistics'))
        if op=='post_freeze':return runner.post_freeze(request.get('anchor_only',False))
        if op=='summary':return runner.summary()
        raise ValueError('Unknown backend operation')


def transport(request):
    command=SSH+["cd "+shlex.quote(REMOTE)+" && "+shlex.quote(REMOTE+'/runtime/GLdev/bin/python')+" scripts/e1_matched_runner.py --backend"]
    run=subprocess.run(command,input=json.dumps(request),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if run.returncode:raise BackendInfrastructureError('Trusted backend transport failed: '+run.stderr[-1500:])
    envelope=json.loads(run.stdout)
    if envelope.get('error'):
        if envelope.get('error_type')=='TimeoutError':raise TimeoutError(envelope['error'])
        if envelope.get('error_type') in ('ValueError','CalledProcessError'):raise ValueError(envelope['error'])
        raise BackendInfrastructureError(envelope['error'])
    return envelope['result']


def policy_statistics(session,out):
    records=sorted(Path(session['output']).glob('decision_*/invocation.json'))
    invocations=[path for path in records if isinstance(read(path).get('pid'),int) and read(path)['pid']>0]
    return {'decision_step_attempts':len(session['history']),'model_cli_invocations':len(invocations),
        'actual_provider_usage':session['usage'],'invocation_records':[str(path) for path in records],
        'raw_session':str(out/'session.json'),
        'scope':'Observed CLI/provider usage only; context rejection without a CLI PID is a decision step, not a model invocation. No inferred provider GPU time or subscription dollar price.'}


def run_policy(args):
    from src.model_adapter import GptDecisionAdapter
    from transformers import AutoTokenizer
    initialized=transport({'op':'start','manifest':args.manifest,'task_id':args.task,'method':args.method,'trial_id':args.trial,'formal':args.formal})
    directory=initialized['episode_directory'];packet=initialized['packet'];out=ROOT/'runs'/('formal/E1_policy' if args.formal else 'development/E1_policy')/Path(directory).name
    out.mkdir(parents=True);save(out/'backend.json',{'episode_directory':directory})
    if args.dispatch_record:
        save(Path(args.dispatch_record),{'episode_directory':directory,'local_output_directory':str(out),
            'task_id':args.task,'method':args.method,'trial_id':str(args.trial),'formal':args.formal})
    implementation={'status':'FROZEN_E1','implementation_sha256':initialized.get('implementation_sha256')} if args.formal else {'status':'DRAFT_E1_RUNNER'}
    verify_implementation(implementation)
    tokenizer=AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer',local_files_only=True,trust_remote_code=False)
    adapter=GptDecisionAdapter(out/'decisions',tokenizer=tokenizer);session=adapter.start(packet,initialized['model_config']);observation={'status':'initial'};status='DECISION_BUDGET_EXHAUSTED'
    try:
        for index in range(packet['budget']['decisions']):
            verify_implementation(implementation)
            check_utc_budget(packet);current=transport({'op':'current','episode_directory':directory})
            action=adapter.step(session,observation,current_sources=current['current_sources'])
            check_utc_budget(packet)
            try:observation=transport({'op':'action','episode_directory':directory,'action':action})
            except ValueError as error:observation={'error':type(error).__name__+': '+str(error)}
            print(json.dumps({'episode_directory':directory,'decision':index,'action':action['action'],'observation':observation}),flush=True)
            if action['action']=='finish':status='SEARCH_FINISHED';break
            if any(isinstance(value,dict) and value.get('execution_integrity')=='incomplete' for value in observation.values()):status='INCOMPLETE_UNKNOWN';break
    except TimeoutError:status='BUDGET_EXHAUSTED'
    except BackendInfrastructureError as error:
        status='INCOMPLETE_UNKNOWN';save(out/'backend_error.json',{'error':str(error)})
    except Exception as error:status='MODEL_FAILED';save(out/'policy_error.json',{'error':type(error).__name__+': '+str(error)})
    finally:
        session['closed']=True;save(out/'session.json',session)
        statistics=policy_statistics(session,out)
        report=transport({'op':'seal','episode_directory':directory,'status':status,'policy_statistics':statistics});save(out/'search_report.json',report)
    report=transport({'op':'post_freeze','episode_directory':directory,'anchor_only':args.anchor_only})
    save(out/'episode.json',report);print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--backend',action='store_true');p.add_argument('--manifest',default='configs/development/e1_freeze_manifest_draft.json')
    p.add_argument('--task');p.add_argument('--method',choices=['G0','G1','G2']);p.add_argument('--trial',default='0');p.add_argument('--formal',action='store_true')
    p.add_argument('--anchor-only',action='store_true',help='Development mechanical integration only; never claims complete domain')
    p.add_argument('--dispatch-record',type=Path,help='Local suite-owned dispatch index, written before tokenizer or model initialization')
    args=p.parse_args()
    if args.backend:
        try:result=backend(json.load(sys.stdin));print(json.dumps({'result':result}),flush=True)
        except Exception as error:
            message=type(error).__name__+': '+str(error)
            if isinstance(error,subprocess.CalledProcessError) and error.stderr:message+=' '+error.stderr.strip()[:1200]
            print(json.dumps({'error':message,'error_type':type(error).__name__}),flush=True)
    else:
        if not args.task or not args.method:p.error('Policy run requires task and method')
        if args.formal and args.anchor_only:p.error('Formal domain runs cannot use the development anchor-only smoke')
        run_policy(args)
