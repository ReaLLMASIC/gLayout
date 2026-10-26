"""Natural-terminal span16: one worker, max144 fresh candidate points; old LIVE unchanged."""
import argparse
import copy
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts import evaluate_train_span_proposals as span
from scripts import evaluate_matched_t0_proposals as physical
from scripts.prepare_natural_terminal_baselines import packet as baseline_packet
from scripts.audit_train_pair_nf_rc import contracted_devices
from src.device_intent import compare_device_intent
from src.train_natural_terminal_span_bundle import load_bundle,validate_tokenizer,canonical_immutable_registries
from src.training import TrustedPhysicalStore
from src.training_selection_v2 import make_rule

read,save,now=physical.read,physical.save,physical.now
ROLE='natural_terminal_literal_span16_physical_followup_train_only'
CODE=tuple(dict.fromkeys((*span.CODE,'scripts/evaluate_natural_terminal_span_proposals.py',
    'scripts/prepare_natural_terminal_baselines.py','scripts/audit_train_pair_nf_rc.py','src/train_natural_terminal_span_bundle.py')))
ORDER={'mode':'train_collection_action_gpt','trials':list(range(1,9))}
RESOURCES={'workers':1,'cpus_per_job':2,'memory_GiB_per_job':8,'generation_timeout_seconds':240,
    'evaluator_timeout_seconds':720,'maximum_dispatch_hours':8,'maximum_new_candidate_points':144,
    'maximum_new_baseline_points':0,'actual_busy_cores_plus_new_limit':24,'RAM_used_GiB_limit':190,'minimum_free_disk_GiB':4}


def packet(manifest,state,points,baselines):
    """Reproduce the natural-terminal context using real controls plus the exact readonly caller."""
    summaries=[{'configuration_id':p['configuration_id'],'S0':baselines[p['configuration_id']]['checked']['S0'],
        'S1':baselines[p['configuration_id']]['checked']['S1'],'S2':baselines[p['configuration_id']]['checked']['S2'],
        'objective':baselines[p['configuration_id']]['checked']['objective'],
        'failure_class':baselines[p['configuration_id']]['checked'].get('failure_class'),
        'reason':baselines[p['configuration_id']]['checked'].get('reason')} for p in points]
    ordinary,_,_=baseline_packet(manifest,state,points,summaries)
    return ordinary['task_packet'],ordinary['visible_history']


def proposal_definition(path,folder):
    path=Path(path).resolve();bundle=path.parent;plan=load_bundle(path);parents={};contexts=[]
    for name in ['train_span_proposer.py','student_interface.py']:
        if (ROOT/'src'/name).read_bytes()!=(bundle/'interface/src'/name).read_bytes():raise ValueError('natural-terminal compiler/ordinary mapper changed: '+name)
    if (ROOT/'src/train_natural_terminal_span_bundle.py').read_bytes()!=(bundle/'interface/src/train_span_bundle.py').read_bytes():
        raise ValueError('Use the actual separately frozen natural-terminal loader, never the old context assignment')
    for entry in plan['contexts']:
        state=read(bundle/entry['initial_state']);collection=read(bundle/entry['parent_collection'])
        registry=read(bundle/entry['effective_registry']);name=entry['parent_collection_id']
        if state['origin']!='natural' or state['initial_state_id']!=entry['initial_state_id']:
            raise ValueError('natural-terminal initial source ancestry changed')
        runtime=copy.deepcopy(collection)
        runtime.update(output_root=str(folder/'parents'/name),physical={k:RESOURCES[k] for k in ['generation_timeout_seconds','evaluator_timeout_seconds']},
            label_rule_path=str(bundle/entry['label_rule']),status='frozen_formal_control_runtime_binding',
            runtime_view_scope='Metadata binding to the already completed exact formal18 controls; not a prior model collection or new physical evidence')
        parents[name]={'manifest':runtime,'registry':registry,'states':[state],'files':collection['source_files'],'collector':sys.modules[__name__]}
        contexts.append({**entry,'state':state,'base_source':state['base_source'],'parent_collection':name,
            'original_request_value':read(bundle/entry['original_request']),'teacher_request_value':read(bundle/entry['teacher_request']),
            'materialized_task_packet':str(folder/'contexts'/state['initial_state_id']/'task_packet.json'),
            'materialized_visible_history':str(folder/'contexts'/state['initial_state_id']/'visible_history.json')})
    canonical,aliases=canonical_immutable_registries([p['registry'] for p in parents.values()])
    for parent,registry_view in zip(parents.values(),canonical):parent['registry']=registry_view
    registry=physical.merge_registries(canonical)
    if len(registry['configurations'])!=18:raise ValueError('Keep both full nine-point natural-terminal domains')
    return plan,parents,contexts,registry


