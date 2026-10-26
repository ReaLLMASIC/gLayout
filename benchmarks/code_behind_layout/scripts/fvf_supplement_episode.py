"""Separate full-module FVF A/R/B/C supplement; no changes to primary E3.

The ordinary state/action/selector/sealing code is reused. This endpoint replaces
only physical transport with the qualified vendor-FVF point API. All searches
seal before returning; even development cannot implicitly open hidden points.
"""
import argparse
import copy
from datetime import timedelta
import fcntl
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import e3_episode as main
from scripts.prepare_fvf_supplement import TASK,EDITABLE
from src.e3_episode_state import EpisodeState
from src.model_adapter import check_utc_budget

COHORT='E3_FVF_fullmodule_supplement_v1'
DRAFT='DRAFT_E3_FVF_SUPPLEMENT'
FROZEN='FROZEN_E3_FVF_SUPPLEMENT'
BUDGET={'wall_seconds':14400,'decisions':24,'patches':8,'full_evaluations':8,
    'maximum_context_tokens':16384,'maximum_output_tokens':1024}
METHODS=('A','R','B','C')
SEEDS=(41,73,109,167,223)
SSH=main.SSH[:-1]+['-o','ControlPath=/tmp/cbl-ssh-control',main.SSH[-1]]
LIVE=('scripts/fvf_supplement_episode.py','scripts/prepare_fvf_search_supplement.py',
    'scripts/fvf_supplement_point.py','scripts/prepare_fvf_supplement.py',
    'scripts/qualify_fvf_supplement.py','scripts/audit_train_pair_nf_rc.py',
    'scripts/qualify_telescopic_supplement.py','docs/fvf_search_supplement_DRAFT.md')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return main.read(path)
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);main.save(path,value)


def matrix():
    return [{'task_id':TASK,'method':method,'trial_id':str(trial),'selection_seed':SEEDS[trial-1]}
        for trial in range(1,6) for method in METHODS]


def selector_points(public):
    """Fixed W/L coordinate projection; original sizing/N never changes."""
    result=[]
    for point in public:
        if point['role'] not in ('anchor','development'):raise ValueError('Only visible FVF coordinates may enter selector')
        parameters=point['parameters']
        if set(parameters)!={'local_current_bias_params'}:raise ValueError('Only the original fixed FVF sizing interface')
        pair=parameters['local_current_bias_params']
        if not isinstance(pair,list) or len(pair)!=2 or any(type(x) not in (int,float) or x<=0 for x in pair):
            raise ValueError('FVF local-current-bias parameters must be original positive W/L')
        result.append({**point,'parameters':{'local_current_bias_width_um':pair[0],'local_current_bias_length_um':pair[1]}})
    return result


def bound_task(manifest,path):
    if Path(path).resolve()!=Path(manifest['task']).resolve():raise ValueError('Only this frozen FVF task')
    expected=manifest['file_sha256'][str(Path(path).relative_to(Path(manifest['preparation'])))]
    if sha(path)!=expected:raise ValueError('FVF task bytes changed')
    task=read(path)
    if (task['task_id']!=TASK or task['editable_paths']!=[EDITABLE] or task['target']!='fvf'
            or task['representation']!='G2' or 'E1_binding' in task):
        raise ValueError('Full-module FVF vendor transport requires its own task')
    return task


