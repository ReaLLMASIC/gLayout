"""Prospective NF GPT+original-rules common pool;32raw slots,2contexts,0newlineages."""
import argparse
import copy
from datetime import datetime,timezone,timedelta
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts import evaluate_nf_span_proposals as nf
from scripts import evaluate_train_span_proposals as span
from scripts import evaluate_matched_t0_proposals as physical
from scripts.corpus_rule_proposer import RULE_IDS
from src.train_span_proposer import compile_proposal,source_identity
from src.student_interface import canonical_action,encode_policy_action,PolicyBudgetError
from src.train_nf_span_bundle import validate_rules_ready

read,save,now=physical.read,physical.save,physical.now
ROLE='matched_NF_joint_GPT_and_original_rules_physical_followup_train_only'
CODE=tuple(dict.fromkeys((*nf.CODE,'scripts/evaluate_nf_joint_pool.py','scripts/corpus_rule_proposer.py')))
RESOURCES={**nf.RESOURCES,'maximum_new_candidate_points':288}


def joint_rule(parent):
    value=nf.make_rule(parent,nf.ORDER)
    value['version']+='__fixed_original_rule_then_GPT_joint16'
    value['sft_selection'].update(actual_trial_field='joint_trial_id',declared_trial_order=list(range(1,17)))
    value['joint_pool']={'rule_ids':list(RULE_IDS),'GPT_trial_ids':list(range(1,9)),
        'order':'Actual original rules generated first, then freshGPT; unchanged original numeric comparisons/scopes'}
    return value


def slots(contexts):
    return [{'initial_state_id':c['initial_state_id'],'parent_collection':c['parent_collection'],
        'producer':producer,'trial_id':trial,'rule_id':RULE_IDS[trial-1] if producer=='rule' else None,
        'joint_trial_id':trial if producer=='rule' else trial+8,'status':'NOT_RUN'}
        for c in contexts for producer in ['rule','GPT'] for trial in range(1,9)]


def prepare(proposal,folder,output_root):
    definition=nf.prepare(proposal,folder,output_root);folder=Path(folder).resolve()
    plan,parents,contexts,_=nf.proposal_definition(proposal,folder)
    if str(folder/'acceptance.json')!=plan['joint_acceptance_plan'] or str(Path(output_root).resolve()/'rules_ready.json')!=plan['rules_ready_path']:
        raise ValueError('Use the exact predeclared NF joint-v2 acceptance and rule-ready locations')
    for name in CODE:
        target=folder/'interface'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    for name,parent in parents.items():save(folder/'rules'/(name+'.json'),joint_rule(read(parent['manifest']['label_rule_path'])))
    definition.update(role=ROLE,physical=RESOURCES,declared_proposals=32,implementation_files=list(CODE),
        slots=slots(definition['contexts']),raw_GPT_proposals=16,raw_original_rule_proposals=16,
        raw_input_policy='Two separate rawproducer roots; common16candidate/context prospectivepool, exactASTdedup beforephysics. No oldpool merge.',
        selection='Frozen actualorder originalrule1..8thenGPT1..8; allhard scopes/effect/tie/v2 criterion unchanged. Reportproducer-specificprovenance and commonpool preferences honestly.',
        launch_order='Materialize all16 rules first; only after the actual rule-ready receipt may the GPTcollector or this physical consumer start. No GPTmodelcall is made bythisconsumer.',
        new_loop_rule='Scan all32rawslots aftereachphysicalpass, continue newlyeligible PHYSICAL_PENDING beforeterminal. Everyproposercost/raw/status preserved.')
    save(folder/'acceptance.json',definition);return definition