def prepare(proposal,folder,output_root):
    folder=Path(folder).resolve();plan,parents,contexts,_=proposal_definition(proposal,folder)
    folder.mkdir(parents=True,exist_ok=False);output_root=Path(output_root).resolve();output_root.relative_to(ROOT/'runs/train_collection')
    for name in CODE:
        target=folder/'interface'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    (folder/'interface/base_selection.py').write_text(span.frozen_base_selection((ROOT/'src/training.py').read_text()))
    for context in contexts:
        name=context['parent_collection'];parent=parents[name];sid=context['initial_state_id']
        save(folder/'parents'/name/'runtime_binding.json',parent['manifest'])
        save(folder/'parents'/name/sid/'baseline_results.json',read(Path(proposal).resolve().parent/context['baseline_results']))
        save(folder/'contexts'/sid/'task_packet.json',context['original_request_value']['task_packet'])
        save(folder/'contexts'/sid/'visible_history.json',context['original_request_value']['visible_history'])
        # Trial_id1..8 is the original v2 ordering schema, not a claim of ACTION producer identity.
        save(folder/'rules'/(name+'.json'),make_rule(read(parent['manifest']['label_rule_path']),ORDER))
    definition={'status':'DRAFT','role':ROLE,'proposal_collection':str(Path(proposal).resolve()),
        'proposal_collection_sha256':hashlib.sha256(Path(proposal).read_bytes()).hexdigest(),
        'created_at_utc':now(),'evidence_root':str(ROOT),'output_root':str(output_root),'physical':RESOURCES,
        'contexts':[{'initial_state_id':c['initial_state_id'],'parent_collection':c['parent_collection']} for c in contexts],
        'trials':list(range(1,9)),'declared_proposals':16,'implementation_files':list(CODE),
        'new_initial_source_ASTs':2,'new_source_lineages':0,'physical_domain_contexts':2,'new_physical_domain_contexts':0,
        'raw_input_policy':'Only this separate natural-terminal GPT span16 pool; no old span16, T0 or rules pool merge.',
        'selection':'Exact inherited Point/Family scopes, minimum effect, ties and v2 actual trial_id earliest representative. No opposite preference prelabelled.',
        'label_order_schema_only':ORDER,'teacher_identity':'Actual literal-span GPT source role remains required; ORDER is only the original trial_id selection interface.',
        'new_loop_rule':'After every physical_pass and before producer-completion handling, rescan actual raw matrix; late eligible candidates continue PHYSICAL_PENDING. Never classify returned rejection as NOT_RUN.',
        'failure_policy':'Durable point reservations/currentTrustedStore/fullraw cost, resource gates, unknownstop and no automatic retries inherited from the existing executor.',
        'task_identity_mapping':'Only backend task_id is normalized. Raw teacher, response, compiled ACTION retained; exact source/physical contract/history and full readonly entrypoint remain visible to both teacher/student.'}
    _,aliases=canonical_immutable_registries([read(Path(proposal).resolve().parent/c['effective_registry']) for c in contexts])
    save(folder/'immutable_source_aliases.json',aliases)
    save(folder/'acceptance.json',definition);return definition


def verify_code(path,definition):
    span.verify_code(path,definition)


def load_acceptance(path,require_frozen=True):
    path=Path(path).resolve();definition=read(path)
    if (definition.get('status')!=('frozen' if require_frozen else 'DRAFT') or definition.get('role')!=ROLE
            or definition.get('physical')!=RESOURCES or definition.get('implementation_files')!=list(CODE)
            or definition.get('trials')!=list(range(1,9)) or definition.get('declared_proposals')!=16
            or definition.get('evidence_root')!=str(ROOT)):
        raise ValueError('Use only the independently reviewed fixed natural-terminal16 acceptance')
    verify_code(path,definition);plan,parents,contexts,registry=proposal_definition(definition['proposal_collection'],path.parent)
    _,aliases=canonical_immutable_registries([read(Path(definition['proposal_collection']).parent/c['effective_registry']) for c in contexts])
    if read(path.parent/'immutable_source_aliases.json')!=aliases:
        raise ValueError('The prospective immutable-source alias proof changed')
    if hashlib.sha256(Path(definition['proposal_collection']).read_bytes()).hexdigest()!=definition['proposal_collection_sha256']:
        raise ValueError('natural-terminal proposal freeze changed')
    if definition['contexts']!=[{'initial_state_id':c['initial_state_id'],'parent_collection':c['parent_collection']} for c in contexts]:
        raise ValueError('Do not add, remove or duplicate natural-terminal contexts')
    for context in contexts:
        name=context['parent_collection'];parent=parents[name];sid=context['initial_state_id']
        if read(path.parent/'parents'/name/'runtime_binding.json')!=parent['manifest']:raise ValueError('Formal control runtime view changed')
        if read(path.parent/'rules'/(name+'.json'))!=make_rule(read(parent['manifest']['label_rule_path']),ORDER):raise ValueError('natural-terminal thresholds or trial order changed')
        if read(context['materialized_task_packet'])!=context['original_request_value']['task_packet'] or read(context['materialized_visible_history'])!=context['original_request_value']['visible_history']:
            raise ValueError('natural-terminal complete readonly entrypoint/source/feedback context changed')
        if read(path.parent/'parents'/name/sid/'baseline_results.json')!=read(Path(definition['proposal_collection']).parent/context['baseline_results']):
            raise ValueError('Do not substitute controls')
    if require_frozen and any(p.stat().st_mode&0o222 for p in [path.parent,*path.parent.rglob('*')]):raise ValueError('natural-terminal acceptance must be readonly')
    return definition,plan,parents,contexts,registry