def verify_manifest(path,*,formal=False):
    path=Path(path);m=read(path)
    if m.get('cohort_id')!=COHORT or m.get('status')!=(FROZEN if formal else DRAFT):
        raise ValueError('Dedicated prospective FVF freeze required; DRAFT is not formal')
    if m.get('formal_dispatch') is not formal or m.get('search_plan')!=matrix() or m.get('budget')!=BUDGET:
        raise ValueError('Fixed20 identities and common ordinary budgets required')
    if formal and path.stat().st_mode&0o222:raise ValueError('Formal supplement manifest must be readonly')
    if sha(m['main_manifest'])!=m['main_manifest_sha256']:raise ValueError('Primary freeze changed')
    original=read(m['main_manifest'])
    if original['status']!='FROZEN_E3' or original['freeze_id']!='E3_primary_v2':raise ValueError('Actual primary E3 freeze required')
    main.verify(original)
    if set(m['implementation_sha256'])!=set(original['implementation_sha256'])|set(LIVE):
        raise ValueError('FVF runtime must bind the full primary dependency plus dedicated closure')
    if formal and (m.get('freeze_id')!=COHORT or not m.get('source_revision') or not m.get('frozen_at_utc')):
        raise ValueError('Actual committed prospective FVF freeze identity required')
    for name,value in m['implementation_sha256'].items():
        if sha(ROOT/name)!=value:raise ValueError('FVF implementation changed: '+name)
    base=Path(m['preparation'])
    for name,value in m['file_sha256'].items():
        p=base/name
        if sha(p)!=value:raise ValueError('FVF frozen input changed: '+name)
        if formal and p.stat().st_mode&0o222:raise ValueError('Frozen FVF input is writable: '+name)
    task=bound_task(m,m['task'])
    if formal and (task.get('status')!='FROZEN_E3_FVF_SUPPLEMENT_TASK' or not task.get('formal_admission')):
        raise ValueError('Dedicated frozen admitted FVF task required')
    return m


def policy_packet(original,manifest,method,deadline):
    packet=main.policy_packet(original,manifest,method,deadline)
    packet['documents']['supplement_scope']={
        'cohort_id':COHORT,'primary_matrix_unchanged':True,
        'full_source':'Entire original top-level335-line OTA module, readonly subordinate circuit/API closure.',
        'constraint':'Only layout changes; immutable per-finger devices, topology, sizing and original15pF electrical constraints.',
        'selector_coordinates':'The original local_current_bias_params=[W,L] supplies two numeric W/L coordinates for the unchanged visible-only selector; the actual parameter envelope and circuit sizing stay immutable.'}
    return packet


def initialize(request):
    formal=request.get('formal',False);m=verify_manifest(request['manifest'],formal=formal)
    ident={k:request[k] for k in ('task_id','method','trial_id','selection_seed')}
    if ident not in m['search_plan'] or request.get('policy_variant','GPT')!='GPT':
        raise ValueError('Only the separately declared20 fresh GPT searches')
    task=read(m['task']);public=[p for p in task['configurations'] if p['role']!='hidden']
    stamp=main.now().strftime('%Y%m%dT%H%M%S%fZ_')+uuid.uuid4().hex[:8]
    out=ROOT/('runs/formal/E3_FVF_supplement' if formal else 'runs/development/FVF_supplement_episodes')/stamp
    reservation=None
    if formal:
        reservation=Path(m['dispatch_directory'])/(ident['method']+'_'+ident['trial_id']+'.json')
        reservation.parent.mkdir(parents=True,exist_ok=True)
        with reservation.open('x') as stream:
            stream.write(json.dumps({**ident,'cohort_id':COHORT,'episode_directory':str(out),
                'status':'RESERVED','created_at_utc':main.now().isoformat()},indent=2)+'\n')
    private=out/'private';private.mkdir(parents=True,mode=0o700);(out/'public').mkdir()
    save(private/'manifest.json',m);save(private/'task.json',task)
    source=private/'revisions/000/source';source.parent.mkdir(parents=True)
    main.capsule(Path(m['task']),source)
    deadline=(main.now()+timedelta(seconds=BUDGET['wall_seconds'])).isoformat()
    packet=policy_packet(read(m['packet']),m,ident['method'],deadline)
    save(private/'packet.json',packet)
    model=read(m['model_config']);model['visible_history_policy']='current_source_and_feedback_v1'
    state=EpisodeState(ident['method'],selector_points(public),ident['selection_seed'],'min',m['risk_weights'])
    state.value.update(episode_directory=str(out),task_path=m['task'],formal_trial=formal,trial_id=ident['trial_id'],
        phase='formal_E3_FVF_supplement' if formal else 'development_E3_FVF_supplement',
        cohort_id=COHORT,policy_variant='GPT',training_seed=None,evaluation_seed_slot=None,selector_variant='main',
        policy_model_identity=model.get('model_identity'),
        status='RUNNING',created_at_utc=main.now().isoformat(),deadline_utc=deadline,
        decisions=0,patch_attempts=0,full_evaluations=0,in_flight=None,physical_events=[],resource_waits=[],
        post_freeze_started=False,contract=packet['contract'],
        contracts_by_configuration={p['configuration_id']:p['contract'] for p in public},
        initial_sources={EDITABLE:(source/EDITABLE).read_text()})
    save(private/'state.json',state.value)
    if reservation:
        record=read(reservation);record['status']='STARTED';save(reservation,record)
    return {'episode_directory':str(out),'packet':packet,'model_config':model,'implementation_sha256':m['implementation_sha256']}


