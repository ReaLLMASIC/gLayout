"""Draft a new minimal-edit source teacher; never modify or launch a collection."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import load,packet
from src.local_model_adapter import source_proposal_prompt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-collection',type=Path,required=True)
    p.add_argument('--collection-id',required=True);p.add_argument('--failure-only',action='store_true');a=p.parse_args()
    base,registry,states,_=load(a.base_collection.resolve())
    domain=[point for point in registry['configurations'] if point['parent_lineage']==states[0]['parent_lineage'] and
            (not states[0].get('task_id') or point['contract']['task_id']==states[0]['task_id'])]
    if len(domain)!=9:raise ValueError('Expected this source task to have exactly nine train points')
    cid=domain[0]['parameters']['circuit']['circuit_id']
    if a.failure_only:
        states=[state for state in states if state.get('ancestry',{}).get('producer_seed')==(379 if cid=='C05' else 241)]
        if len(states)!=1:raise ValueError('Expected one genuinely observed generation-failure initial program')
    for state in states:
        old=state['initial_state_id'];state['initial_state_id']=old+'__minimal_GPT_teacher_v1'
        state['ancestry']={**state['ancestry'],'prospective_context_copy_of':old,'teacher_instruction_version':'minimal_source_edit_v1','old_outcomes_relabelled':False}
    out=ROOT/'runtime/collection_preparation'/(a.collection_id+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
    (out/'initial_states.jsonl').write_text(''.join(json.dumps(state,ensure_ascii=False)+'\n' for state in states))
    draft={'status':'DRAFT_NOT_FROZEN','role':'train_collection','collection_id':a.collection_id,'base_collection_manifest':str(a.base_collection.resolve()),
        'source_pack':base['source_pack'],'trusted_bundle':base['trusted_bundle'],'registry_path':base['registry_path'],'label_rule_path':base['label_rule_path'],
        'initial_states_path':str(out/'initial_states.jsonl'),'initial_state_count':len(states),'editable_paths':['textbook_sharing/layout.py'],
        'gold_controls':base.get('gold_controls',{}),'teacher_instruction_version':'minimal_source_edit_v1',
        'student_preselection':{'student_interface_version':'ordinary_policy_action_v1','max_new_tokens':1024,'max_context_tokens':8192,'stage':'before_physics'},
        'sampling':{'mode':'train_collection_source_gpt','backend':'isolated_gpt_cli','model':'gpt-6.1-sol','reasoning_effort':'high',
            'trials':list(range(1,9)),'proposal_workers':2,'seed':None,'seed_control_available':False,'proposal_format':'full_source_teacher',
            'max_new_tokens':3072,'max_context_tokens':8192,'timeout_seconds':240},
        'physical':{**base['physical'],'workers':2},'budget':{**base['budget'],'initial_batch_initial_states':len(states)},
        'deduplication':base.get('deduplication',{'method':'exact_ast_dump','include_attributes':False,'numeric_normalization':False}),'prospective_change':'Preserve every unaffected line/comment/docstring/import/name/order. Reject oversized canonical ordinary actions before physics, retaining complete raw source and all generation costs. Never repair/shorten a proposal.',
        'output_budget_scope':'3072 pinned student-tokenizer tokens for complete source JSON + EOS. Distinct student preselection is ordinary ACTION_JSON <=1024 and complete source/contract/action <=8192.',
        'isolation':{'fresh_ephemeral_session_per_trial':True,'native_tools':False,'no_sampling_seed_exposed':True,'concurrent_slots_global':2},
        'source_program_counting':'New teacher contexts do not create independent source programs or lineages. Count useful initial programs and unique terminal ASTs separately from pair counts.',
        'new_baseline9_per_state_and_new_teacher_proposals_required':True,'old_development_outcomes_admitted':False,'formal_collection_launched':False}
    (out/'preparation.json').write_text(json.dumps(draft,indent=2)+'\n')
    # This exact draft request uses actual original-control feedback solely for
    # tokenizer calibration. Runtime always recounts each fresh initial baseline.
    prior=Path(base['output_root'])
    candidates=sorted(prior.glob('*/baseline_results.json'))
    if candidates:
        results=json.loads(candidates[0].read_text())
        baseline={identifier:{'checked':{'S0':True,'S1':True,'S2':(result.get('physical_result') or {}).get('assessment',{}).get('S2',False),'failure_class':None},'result':result} for identifier,result in results.items()}
        if len(baseline)!=9:raise ValueError('A partial original baseline is not a nine-point context calibration')
        feedback_scope='actual existing collection baseline; new initial baselines remain required'
    else:
        q=json.loads((ROOT/'results/derived/C05_C08_domain_development_qualification.json').read_text())['circuits'][cid]
        if not q['all_points_ready']:raise ValueError('All nine development controls must be complete')
        by_sizing={json.dumps(json.loads((Path(row['raw_run'])/'sizing_input.json').read_text()),sort_keys=True):row for row in q['points']}
        baseline={}
        for point in domain:
            row=by_sizing[json.dumps(point['parameters']['sizing'],sort_keys=True)]
            baseline[point['configuration_id']]={'checked':{'S0':True,'S1':True,'S2':row['core_constraints_pass'],'failure_class':None},
                'result':{'status':'EVALUATED','physical_result':{'observation':{'corners':{corner:{'metrics':{'area':{'value':row['area_um2'],'unit':'um2'}}} for corner in row['corners']}}}}}
        feedback_scope='actual original development qualification controls only; no claim about new initial-program baselines'
    from transformers import AutoTokenizer
    cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text());tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
    sizes=[]
    for state in states:
        points=[point for point in registry['configurations'] if not state.get('task_id') or point['contract']['task_id']==state['task_id']]
        task,history=packet(draft,state,points,baseline)
        observation=history[0]['observation'];observation['actual_original_controls_for_context_calibration']=observation.pop('actual_new_baseline')
        observation.update(status='draft_context_size_calibration_only',new_initial_baseline_pending=True)
        request={'mode':'train_collection_source_gpt','trial_id':1,'request':{'task_packet':task,'visible_history':history}}
        file=out/(state['initial_state_id']+'_request.json');file.write_text(json.dumps(request,indent=2)+'\n')
        encoded=tokenizer.apply_chat_template([{'role':'user','content':source_proposal_prompt(request['request'])}],tokenize=True,add_generation_prompt=True,return_dict=True)
        count=len(encoded['input_ids']);sizes.append({'initial_state_id':state['initial_state_id'],'input_tokens':count,'source_output_reserve':3072,
            'total_reserved_tokens':count+3072,'fits':count+3072<=8192,'request_example':str(file),'feedback_scope':feedback_scope})
    report={'scope':'actual_pinned_tokenizer_DRAFT_request_calibration_zero_inference','teacher_instruction_version':'minimal_source_edit_v1',
        'tokenizer_revision':cache['revision'],'full_source_preserved':True,'all_requests_fit':all(row['fits'] for row in sizes),'requests':sizes,
        'runtime_requirement':'Recount each exact fresh-baseline request and reject overflow; no context/source truncation.', 'model_inferences':0,'physical_runs':0}
    (out/'teacher_context_preflight.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'preparation':str(out/'preparation.json'),'preflight':str(out/'teacher_context_preflight.json'),'initial_states':len(states),'requests':sizes},indent=2))
    if not report['all_requests_fit']:raise ValueError('Complete minimal-edit source teacher exceeds the frozen context')


if __name__=='__main__':main()