def baseline_control(path,report):
    began=time.monotonic(); cpu=time.process_time()
    definition,_,parents,contexts,registry=load_acceptance(path,False);records=[]
    for context in contexts:
        proposal={'request':context['teacher_request_value'],'source':context['base_source'],'patch':'','attempt':{}}
        row=span.candidate_row(context,parents[context['parent_collection']],proposal,1)
        records.append({'initial_state_id':context['initial_state_id'],
            'actual_points':physical.baseline_bindings(context,parents[context['parent_collection']],registry,row),
            'student_identity_proof':span.student_identity_proof(context,row)})
    result={'status':'ACTUAL_NATURAL_TERMINAL_FORMAL18_BASELINE_AND_READONLY_CALLER_CONTROL','records':records,
        'actual_baseline_points_re_read':18,'actual_wall_seconds':time.monotonic()-began,
        'actual_CPU_seconds':time.process_time()-cpu,'new_model_calls':0,'new_physical_calls':0};save(report,result)
    return {k:v for k,v in result.items() if k!='records'}


def freeze(path):
    path=Path(path).resolve();definition,_,_,_,_=load_acceptance(path,False)
    control=read(path.parent/'baseline_control.json')
    if control.get('actual_baseline_points_re_read')!=18 or control.get('status')!='ACTUAL_NATURAL_TERMINAL_FORMAL18_BASELINE_AND_READONLY_CALLER_CONTROL':
        raise ValueError('Actual18-control read-only proof required before freeze')
    definition.update(status='frozen',frozen_at_utc=now());save(path,definition)
    for p in sorted(path.parent.rglob('*'),key=lambda p:len(p.parts),reverse=True):p.chmod(0o555 if p.is_dir() else 0o444)
    path.parent.chmod(0o555);load_acceptance(path)
    return {'status':'FROZEN_NATURAL_TERMINAL_PHYSICAL_ACCEPTANCE_NO_CALLS','new_model_calls':0,'new_physical_calls':0}


def finish_cycle(definition,plan,parents,contexts,registry,state,output,tokenizer,folder):
    """Crucially, producer completion may arrive while the physical pass runs."""
    if state['status'].startswith('PAUSED'):return
    if (Path(plan['output_root'])/'completion.json').exists():
        span.scan_returned(definition,plan,parents,contexts,registry,state,output,tokenizer)
        save(output/'state.json',state)
        if any(c['status']=='PHYSICAL_PENDING' for c in state['cells']):return
        matrix=span.raw_matrix(plan)
        for cell in state['cells']:
            if cell['status']=='NOT_RUN':
                actual=matrix[(cell['initial_state_id'],cell['trial_id'])]['status']
                if actual!='NOT_RUN':raise ValueError('Completed producer has an unresolved returned/dispatched natural-terminal slot')
                cell['status']='ORIGINAL_NOT_RUN_PROPOSAL_WINDOW_ENDED'
        derive_contexts(definition,parents,registry,state,output,tokenizer,folder)
        if not state['status'].startswith('PAUSED'):state['status']='COMPLETE'
    elif not any(c['status'] in ('NOT_RUN','PHYSICAL_PENDING') for c in state['cells']):state['status']='COMPLETE'