class Gateway(main.Gateway):
    def __init__(self,out):
        super().__init__(out)
        self.origin_manifest=Path(self.manifest['manifest_path'])
        origin=verify_manifest(self.origin_manifest,formal=self.state.value['formal_trial'])
        if self.manifest!=origin or self.task!=read(origin['task']):
            raise ValueError('Episode task/manifest differs from the bound supplement')

    def predictions(self):
        if self.state.value['method']!='C':return None
        from src.e3_risk_model import load_frozen_predictor
        points=selector_points([p for p in self.task['configurations'] if p['role']!='hidden'])
        return load_frozen_predictor(Path(self.manifest['risk_model'])).predict(self.sources(),self.state.value,
            {p['configuration_id']:p['parameters'] for p in points})

    def physical(self,ident,revision,stage):
        value=self.state.value
        if stage=='search':
            check_utc_budget(self.packet)
            if value['sealed'] or value['full_evaluations']>=BUDGET['full_evaluations']:
                raise ValueError('Search sealed or full-point budget exhausted')
            if ident not in value['features']:raise ValueError('Hidden configuration cannot enter search')
        else:require_release(self.manifest,self.out)
        event={'configuration_id':ident,'revision':revision,'stage':stage,
            'started_at_utc':main.now().isoformat(),'status':'RUNNING'}
        value['in_flight']=event;value['physical_events'].append(event);self.write()
        folder=self.private/('points/%04d_%s'%(len(value['physical_events']),ident))
        from scripts.fvf_supplement_point import evaluate_supplement
        # This consumer already enforces the actual CPU/RAM/disk/UTC gate. Do
        # not add the main Gateway's second physical gate or double-count wait.
        row=evaluate_supplement(self.origin_manifest,ident,folder,self.source(revision),
            value['deadline_utc'] if stage=='search' else None,formal=value['formal_trial'])
        calls=row['physical_call_reservations']
        if stage=='search':value['full_evaluations']+=calls
        event.update(status='RETURNED',ended_at_utc=main.now().isoformat(),point_record=str(folder/'point.json'),
            execution_integrity=row['checked']['execution_integrity'],actual_physical_calls=calls)
        value['resource_waits'].append({'stage':stage,'point_record':str(folder/'point.json'),
            'resource_samples':row['resource_samples'],'point_window_includes_resource_wait':True})
        value['in_flight']=None
        if row['checked']['execution_integrity']!='valid':
            value['status']='BUDGET_EXHAUSTED' if row['checked']['execution_integrity']=='budget_exhausted' else 'INCOMPLETE_UNKNOWN'
        self.write()
        if value['formal_trial'] and row.get('run_directory'):
            # The existing E3 archive keeps all bytes privately and retains
            # source/GDS/telemetry online. No new archive format is introduced.
            from scripts.archive_e3_evidence import archive_point
            event['archive']=archive_point(folder);self.write()
        return row

    def seal(self,status,usage):
        report=super().seal(status,usage)
        report.update(cohort_id=COHORT,primary24_1730_and_7clusters_unchanged=True)
        save(self.out/'public/search.json',report);return report

    def costs(self):
        stages={}
        for event in self.state.value['physical_events']:
            stage='search' if event['stage']=='search' else ('hidden' if event['stage'].endswith('_hidden') else 'post_freeze_diagnostic')
            total=stages.setdefault(stage,{'physical_calls':0,'point_attempts':0,'stage_wall_seconds':0.,
                'waited_child_CPU_seconds':0.,'missing_CPU_records':0,'unresolved_calls':0,'point_wall_seconds':0.,'point_parent_CPU_seconds':0.})
            total['point_attempts']+=1
            if event['status']!='RETURNED':total['unresolved_calls']+=1;continue
            row=read(event['point_record']);total['physical_calls']+=row['physical_call_reservations']
            total['point_wall_seconds']+=row['point_wall_seconds'];total['point_parent_CPU_seconds']+=row['point_parent_CPU_seconds']
            unresolved_cost=bool(row['physical_call_reservations'] and not row.get('actual_costs_by_stage'))
            if row['physical_call_reservations'] and row.get('run_directory'):
                try:
                    execution=read(Path(row['run_directory'])/'manifest.json')
                    terminal=execution.get('status') in ('CANDIDATE_FAILED','REJECTED_OUTPUT','EVALUATED','EVALUATION_FAILED','BUDGET_EXHAUSTED')
                    terminal=terminal and all(execution[name].get('container_state',{}).get('Running') is False
                        for name in ('candidate','trusted') if name in execution)
                    unresolved_cost=unresolved_cost or not terminal
                except (OSError,ValueError):unresolved_cost=True
            if unresolved_cost:
                # A reserved executor whose final stage telemetry is missing
                # (or a still-RUNNING host manifest) is not evidence of zero
                # unknown child CPU. A resource-gate NOT_RUN
                # (zero reservations) has no missing child execution instead.
                total['missing_CPU_records']+=1;total['unresolved_calls']+=1
            for cost in row.get('actual_costs_by_stage',{}).values():
                if cost['wall_seconds'] is not None:total['stage_wall_seconds']+=cost['wall_seconds']
                if cost['waited_child_CPU_seconds'] is None:total['missing_CPU_records']+=1
                else:total['waited_child_CPU_seconds']+=cost['waited_child_CPU_seconds']
        for total in stages.values():
            total['known_waited_child_CPU_seconds']=total['waited_child_CPU_seconds']
            total['CPU_total_complete']=not(total['missing_CPU_records'] or total['unresolved_calls'])
            if not total['CPU_total_complete']:total['waited_child_CPU_seconds']=None
        return stages

    def post_freeze(self):
        # Parent's loop supplies once-only fresh25/no feedback/unknown-stop.
        # Its main release guard is bypassed only after this stricter separate
        # guard has verified both releases; the main method recognizes this
        # manifest as distinct and therefore performs no alternative release.
        require_release(self.manifest,self.out)
        return super().post_freeze()