def load_acceptance(path,require_frozen=True):
    path=Path(path).resolve();definition=read(path)
    if (definition.get('role')!=ROLE or definition.get('status')!=('frozen' if require_frozen else 'DRAFT')
            or definition.get('physical')!=RESOURCES or definition.get('implementation_files')!=list(CODE)
            or definition.get('declared_proposals')!=32 or definition.get('evidence_root')!=str(ROOT)):
        raise ValueError('Use onlythe independentlyreviewed fixedNF joint32 plan')
    nf.verify_code(path,definition);plan,parents,contexts,registry=nf.proposal_definition(definition['proposal_collection'],path.parent)
    if definition['slots']!=slots(definition['contexts']):raise ValueError('Do not alterthe32predeclaredsource/trial slots')
    if definition['contexts']!=[{'initial_state_id':c['initial_state_id'],'parent_collection':c['parent_collection']} for c in contexts]:raise ValueError('NF contexts changed')
    if hashlib.sha256(Path(definition['proposal_collection']).read_bytes()).hexdigest()!=definition['proposal_collection_sha256']:raise ValueError('GPTbundlechanged')
    for context in contexts:
        name=context['parent_collection'];parent=parents[name];sid=context['initial_state_id']
        if read(path.parent/'parents'/name/'runtime_binding.json')!=parent['manifest']:raise ValueError('Formalcontrolbindingchanged')
        if read(path.parent/'rules'/(name+'.json'))!=joint_rule(read(parent['manifest']['label_rule_path'])):raise ValueError('Jointscope/numericthresholds/trialorderchanged')
        if read(context['materialized_task_packet'])!=context['original_request_value']['task_packet'] or read(context['materialized_visible_history'])!=context['original_request_value']['visible_history']:raise ValueError('Actualcompletecontextchanged')
        if read(path.parent/'parents'/name/sid/'baseline_results.json')!=read(Path(definition['proposal_collection']).parent/context['baseline_results']):raise ValueError('Controlssubstituted')
    if require_frozen and any(p.stat().st_mode&0o222 for p in [path.parent,*path.parent.rglob('*')]):raise ValueError('Jointfreezeiswritable')
    return definition,plan,parents,contexts,registry


def baseline_control(path,report):
    definition,_,parents,contexts,registry=load_acceptance(path,False);records=[]
    for c in contexts:
        row=span.candidate_row(c,parents[c['parent_collection']],{'request':c['teacher_request_value'],'source':c['base_source'],'patch':'','attempt':{}},1)
        records.append({'initial_state_id':c['initial_state_id'],'points':physical.baseline_bindings(c,parents[c['parent_collection']],registry,row),
            'identity':span.student_identity_proof(c,row)})
    result={'status':'ACTUAL_NF_JOINT_FORMAL18_CONTROL','records':records,'actual_baseline_points_re_read':18,'new_model_calls':0,'new_physical_calls':0}
    save(report,result);return {k:v for k,v in result.items() if k!='records'}


def freeze(path):
    path=Path(path).resolve();d,*_=load_acceptance(path,False);control=read(path.parent/'baseline_control.json')
    if control.get('status')!='ACTUAL_NF_JOINT_FORMAL18_CONTROL' or control.get('actual_baseline_points_re_read')!=18:raise ValueError('Actualjoint18controlproofrequired')
    d.update(status='frozen',frozen_at_utc=now());save(path,d)
    for p in sorted(path.parent.rglob('*'),key=lambda p:len(p.parts),reverse=True):p.chmod(0o555 if p.is_dir() else 0o444)
    path.parent.chmod(0o555);load_acceptance(path);return {'status':'FROZEN_JOINT32_NO_CALLS','models':0,'physics':0}


def materialize_rules(folder,contexts,output,tokenizer):
    definition=read(folder/'acceptance.json');proposal_sha=definition['proposal_collection_sha256']
    if (output/'rules_ready.json').exists():
        validate_rules_ready(read(output/'rules_ready.json'),proposal_sha,folder/'acceptance.json')
        return read(output/'rules_ready.json')
    module=physical.module(folder/'interface/scripts/corpus_rule_proposer.py','_frozen_NF_original_rules')
    if module.RULE_IDS!=RULE_IDS:raise ValueError('Originaleightoptionschanged')
    for c in contexts:
        for rule in RULE_IDS:
            work=output/'raw_rules'/c['initial_state_id']/rule
            if work.exists():raise ValueError('Unresolvedrulegenerationreservation; noretry')
            work.mkdir(parents=True);save(work/'reservation.json',{'initial_state_id':c['initial_state_id'],'rule_id':rule,'at_utc':now()})
            began=time.monotonic();cpu=time.process_time();attempt={'rule_id':rule,'model':None,'seed':None,'status':'RULE_RETURNED'}
            ordinary=c['original_request_value'];save(work/'request.json',{'mode':'train_collection_rules','rule_id':rule,'request':ordinary})
            try:
                text=module.propose(c['base_source']['textbook_sharing/layout.py'],rule)
                save(work/'response.json',{'proposal':{'source_text':text},'model':None,'rule_id':rule})
                compiled=compile_proposal(c['base_source'],{'edits':[{'path':'textbook_sharing/layout.py','old':c['base_source']['textbook_sharing/layout.py'],'new':text}]})
                save(work/'compiled.json',compiled);student=span.student_request({'base_source':c['base_source'],'visible_contract':ordinary['task_packet'],'visible_feedback':ordinary['visible_history']},span.CONTEXT_VERSION,16384)
                save(work/'student_request.json',student);(work/'student_action.json').write_text(canonical_action(compiled['patch'],student)+'\n')
                try:
                    e=encode_policy_action(tokenizer,student,compiled['patch'],16384,1024);attempt['student_budget']={'prompt_tokens':e.prompt_tokens,'completion_tokens_including_EOS':e.completion_tokens}
                except PolicyBudgetError as exc:attempt.update(status='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS',student_budget=exc.details)
            except (ValueError,KeyError,TypeError) as exc:attempt.update(status='RULE_PROPOSAL_REJECTED_NO_LABEL',error=type(exc).__name__+': '+str(exc))
            attempt.update(ended_at_utc=now(),usage={'wall_seconds':time.monotonic()-began,'process_CPU_seconds':time.process_time()-cpu,'model_inferences':0})
            save(work/'attempt.json',attempt)
    result={'status':'ALL16_ORIGINAL_RULE_ATTEMPTS_TERMINAL_BEFORE_GPT','at_utc':now(),'attempts':16,'model_calls':0,
        'proposal_collection_sha256':proposal_sha,'acceptance_path':str((folder/'acceptance.json').resolve()),
        'acceptance_sha256':hashlib.sha256((folder/'acceptance.json').read_bytes()).hexdigest()}
    save(output/'rules_ready.json',result);return result