def context_counts(value):
    result=copy.deepcopy(value)
    for key in ['initial_contexts_reused','original_contexts_reused','additional_independent_contexts']:result.pop(key,None)
    result.update(physical_domain_contexts=2,new_physical_domain_contexts=0,new_initial_source_ASTs=2,new_source_lineages=0,
        proposer_pool='separate_natural-terminal_literal_span_GPT16_not_merged_with_rules_or_old16')
    return result


def derive_contexts(definition,parents,registry,state,output,tokenizer,folder):
    span.derive(definition,parents,registry,state,output,tokenizer,folder)
    if (output/'student_selection.json').exists():save(output/'student_selection.json',context_counts(read(output/'student_selection.json')))


def audit_full_rc(run,point):
    path=Path(run)/'evidence/validation.json'
    if not path.exists() or not read(path).get('assessment',{}).get('S1'):
        return {'status':'NOT_APPLICABLE_BEFORE_S1','not_a_negative_RC_label':True}
    pex=read(path)['artifacts']['pex']
    if pex['ports']!=point['parameters']['circuit']['ports']:raise ValueError('Extracted port order differs from immutable N')
    view=contracted_devices((Path(run)/'evidence'/pex['netlist']).read_text(),pex['top_cell'],pex['ports'])
    graph=compare_device_intent(view,(Path(run)/'trusted/references'/(point['configuration_id']+'.spice')).read_text())
    if not graph['is_clean']:raise ValueError('Unsimplified fullRC connection graph differs from independent per-finger N')
    return graph


def serial_physical_pass(definition, parents, registry, state, output, check_implementation, *,
                         sample=physical.resource_sample, execute_point=physical.point_call):
    store = TrustedPhysicalStore(ROOT, registry)
    while physical.pending_points(state) and not state['status'].startswith('PAUSED'):
        if datetime.now(timezone.utc) >= datetime.fromisoformat(state['deadline_utc']):
            state['dispatch_window_ended'] = True; return
        resource = sample(); state['resource_samples'].append(resource)
        if resource['available_disk_GiB'] < 4: state['status'] = 'PAUSED_STORAGE'; return
        if resource['actual_busy_cores'] + 2 > 24 or resource['RAM_used_GiB'] > 190:
            save(output / 'state.json', state); time.sleep(5); continue
        if sum(c.get('physical_point_reservations', 0) for c in state['cells']) >= 144:
            raise ValueError('The original maximum144 point reservations is exhausted')
        check_implementation(); cell, job = physical.pending_points(state)[0]
        row = read(output / cell['candidate_file']); point = store._configuration(row, job['configuration_id'])
        folder = output / 'candidates' / row['candidate_id'] / 'points' / job['configuration_id']
        if folder.exists():
            job['status'] = 'UNRESOLVED_EXISTING_POINT_NO_RETRY'; state['status'] = 'PAUSED_UNKNOWN'; return
        job.update(status='DISPATCH_RESERVED', reserved_at_utc=now(), resources_before_dispatch=resource)
        cell['physical_point_reservations'] = cell.get('physical_point_reservations', 0) + 1; save(output / 'state.json', state)
        try:
            result = execute_point(parents[cell['parent_collection']], point, row,
                (output / cell['candidate_file']).parent / 'source', folder, state['deadline_utc'])
            run = Path(result['run_directory']).resolve(); began = time.monotonic(); cpu = time.process_time()
            graph = {'status': 'RC_GRAPH_NOT_YET_READ'}
            try:
                graph = audit_full_rc(run, point)
            except Exception as exc:
                graph = {'status': 'UNKNOWN_RC_GRAPH_QUARANTINE', 'actual_audit': graph,
                    'error': type(exc).__name__ + ': ' + str(exc)}
                raise
            finally:
                save(folder / 'full_RC_device_graph_audit.json', {'audit': graph, 'wall_seconds': time.monotonic() - began,
                    'CPU_seconds': time.process_time() - cpu, 'simulation_netlist_simplified': False})
            job['evidence_path'] = str((run / 'manifest.json').relative_to(ROOT))
            baseline = read(output / cell['baseline_adoption'])[job['configuration_id']]
            row['outcomes'].append({'configuration_id': job['configuration_id'], 'role': point['domain_role'],
                'evidence_path': job['evidence_path'], 'baseline_evidence_path': baseline['evidence_path'],
                'baseline_candidate_id': baseline['baseline_candidate_id']})
            save(output / cell['candidate_file'], row)
            checked = store._read_run(job['evidence_path'], row, job['configuration_id'], row['candidate_source'], row['candidate_id'])
            if checked.get('point_evaluation_complete') is not True:
                raise ValueError('Partial corner evidence is unknown,not a candidate negative')
            job.update(checked=checked, status='COMPLETE', returned_at_utc=now())
        except Exception as exc:
            job.update(status='UNKNOWN_NO_RETRY', error=type(exc).__name__ + ': ' + str(exc), returned_at_utc=now())
            cell['status'] = 'QUARANTINED_UNKNOWN'; state['status'] = 'PAUSED_UNKNOWN'
        save(output / 'state.json', state)