def source_proof(path):
    out=Path(path);state=read(out/'private/state.json');task=read(out/'private/task.json')
    if not state['sealed'] or state.get('cohort_id')!=COHORT or not state.get('formal_trial'):
        raise ValueError('Each supplement source must actually be formally sealed')
    report=read(out/'public/search.json')
    if (report['cohort_id']!=COHORT or report['selection']!=state['selection']
            or state['post_freeze_started'] or any(e['stage']!='search' for e in state['physical_events'])):
        raise ValueError('No supplement point may have opened before the common release')
    if state['in_flight']:raise ValueError('Unresolved physical call prevents release')
    source=out/'private'/('revisions/%03d/source'%state['selection']['revision'])
    return {'task_id':task['task_id'],'method':state['method'],'trial_id':state['trial_id'],
        'selection_seed':state['seed'],'episode_directory':str(out.resolve()),
        'selected_source_sha256':{n:sha(source/n) for n in task['source_files']}}


def shared_release(manifest):
    original=read(manifest['main_manifest']);release=main.require_release(original,baseline=True)
    if release['actual_trained_models']!=12 or len(release['sealed_searches'])!=1730:
        raise ValueError('Original1730 searches and12 actual models must precede supplement hidden')
    return release


def release(manifest_path,index_path):
    m=verify_manifest(manifest_path,formal=True);shared=shared_release(m)
    destination=Path(m['supplement_release_file'])
    if destination.exists():raise ValueError('Supplement release is never overwritten')
    index=read(index_path)
    if index['cohort_id']!=COHORT or len(index['searches'])!=20:raise ValueError('Exact20 supplement search index required')
    proofs=[source_proof(row['episode_directory']) for row in index['searches']]
    identity=lambda r:{k:r[k] for k in ('task_id','method','trial_id','selection_seed')}
    if sorted((json.dumps(identity(r),sort_keys=True) for r in proofs))!=sorted(json.dumps(r,sort_keys=True) for r in matrix()):
        raise ValueError('All20 distinct fixed method/trial sources must be sealed')
    if len({r['episode_directory'] for r in proofs})!=20:raise ValueError('Repeated episode is not an independent trial')
    for proof in proofs:
        if read(Path(proof['episode_directory'])/'private/manifest.json')!=m:raise ValueError('Search used another supplement freeze')
    value={'status':'FROZEN_E3_FVF_SUPPLEMENT_EVALUATION_RELEASE','cohort_id':COHORT,
        'freeze_id':m['freeze_id'],'manifest_sha256':sha(manifest_path),'main_release_sha256':sha(read(m['main_manifest'])['hidden_release_file']),
        'actual_trained_models':shared['actual_trained_models'],'sealed_searches':proofs,'created_at_utc':main.now().isoformat(),
        'hidden_calls_dispatched':0}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('x') as f:f.write(json.dumps(value,indent=2,allow_nan=False)+'\n')
    destination.chmod(0o444);return {'status':value['status'],'hidden_calls':0}