def scan(definition,plan,parents,contexts,registry,state,output,tokenizer):
    matrix=span.raw_matrix(plan) if (Path(plan['output_root'])/'matrix.json').exists() else {}
    lookup={c['initial_state_id']:c for c in contexts};seen={sid:{source_identity(c['base_source']):'initial_source'} for sid,c in lookup.items()}
    for cell in state['cells']:
        if cell.get('candidate_file'):seen[cell['initial_state_id']][source_identity(read(output/cell['candidate_file'])['candidate_source'])]=read(output/cell['candidate_file'])['candidate_id']
    save(output/'effective_registry.json',registry)
    ready=read(output/'rules_ready.json')
    validate_rules_ready(ready,definition['proposal_collection_sha256'],Path(ready['acceptance_path']))
    for cell in state['cells']:
        if cell['status']!='NOT_RUN':continue
        c=lookup[cell['initial_state_id']];parent=parents[cell['parent_collection']]
        if cell['producer']=='rule':
            work=output/'raw_rules'/cell['initial_state_id']/cell['rule_id'];attempt=read(work/'attempt.json');cell['original_proposal_status']=attempt['status']
            if attempt['status']!='RULE_RETURNED':cell['status']=attempt['status'];continue
            compiled=read(work/'compiled.json');text=read(work/'response.json')['proposal']['source_text']
            expected=compile_proposal(c['base_source'],{'edits':[{'path':'textbook_sharing/layout.py','old':c['base_source']['textbook_sharing/layout.py'],'new':text}]})
            if compiled!=expected:raise ValueError('Actualoriginalrulecompilerproofdiffers')
            proposal={'source':compiled['candidate_source'],'patch':compiled['patch'],'request':c['original_request_value'],'attempt':attempt}
        else:
            raw=matrix.get((cell['initial_state_id'],cell['trial_id']))
            if not raw or raw['status'] in ('NOT_RUN','DISPATCHED'):continue
            work=Path(plan['output_root'])/cell['initial_state_id']/('trial_'+str(cell['trial_id']));attempt=read(work/'attempt.json')
            if datetime.fromisoformat(attempt['started_at_utc'])<datetime.fromisoformat(ready['at_utc']):raise ValueError('GPTstartedbeforepredeclaredactualrulefirstorder')
            cell['original_proposal_status']=raw['status']
            proposal=span.verify_raw(plan,c,cell['trial_id'],work,tokenizer,definition['proposal_collection_sha256'])
            if proposal['status']!='ELIGIBLE_UNIQUE_CHECK_PENDING':cell['status']=proposal['status'];continue
        identity=source_identity(proposal['source'])
        if identity in seen[cell['initial_state_id']]:cell.update(status='SEMANTIC_DUPLICATE_BEFORE_PHYSICS',duplicate_of=seen[cell['initial_state_id']][identity]);continue
        row=joint_candidate_row(c,parent,proposal,cell,work)
        proof=span.student_identity_proof(c,row,str(work))
        try:e=encode_policy_action(tokenizer,proof['ordinary_student_request'],row['candidate_patch'],16384,1024)
        except PolicyBudgetError as exc:cell.update(status='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS',student_budget=exc.details);continue
        baseline=physical.baseline_bindings(c,parent,registry,row);where=output/'candidates'/row['candidate_id'];where.mkdir(parents=True,exist_ok=False)
        span.workspace(Path(parent['manifest']['source_pack']),parent['files'],row['candidate_source'],where/'source')
        save(where/'candidate.json',row);save(where/'baseline_adoption.json',baseline);save(where/'student_identity_proof.json',proof)
        # Original raw producer artifacts stay unchanged intheir ownrawroot; retain exact copies for this canonicalcandidate.
        shutil.copytree(work,where/'original_proposal')
        cell.update(status='PHYSICAL_PENDING',candidate_file=str((where/'candidate.json').relative_to(output)),
            baseline_adoption=str((where/'baseline_adoption.json').relative_to(output)),student_budget={'prompt_tokens':e.prompt_tokens,'completion_tokens_including_EOS':e.completion_tokens},
            points=[{'configuration_id':k,'status':'NOT_RUN'} for k in baseline])
        seen[cell['initial_state_id']][identity]=row['candidate_id']


