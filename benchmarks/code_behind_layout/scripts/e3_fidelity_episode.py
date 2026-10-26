"""Separate C+F3 ablation using the ordinary E3 policy and revision state.

Only newly selected development points may be empirically deferred. Anchor and
retained regressions use actual full checks, as does every post-release point.
The main A/R/B/C F0 consumer is unchanged.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import e3_episode as main
from scripts.e3_fidelity_point import evaluate
from src.e3_feedback import compact, public_checked
from src.model_adapter import check_utc_budget, validate_action

POLICY = 'F3_actual_nominal_promote_shared_PEX'


def verify_calibration(manifest):
    if manifest.get('status')!='FROZEN_E3_FIDELITY_METHOD':return
    path=main.project(manifest['promotion_calibration'])
    if path.stat().st_mode & 0o222 or hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['promotion_calibration_sha256']:
        raise RuntimeError('The frozen train/validation calibration artifact changed')


def initialize(request):
    manifest = main.read(main.project(request['manifest']))
    verify_calibration(manifest)
    if (request['method']!='C' or request.get('policy_variant','GPT')!='GPT' or
            request.get('selector_variant','main')!='main'):
        raise ValueError('The separate F3 ablation is GPT+C on the fixed two OTA states')
    identity = (request['task_id'],str(request.get('trial_id','development')))
    if request.get('formal') and identity not in {(r['task_id'],str(r['trial_id'])) for r in manifest['search_plan']}:
        raise ValueError('Identity outside the ten frozen F3 searches')
    result = main.initialize(request,expected_fidelity=POLICY)
    out = Path(result['episode_directory']);private = out/'private'
    state = main.read(private/'state.json')
    state.update(fidelity_policy=POLICY,low_fidelity_calls=0,staged_point_requests=0,
        actual_full_evaluator_invocations=0,deferred_by_revision={})
    main.save(private/'state.json',state)
    packet = result['packet']
    packet['documents']['controlled_verification'].update(fidelity_policy=POLICY,
        fidelity='pex_spice',low_fidelity_calls_max=32,
        low_fidelity_unit='One actual PEX acquisition or one actual TT nominal invocation; two usual calls per staged point',
        deferred='A newly selected development point may be empirically deferred. This is not a verified failure or pass. Anchor and retained points always require actual full checks.',
        final_verification='Only actual verified points enter source selection. All post-release checks use fresh original full execution.')
    main.save(private/'packet.json',packet)
    return result


class Gateway(main.Gateway):
    def __init__(self,out):
        super().__init__(out)
        if self.manifest['fidelity_policy']!=POLICY:
            raise ValueError('F3 backend cannot consume the main F0 manifest')
        verify_calibration(self.manifest)

    def next(self):
        deferred = self.state.value.setdefault('deferred_by_revision',{}).get(str(self.state.value['revision']),[])
        return self.state.next_configuration(self.predictions(),excluded=deferred)

    def current(self):
        result=super().current()
        result.update(low_fidelity_calls=self.state.value['low_fidelity_calls'],
            remaining_low_fidelity_calls=self.manifest['fidelity_budget']['low_fidelity_calls']-self.state.value['low_fidelity_calls'])
        return result

    def physical(self,ident,revision,stage):
        if stage!='search':
            # Fresh source -> GDS -> DRC/LVS/PEX -> full benchmark, identical to
            # the main post-release consumer. No search cache enters this path.
            return super().physical(ident,revision,stage)
        value = self.state.value
        check_utc_budget(self.packet)
        if value['sealed'] or value['full_evaluations']>=self.manifest['budget']['full_evaluations']:
            raise ValueError('Source sealed or actual full-check budget exhausted')
        if value['low_fidelity_calls']+2>self.manifest['fidelity_budget']['low_fidelity_calls']:
            raise ValueError('Insufficient remaining PEX+nominal call budget')
        from scripts.e3_generation_qualify import gate
        if shutil.disk_usage(ROOT).free<4*1024**3:
            raise RuntimeError('Research storage below4GiB; no new physical work')
        waiting={'stage':stage,'started_at_utc':main.now().isoformat(),'status':'WAITING'}
        value['resource_waits'].append(waiting);began=time.monotonic();self.write()
        try:
            waiting.update(gate(timeout=min(600,check_utc_budget(self.packet))),status='OPEN')
            check_utc_budget(self.packet)
        except Exception as error:
            waiting.update(status='NOT_DISPATCHED',error=type(error).__name__+': '+str(error))
            raise
        finally:
            waiting.update(ended_at_utc=main.now().isoformat(),actual_wait_wall_seconds=time.monotonic()-began)
            self.write()
        retained=set(value['required_passes'])|set(value['counterexamples'])|{value['anchor']}
        allow_screening=ident not in retained
        event={'configuration_id':ident,'revision':revision,'stage':stage,'status':'RUNNING',
            'fidelity_policy':POLICY,'allow_screening':allow_screening,'started_at_utc':main.now().isoformat()}
        value['in_flight']=event;value['physical_events'].append(event);value['staged_point_requests']+=1;self.write()
        folder=self.private/('points/%04d_%s'%(len(value['physical_events']),ident))
        evidence=evaluate(self.private/'task.json',ident,folder,self.source(revision),policy='F3',
            calibration_path=main.project(self.manifest['promotion_calibration']),allow_screening=allow_screening,
            deadline=value['deadline_utc'],formal=value['formal_trial'])
        costs=evidence['costs']
        pex=(evidence.get('physical_actual') or {}).get('actual_cost',{})
        pex_calls=int('trusted' in pex)
        nominal_calls=costs['actual_nominal_evaluator_invocations']
        full_calls=costs['actual_full_evaluator_invocations']
        value['low_fidelity_calls']+=pex_calls+nominal_calls
        value['full_evaluations']+=full_calls
        value['actual_full_evaluator_invocations']+=full_calls
        full=evidence.get('full_actual')
        rejected=(evidence.get('physical_actual') or {}).get('actual_physical_rejection')
        decision=evidence.get('promotion_decision') or {}
        if full is not None:
            row={**full,'task_id':self.task['task_id'],'configuration_id':ident,'fidelity':POLICY}
        elif rejected is not None:
            from scripts.e1_matched_runner import visible_feedback
            run=Path(evidence['physical_actual']['run_directory'])
            result={'run_directory':str(run),'physical_result':main.read(run/'evidence/validation.json'),
                'status':main.read(run/'manifest.json')['status']}
            row={'task_id':self.task['task_id'],'configuration_id':ident,'run_directory':str(run),
                'checked':rejected,'objective':None,'physical_feedback':visible_feedback(result),'fidelity':POLICY}
        elif decision.get('action')=='screened_deferred':
            if not allow_screening:
                raise RuntimeError('Anchor or retained regression was deferred')
            row={'task_id':self.task['task_id'],'configuration_id':ident,'deferred':True,
                'promotion_decision':decision,'nominal_actual':evidence['nominal_actual'],
                'point_record':str(folder/'fidelity_point.json')}
        else:
            budget=evidence.get('physical_status')=='budget_exhausted'
            row={'task_id':self.task['task_id'],'configuration_id':ident,'objective':None,'physical_feedback':{},
                'checked':{'S0':False,'S1':False,'S2':False,'execution_integrity':'budget_exhausted' if budget else 'incomplete',
                    'failure_class':'budget' if budget else 'unknown','reason':evidence.get('error',evidence['status'])}}
        main.save(folder/'point.json',row)
        event.update(status='RETURNED',ended_at_utc=main.now().isoformat(),point_record=str(folder/'point.json'),
            fidelity_record=str(folder/'fidelity_point.json'),low_fidelity_calls=pex_calls+nominal_calls,
            actual_full_evaluator_invocations=full_calls)
        value['in_flight']=None
        if not row.get('deferred') and row['checked']['execution_integrity']!='valid':
            value['status']='BUDGET_EXHAUSTED' if row['checked']['execution_integrity']=='budget_exhausted' else 'INCOMPLETE_UNKNOWN'
        self.write();return row

    def action(self,action):
        if action.get('action')!='request_evaluation':
            return super().action(action)
        value=self.state.value;check_utc_budget(self.packet)
        if value['sealed'] or value['status']!='RUNNING':raise ValueError('Episode search is closed')
        if value['decisions']>=self.manifest['budget']['decisions']:raise ValueError('Decision budget exhausted')
        value['decisions']+=1;self.write();validate_action(action,self.packet)
        ident=self.next()
        if ident is None:raise ValueError('No further configuration required; edit or finish')
        if action['configuration_ids']!=[ident] or action['fidelity']!='pex_spice':
            raise ValueError('Controlled next check is '+ident+' at pex_spice')
        row=self.physical(ident,value['revision'],'search')
        if row.get('deferred'):
            value.setdefault('deferred_by_revision',{}).setdefault(str(value['revision']),[]).append(ident)
            self.write()
            return {'configuration_id':ident,'revision':value['revision'],'status':'screened_deferred',
                'promotion_decision':row['promotion_decision'],
                'nominal_metrics':row['nominal_actual']['measurement']['metrics'],
                'low_fidelity_calls':value['low_fidelity_calls'],'actual_full_calls':value['full_evaluations'],
                'episode_status':value['status'],'next_configuration':self.next()}
        if row['checked']['execution_integrity']=='valid':self.state.observe(row);self.write()
        return {'configuration_id':ident,'revision':value['revision'],'checked':public_checked(row['checked']),
            'objective':row['objective'],'episode_status':value['status'],
            'low_fidelity_calls':value['low_fidelity_calls'],'actual_full_calls':value['full_evaluations'],
            'physical_feedback':compact(row['physical_feedback']),
            'next_configuration':self.next() if value['status']=='RUNNING' else None}

    def costs(self):
        totals={}
        for event in self.state.value['physical_events']:
            if event['stage']!='search':
                continue
            total=totals.setdefault('search',{'physical_calls':0,'stage_wall_seconds':0.,
                'waited_child_CPU_seconds':0.,'missing_CPU_records':0,'unresolved_calls':0,
                'actual_full_evaluator_invocations':0,'low_fidelity_calls':0})
            total['physical_calls']+=1
            if event['status']!='RETURNED':total['unresolved_calls']+=1;continue
            evidence=main.read(event['fidelity_record'])
            total['actual_full_evaluator_invocations']+=event['actual_full_evaluator_invocations']
            total['low_fidelity_calls']+=event['low_fidelity_calls']
            for stage in evidence['costs']['stages']:
                for name in ['candidate','trusted']:
                    if name not in stage:continue
                    total['stage_wall_seconds']+=stage[name]['wall_seconds']
                    cpu=stage[name]['waited_child_CPU_seconds']
                    if cpu is None:total['missing_CPU_records']+=1
                    else:total['waited_child_CPU_seconds']+=cpu
        # Let the unchanged parent count fresh post-release full executions.
        original=self.state.value['physical_events']
        try:
            self.state.value['physical_events']=[e for e in original if e['stage']!='search']
            totals.update(super().costs())
        finally:self.state.value['physical_events']=original
        return totals

    def seal(self,status,usage):
        report=super().seal(status,usage)
        report.update(fidelity_policy=POLICY,low_fidelity_calls=self.state.value['low_fidelity_calls'],
            actual_full_evaluator_invocations=self.state.value['actual_full_evaluator_invocations'],
            deferred_by_revision=self.state.value['deferred_by_revision'],screened_points_are_not_actual_failures=True)
        main.save(self.out/'public/search.json',report);return report

    def post_freeze(self):
        if not self.state.value['formal_trial']:
            raise ValueError('Development F3 episodes are search-only; no hidden dispatch from this consumer')
        return super().post_freeze()


def backend(request):
    if request['op']=='start':return initialize(request)
    out=main.project(request['episode_directory'])
    with (out/'private/backend.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);gateway=Gateway(out)
        if request['op']=='current':return gateway.current()
        if request['op']=='action':return gateway.action(request['action'])
        if request['op']=='seal':return gateway.seal(request['status'],request.get('policy_statistics'))
        if request['op']=='post_freeze':return gateway.post_freeze()
        raise ValueError('Unknown F3 gateway operation')


def transport(request):
    command=main.SSH+['cd '+shlex.quote(main.REMOTE)+' && '+shlex.quote(main.REMOTE+'/runtime/GLdev/bin/python')+' scripts/e3_fidelity_episode.py --backend']
    process=subprocess.run(command,input=json.dumps(request),text=True,capture_output=True)
    if process.returncode:raise RuntimeError('F3 transport failed: '+process.stderr[-1500:])
    envelope=json.loads(process.stdout)
    if envelope.get('error'):
        kind=TimeoutError if envelope['error_type']=='TimeoutError' else ValueError if envelope['error_type']=='ValueError' else RuntimeError
        raise kind(envelope['error'])
    return envelope['result']


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend',action='store_true');p.add_argument('--manifest');p.add_argument('--task')
    p.add_argument('--method',choices=['C'],default='C');p.add_argument('--selection-seed',type=int,default=41)
    p.add_argument('--trial',default='development');p.add_argument('--formal',action='store_true')
    p.add_argument('--variant',choices=['GPT'],default='GPT');p.add_argument('--training-seed',type=int,default=41)
    p.add_argument('--selector-variant',default='main');p.add_argument('--dispatch-record',type=Path)
    p.add_argument('--search-only',action='store_true')
    a=p.parse_args()
    if a.backend:
        try:print(json.dumps({'result':backend(json.load(sys.stdin))}),flush=True)
        except Exception as error:print(json.dumps({'error':str(error),'error_type':type(error).__name__}),flush=True)
    else:
        if not a.manifest or not a.task:p.error('Manifest and task required')
        a.search_only=True
        main.run_policy(a,rpc=transport)