def released_manifest(manifest):
    if manifest['status']!=FROZEN:raise ValueError('Development never releases this supplement hidden domain')
    shared_release(manifest)
    path=Path(manifest['supplement_release_file'])
    if not path.is_file() or path.stat().st_mode&0o222:raise ValueError('Separate supplement release absent or writable')
    r=read(path)
    if (r['status']!='FROZEN_E3_FVF_SUPPLEMENT_EVALUATION_RELEASE' or r['freeze_id']!=manifest['freeze_id']
            or r['manifest_sha256']!=sha(manifest['manifest_path'])
            or r['main_release_sha256']!=sha(read(manifest['main_manifest'])['hidden_release_file'])):
        raise ValueError('Supplement/shared release identity changed')
    if len(r['sealed_searches'])!=20:raise ValueError('Exact20 sources must precede any supplement hidden point')
    return r


def require_release(manifest,episode):
    r=released_manifest(manifest)
    matches=[row for row in r['sealed_searches'] if Path(row['episode_directory']).resolve()==Path(episode).resolve()]
    if len(matches)!=1:raise ValueError('This episode was not sealed in the exact20 release')
    state=read(Path(episode)/'private/state.json');task=read(Path(episode)/'private/task.json')
    source=Path(episode)/'private'/('revisions/%03d/source'%state['selection']['revision'])
    if not state['sealed'] or {n:sha(source/n) for n in task['source_files']}!=matches[0]['selected_source_sha256']:
        raise ValueError('The actual selected source changed after release')
    return r