def joint_candidate_row(context,parent,proposal,cell,raw_directory):
    row=span.candidate_row(context,parent,proposal,cell['trial_id'])
    row['candidate_id']='NF_joint__'+cell['initial_state_id']+'__'+cell['producer']+'_'+str(cell['trial_id'])
    metadata=row['proposal_generation']
    metadata.update(joint_trial_id=cell['joint_trial_id'],producer=cell['producer'],rule_id=cell['rule_id'],raw_directory=str(raw_directory))
    if cell['producer']=='rule':
        metadata.update(proposer_cohort='original_eight_planning_rules_train_proposals',teacher_mode='train_collection_rules',
            model=None,seed=None,model_inferences=0)
    return row


def producer_funnel(state):
    return {producer:{'declared_attempts':16,
        'cell_status_counts':dict(Counter(c['status'] for c in state['cells'] if c['producer']==producer)),
        'unique_candidate_sources_enrolled':sum(bool(c.get('candidate_file')) for c in state['cells'] if c['producer']==producer),
        'admitted_complete_domain_candidates':sum(c['status']=='ADMITTED_COMPLETE_DOMAIN' for c in state['cells'] if c['producer']==producer),
        'points':dict(Counter(p['status'] for c in state['cells'] if c['producer']==producer for p in c.get('points',[])))}
        for producer in ['rule','GPT']}


def derive(definition,parents,registry,state,output,tokenizer,folder):
    span.derive(definition,parents,registry,state,output,tokenizer,folder)
    if (output/'student_selection.json').exists():
        value=nf.nf_counts(read(output/'student_selection.json'));value.update(proposer_cohort='fixed_original_rules_then_GPT_joint16_per_context',planned_proposals=32,
            raw_GPT_proposals=16,raw_rule_proposals=16,maximum_unique_contexts=2,old_pools_merged=False,
            proposer_pool='This prospective joint32 pool only: original16rules plus fresh16GPT; producer-specific raw roots and fixed source order retained.',
            producer_results=producer_funnel(state),
            counting='Joint32 candidates share two fixed circuit-domain contexts and one compiler lineage. T1/T2 and T3/T4 are matched methods, never independent states. No old pool is included.')
        save(output/'student_selection.json',value)


def cycle(definition,plan,parents,contexts,registry,state,output,tokenizer,folder,check_implementation):
    validate_rules_ready(read(output/'rules_ready.json'),definition['proposal_collection_sha256'],folder/'acceptance.json')
    scan(definition,plan,parents,contexts,registry,state,output,tokenizer);save(output/'state.json',state)
    physical.physical_pass(definition,parents,registry,state,output,execute_point=nf.point_call,check_implementation=check_implementation)
    if state['status'].startswith('PAUSED'):return
    derive(definition,parents,registry,state,output,tokenizer,folder)
    if (Path(plan['output_root'])/'completion.json').exists():
        scan(definition,plan,parents,contexts,registry,state,output,tokenizer);save(output/'state.json',state)
        if any(c['status']=='PHYSICAL_PENDING' for c in state['cells']):return
        matrix=span.raw_matrix(plan)
        for c in state['cells']:
            if c['status']=='NOT_RUN':
                if c['producer']!='GPT' or matrix[(c['initial_state_id'],c['trial_id'])]['status']!='NOT_RUN':raise ValueError('Unresolvedreturnedslotaftercompletion')
                c['status']='ORIGINAL_NOT_RUN_PROPOSAL_WINDOW_ENDED'
        derive(definition,parents,registry,state,output,tokenizer,folder)
        if not state['status'].startswith('PAUSED'):state['status']='COMPLETE'