def cycle(definition,plan,parents,contexts,registry,state,output,tokenizer,folder,check_implementation):
    span.scan_returned(definition,plan,parents,contexts,registry,state,output,tokenizer);save(output/'state.json',state)
    serial_physical_pass(definition,parents,registry,state,output,check_implementation)
    if state['status'].startswith('PAUSED'):return
    derive_contexts(definition,parents,registry,state,output,tokenizer,folder)
    finish_cycle(definition,plan,parents,contexts,registry,state,output,tokenizer,folder)


def run(path):
    path=Path(path).resolve();definition,plan,parents,contexts,registry=load_acceptance(path);output=Path(definition['output_root'])
    output.relative_to(ROOT/'runs/train_collection');output.mkdir(parents=True,exist_ok=True)
    with (output/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (output/'acceptance.json').exists() and read(output/'acceptance.json')!=definition:raise ValueError('Different acceptance already owns output')
        save(output/'acceptance.json',definition);state=read(output/'state.json') if (output/'state.json').exists() else span.initial_state(definition)
        if state['role'] not in (span.ROLE,ROLE):raise ValueError('Different natural-terminal coordinator role')
        if [(c['initial_state_id'],c['trial_id']) for c in state['cells']] != [(c['initial_state_id'],trial) for c in definition['contexts'] for trial in definition['trials']]:
            raise ValueError('Resume must preserve the complete original sixteen natural-terminal slots')
        state['role']=ROLE;physical.mark_orphaned_reservations(state)
        if state['status'].startswith('PAUSED') or state['status'] in ('COMPLETE','WINDOW_ENDED'):return context_counts(span.completion(state))
        from transformers import AutoTokenizer
        cache=read(ROOT/'configs/training/backbone_cache.json');validate_tokenizer(cache['snapshot'],Path(definition['proposal_collection']).parent)
        tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
        while datetime.now(timezone.utc)<datetime.fromisoformat(state['deadline_utc']):
            state.update(status='RUNNING',coordinator_pid=os.getpid())
            try:
                if not (Path(plan['output_root'])/'matrix.json').exists():
                    state['status']='WAITING_FOR_FROZEN_PROPOSALS';save(output/'state.json',state);time.sleep(5);continue
                cycle(definition,plan,parents,contexts,registry,state,output,tokenizer,path.parent,lambda:verify_code(path,definition))
            except json.JSONDecodeError as exc:
                state.setdefault('metadata_waits',[]).append({'at_utc':now(),'error':str(exc)});save(output/'state.json',state);time.sleep(5);continue
            except Exception as exc:state.update(status='PAUSED_UNKNOWN',error=type(exc).__name__+': '+str(exc));break
            if state['status'].startswith('PAUSED') or state['status']=='COMPLETE' or state.get('dispatch_window_ended'):break
            if any(c['status']=='PHYSICAL_PENDING' for c in state['cells']):continue
            save(output/'state.json',state);time.sleep(5)
        else:state['status']='WINDOW_ENDED'
        if state.get('dispatch_window_ended') and not state['status'].startswith('PAUSED'):state['status']='WINDOW_ENDED'
        if state['status'].startswith('PAUSED'):physical.invalidate_derivation(output)
        state.update(coordinator_pid=None,ended_at_utc=now());save(output/'state.json',state)
        if (output/'student_selection.json').exists():save(output/'student_selection.json',context_counts(read(output/'student_selection.json')))
        result=context_counts(span.completion(state));save(output/'completion.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group(required=True)
    for name in ['prepare','baseline-control','freeze','validate-only','execute']:m.add_argument('--'+name,action='store_true')
    for name in ['proposal','folder','output-root','plan','report']:p.add_argument('--'+name,type=Path)
    a=p.parse_args()
    if a.prepare:result=prepare(a.proposal,a.folder,a.output_root)
    elif a.baseline_control:result=baseline_control(a.plan,a.report)
    elif a.freeze:result=freeze(a.plan)
    elif a.validate_only:result={'status':'VALIDATED_natural-terminal_ACCEPTANCE_NO_CALLS','declared_proposals':load_acceptance(a.plan)[0]['declared_proposals']}
    else:result=run(a.plan)
    print(json.dumps(result,indent=2,allow_nan=False))