def require_hidden_source(manifest,source):
    """Also guard direct formal point API calls, not just the model gateway."""
    release=released_manifest(manifest);task=read(manifest['task'])
    source=Path(source) if source is not None else Path(task['source_pack_base'])
    actual={n:sha(source/n) for n in task['source_files']}
    original={n:sha(Path(task['source_pack_base'])/n) for n in task['source_files']}
    if actual!=original and actual not in [r['selected_source_sha256'] for r in release['sealed_searches']]:
        raise ValueError('Hidden point source is neither immutable original nor one of20 released selections')


def original_baseline(manifest_path,output):
    """One fresh25 original program pass after both releases, with no retries."""
    m=verify_manifest(manifest_path,formal=True);released_manifest(m);task=read(m['task'])
    output=Path(output).resolve();expected=ROOT/'runs/formal/E3_FVF_supplement_baseline'/COHORT
    if output!=expected:raise ValueError('Only the one fixed supplement baseline output')
    output.mkdir(parents=True,exist_ok=False);(output/'private').mkdir(mode=0o700)
    save(output/'private/manifest.json',m);rows=[]
    from scripts.fvf_supplement_point import evaluate_supplement
    from scripts.archive_e3_evidence import archive_point
    for point in task['configurations']:
        ident=point['configuration_id'];folder=output/'private'/ident
        # The reservation survives a process failure. Existing output is never
        # retried, and no subsequent point is dispatched on unknown.
        save(output/'private/in_flight.json',{'configuration_id':ident,'started_at_utc':main.now().isoformat()})
        row=evaluate_supplement(manifest_path,ident,folder,Path(task['source_pack_base']),formal=True)
        rows.append({'configuration_id':ident,'role':point['role'],'checked':row['checked'],'objective':row['objective'],
            'point_record':str(folder/'point.json'),'actual_costs_by_stage':row.get('actual_costs_by_stage',{}),
            'point_wall_seconds':row['point_wall_seconds'],'point_parent_CPU_seconds':row['point_parent_CPU_seconds']})
        save(output/'private/points.json',rows)
        save(output/'private/in_flight.json',None)
        if row.get('run_directory'):archive_point(folder)
        if row['checked']['execution_integrity']!='valid':break
    known=sum(r['checked']['execution_integrity']=='valid' for r in rows)
    report={'status':'COMPLETE_ORIGINAL_BASELINE' if known==25 else 'INCOMPLETE_UNKNOWN',
        'cohort_id':COHORT,'declared_points':25,'attempted_points':len(rows),'known_points':known,'NOT_RUN':25-len(rows),
        'S2_points':sum(r['checked']['S2'] for r in rows),'hidden_vectors_exported':False,'new_model_calls':0,
        'automatic_retry':False,'raw_point_records':'private/points.json'}
    save(output/'public_summary.json',report);return report