def completion(state):
    points=[p for c in state['cells'] for p in c.get('points',[])]
    return {'status':state['status'],'declared_raw_proposals':32,'raw_source_counts':{'rule':16,'GPT':16},
        'producer_results':producer_funnel(state),
        'actual_reserved_candidate_points':sum(p['status']!='NOT_RUN' for p in points),'maximum_candidate_points':288,
        'point_status_counts':dict(Counter(p['status'] for p in points)),
        'selection_funnel':state.get('selection_funnel'),'physical_domain_contexts':2,'new_initial_source_ASTs':0,'new_source_lineages':0,
        'new_model_calls_in_consumer':0,'new_baseline_points':0,'automatic_retry':False,'at_utc':now()}


def run(path):
    path=Path(path).resolve();d,plan,parents,contexts,registry=load_acceptance(path);out=Path(d['output_root']);out.relative_to(ROOT/'runs/train_collection');out.mkdir(parents=True,exist_ok=True)
    with (out/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (out/'acceptance.json').exists() and read(out/'acceptance.json')!=d:raise ValueError('Otheracceptanceownsoutput')
        save(out/'acceptance.json',d)
        state=read(out/'state.json') if (out/'state.json').exists() else {'status':'RUNNING','role':ROLE,'cells':copy.deepcopy(d['slots']),
            'started_at_utc':now(),'deadline_utc':(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat(),'resource_samples':[],'metadata_waits':[]}
        if state['role']!=ROLE or [(c['initial_state_id'],c['producer'],c['trial_id']) for c in state['cells']]!=[(c['initial_state_id'],c['producer'],c['trial_id']) for c in d['slots']]:raise ValueError('Keepall32originalslots')
        physical.mark_orphaned_reservations(state)
        if state['status'].startswith('PAUSED') or state['status'] in ('COMPLETE','WINDOW_ENDED'):return completion(state)
        from transformers import AutoTokenizer
        cache=read(ROOT/'configs/training/backbone_cache.json');nf.validate_tokenizer(cache['snapshot'],Path(d['proposal_collection']).parent)
        tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
        validate_rules_ready(read(out/'rules_ready.json'),d['proposal_collection_sha256'],path)
        while not state['status'].startswith('PAUSED') and datetime.now(timezone.utc)<datetime.fromisoformat(state['deadline_utc']):
            state.update(status='RUNNING',coordinator_pid=os.getpid())
            try:cycle(d,plan,parents,contexts,registry,state,out,tokenizer,path.parent,lambda:nf.verify_code(path,d))
            except json.JSONDecodeError as exc:state['metadata_waits'].append({'at_utc':now(),'error':str(exc)});save(out/'state.json',state);time.sleep(5);continue
            except Exception as exc:state.update(status='PAUSED_UNKNOWN',error=type(exc).__name__+': '+str(exc));break
            if state['status'].startswith('PAUSED') or state['status']=='COMPLETE' or state.get('dispatch_window_ended'):break
            if any(c['status']=='PHYSICAL_PENDING' for c in state['cells']):continue
            save(out/'state.json',state);time.sleep(5)
        if state.get('dispatch_window_ended') or (not state['status'].startswith('PAUSED') and state['status']!='COMPLETE'):state['status']='WINDOW_ENDED'
        if state['status'].startswith('PAUSED'):physical.invalidate_derivation(out)
        state.update(coordinator_pid=None,ended_at_utc=now());save(out/'state.json',state);result=completion(state);save(out/'completion.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group(required=True)
    for name in ['prepare','baseline-control','freeze','validate-only','materialize-rules','execute']:m.add_argument('--'+name,action='store_true')
    for name in ['proposal','folder','output-root','plan','report']:p.add_argument('--'+name,type=Path)
    a=p.parse_args()
    if a.prepare:r=prepare(a.proposal,a.folder,a.output_root)
    elif a.baseline_control:r=baseline_control(a.plan,a.report)
    elif a.freeze:r=freeze(a.plan)
    elif a.validate_only:r={'status':'VALIDATED_JOINT32_NO_CALLS','slots':load_acceptance(a.plan)[0]['declared_proposals']}
    elif a.materialize_rules:
        d,_,_,contexts,_=load_acceptance(a.plan);out=Path(d['output_root']);out.mkdir(parents=True,exist_ok=True)
        from transformers import AutoTokenizer
        cache=read(ROOT/'configs/training/backbone_cache.json');nf.validate_tokenizer(cache['snapshot'],Path(d['proposal_collection']).parent)
        tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
        with (out/'coordinator.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=materialize_rules(a.plan.resolve().parent,contexts,out,tokenizer)
    else:r=run(a.plan)
    print(json.dumps(r,indent=2,allow_nan=False))