def backend(request):
    if request['op']=='start':return initialize(request)
    out=Path(request['episode_directory'])
    with (out/'private/backend.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);g=Gateway(out)
        if request['op']=='current':return g.current()
        if request['op']=='action':return g.action(request['action'])
        if request['op']=='seal':return g.seal(request['status'],request.get('policy_statistics'))
        if request['op']=='post_freeze':return g.post_freeze()
        raise ValueError('Unknown supplement gateway operation')


def transport(request):
    command=SSH+['cd '+shlex.quote(main.REMOTE)+' && '+shlex.quote(main.REMOTE+'/runtime/GLdev/bin/python')+' scripts/fvf_supplement_episode.py --backend']
    p=subprocess.run(command,input=json.dumps(request),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode:raise RuntimeError('FVF transport failed: '+p.stderr[-1500:])
    r=json.loads(p.stdout)
    if 'error' in r:
        kind={'TimeoutError':TimeoutError,'ValueError':ValueError}.get(r['error_type'],RuntimeError)
        raise kind(r['error'])
    return r['result']


def run_policy(args,rpc=transport):
    from transformers import AutoTokenizer
    from src.model_adapter import GptDecisionAdapter
    init=rpc({'op':'start','manifest':args.manifest,'task_id':TASK,'method':args.method,
        'trial_id':str(args.trial),'selection_seed':SEEDS[int(args.trial)-1],'formal':args.formal,'policy_variant':'GPT'})
    directory=init['episode_directory']
    out=ROOT/('runs/formal/E3_FVF_supplement_policy' if args.formal else 'runs/development/FVF_supplement_policy')/Path(directory).name
    out.mkdir(parents=True);save(out/'backend.json',{'episode_directory':directory,'cohort_id':COHORT})
    if args.dispatch_record:save(args.dispatch_record,{'episode_directory':directory,'local_output_directory':str(out),
        'cohort_id':COHORT,'task_id':TASK,'method':args.method,'trial_id':str(args.trial),'formal':args.formal})
    # Same live-map recheck before any tokenizer/model request as primary E3.
    main.verify({'status':'FROZEN_E3','implementation_sha256':init['implementation_sha256']})
    tokenizer=AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer',local_files_only=True,trust_remote_code=False)
    adapter=GptDecisionAdapter(out/'decisions',tokenizer=tokenizer)
    session=adapter.start(init['packet'],init['model_config']);observation={'status':'initial'};status='DECISION_BUDGET_EXHAUSTED'
    try:
        for _ in range(BUDGET['decisions']):
            main.verify({'status':'FROZEN_E3','implementation_sha256':init['implementation_sha256']})
            current=rpc({'op':'current','episode_directory':directory})
            action=adapter.step(session,{**observation,'next_configuration':current['next_configuration']},current_sources=current['current_sources'])
            try:observation=rpc({'op':'action','episode_directory':directory,'action':action})
            except ValueError as error:observation={'error':str(error),'next_configuration':current['next_configuration']}
            if action['action']=='finish':status='SEARCH_FINISHED';break
            if observation.get('checked',{}).get('execution_integrity') not in (None,'valid'):
                status=observation['episode_status'];break
    except TimeoutError:status='BUDGET_EXHAUSTED'
    except Exception as error:
        status=('CONTEXT_BUDGET_EXHAUSTED' if isinstance(error,ValueError) and str(error).startswith('Complete GPT source/history exceeds the shared context budget')
            else 'MODEL_FAILED' if isinstance(error,ValueError) else 'INCOMPLETE_UNKNOWN')
        save(out/'error.json',{'error':type(error).__name__+': '+str(error)})
    finally:
        session['closed']=True;save(out/'session.json',session)
        report=rpc({'op':'seal','episode_directory':directory,'status':status,'policy_statistics':main.policy_statistics(session,out)})
        save(out/'search.json',report)
    print(json.dumps({'status':'SUPPLEMENT_SEARCH_SEALED_AWAITING_BOTH_RELEASES','cohort_id':COHORT,
        'episode_directory':directory,'local_output_directory':str(out),'hidden_calls':0}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--backend',action='store_true')
    p.add_argument('--manifest');p.add_argument('--method',choices=METHODS);p.add_argument('--trial',type=int,choices=range(1,6))
    p.add_argument('--formal',action='store_true');p.add_argument('--dispatch-record',type=Path)
    p.add_argument('--release-index',type=Path);p.add_argument('--post-freeze')
    p.add_argument('--original-baseline',type=Path)
    a=p.parse_args()
    if a.backend:
        try:print(json.dumps({'result':backend(json.load(sys.stdin))}),flush=True)
        except Exception as e:print(json.dumps({'error':str(e),'error_type':type(e).__name__}),flush=True)
    elif a.release_index:print(json.dumps(release(a.manifest,a.release_index)))
    elif a.original_baseline:print(json.dumps(original_baseline(a.manifest,a.original_baseline)))
    elif a.post_freeze:print(json.dumps(backend({'op':'post_freeze','episode_directory':a.post_freeze})))
    else:
        if not(a.manifest and a.method and a.trial):p.error('Manifest/method/trial required')
        run_policy(a)
