"""Draft new teacher states from three actual model-produced API failures."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import load,packet
from src.training import TrustedPhysicalStore
from src.local_model_adapter import source_proposal_prompt

base_path=ROOT/'runtime/train_collections/c05_minimal_gpt_teacher_v1/collection.json'
base,registry,_,_=load(base_path);prior=Path(base['output_root'])
readmission=json.loads((ROOT/'runs/train_collection/c05_minimal_gpt_teacher_v1_student_readmission_v1/physical_readmission.json').read_text())
if readmission['status']!='RE_ADMITTED_FROM_RAW' or readmission['admitted_candidates']!=7:
    raise ValueError('Wait for the full actual seven-program pool to pass current strict admission')
rows=[json.loads(line) for line in (prior/'candidates.jsonl').read_text().splitlines() if line.strip()]
selected=[next(row for row in rows if row['candidate_id'].endswith('__trial_'+str(number))) for number in [4,5,6]]
identifier='c05_natural_api_repair_teacher_v1'
out=ROOT/'runtime/collection_preparation'/(identifier+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
assignment=next(row for row in registry['lineages'] if row['lineage_id']==selected[0]['parent_lineage'])
points=registry['configurations'];effective=json.loads((prior/'effective_registry.json').read_text());effective_points={point['configuration_id']:point for point in effective['configurations']}
states=[];baselines={}
for number,row in zip([4,5,6],selected):
    state={'initial_state_id':'c05_natural_t'+str(number)+'_v1','task_id':points[0]['contract']['task_id'],
        'parent_lineage':row['parent_lineage'],'origin':'natural','editable_paths':['textbook_sharing/layout.py'],
        'base_source':row['candidate_source'],
        'ancestry':{'kind':'actual_isolated_GPT_model_candidate','parent_collection':base['collection_id'],
            'parent_initial_state_id':row['initial_state_id'],'parent_candidate_id':row['candidate_id'],
            'parent_raw_candidate_pool':str(prior/'candidates.jsonl'),'source_revision':'1f90e33913208e572744b7c5a144a7da8c073235',
            'parent_proposal_generation':row['proposal_generation'],'parent_physical_outcomes':row['outcomes'],
            'observed_failure':'qualified textbook_sharing.assembly.engine.AssemblyError when source calls assemble repeatedly with identical cell name',
            'not_manually_injected_or_reverse_patched':True,'new_baseline9_and_new_teacher_proposals_required':True}}
    if list(state['base_source'])!=['textbook_sharing/layout.py']:raise ValueError('Retain the entire actual source module unchanged')
    baseline={}
    for outcome in row['outcomes']:
        point={**effective_points[outcome['configuration_id']],**{key:assignment[key] for key in ['editable_paths','frozen_source_pack','frozen_source_files']}}
        point.update(lineage_editable_paths=assignment['editable_paths'],editable_paths=list(state['base_source']))
        run=(prior/outcome['evidence_path']).parent;result={**json.loads((run/'manifest.json').read_text()),'run_directory':str(run)}
        checked=TrustedPhysicalStore._inspect_execution_run(run,point,state['base_source'])
        if checked['S0'] or checked['generation_failure_exception']!='textbook_sharing.assembly.engine.AssemblyError':
            raise ValueError('This next-wave inventory is only the three actually observed and verified API failures')
        baseline[outcome['configuration_id']]={'checked':checked,'result':result}
    if len(baseline)!=9:raise ValueError('A complete actual failure domain is required for this draft context preflight')
    states.append(state);baselines[state['initial_state_id']]=baseline
(out/'initial_states.jsonl').write_text(''.join(json.dumps(state,ensure_ascii=False)+'\n' for state in states))
draft={**base,'status':'DRAFT_NOT_FROZEN','collection_id':identifier,'base_collection_manifest':str(base_path),
    'registry_path':base['registry_path'],'label_rule_path':base['label_rule_path'],
    'initial_states_path':str(out/'initial_states.jsonl'),'initial_state_count':3,
    'gold_controls':json.loads((prior/'gold_controls.json').read_text()),'physical':{**base['physical'],'workers':1},
    'budget':{**base['budget'],'initial_batch_initial_states':3},'formal_collection_launched':False,
    'new_initial_sources_from_actual_model_programs_not_engineering_patches':True,
    'original_parent_collection_plan_retained':{'planned_proposals':24,'returned_proposals':8,'remaining_not_run':16},
    'prospective_change':'Three distinct actual failed planning algorithms become natural initial programs. All original source text and ancestry retained; new proposals and physical evidence will be required. No parent failure becomes a new collection label.'}
for key in ['frozen_at_utc','output_root','evidence_root','teacher_context_preflight','request_example']:
    draft.pop(key,None)
from transformers import AutoTokenizer
cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text());tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
flights=[]
for state in states:
    task,history=packet(draft,state,points,baselines[state['initial_state_id']])
    request={'mode':'train_collection_source_gpt','trial_id':1,'request':{'task_packet':task,'visible_history':history}}
    file=out/(state['initial_state_id']+'_request.json');file.write_text(json.dumps(request,indent=2)+'\n')
    count=len(tokenizer.apply_chat_template([{'role':'user','content':source_proposal_prompt(request['request'])}],tokenize=True,add_generation_prompt=True,return_dict=True)['input_ids'])
    flights.append({'initial_state_id':state['initial_state_id'],'input_tokens':count,'source_output_reserve':3072,
        'total_reserved_tokens':count+3072,'fits':count+3072<=8192,'request_example':str(file),
        'feedback_scope':'Actual parent model-program failures, current strict gate inspected; new collection obtains its own fresh failed-source baseline9 and recounts exact context.'})
flight={'scope':'exact_pinned_tokenizer_DRAFT_preflight_only','teacher_instruction_version':'minimal_source_edit_v1',
    'tokenizer_revision':cache['revision'],'full_source_preserved':True,'all_requests_fit':all(row['fits'] for row in flights),
    'requests':flights,'model_inferences':0,'new_physical_runs':0,'physical_runs':0,'no_training_labels_generated':True}
(out/'teacher_context_preflight.json').write_text(json.dumps(flight,indent=2)+'\n')
(out/'preparation.json').write_text(json.dumps(draft,indent=2)+'\n')
print(json.dumps({'preparation':str(out/'preparation.json'),'initial_states':3,'preflight':flight},indent=2))
if not flight['all_requests_fit']:raise ValueError('Full source plus actual failure feedback exceeds source teacher budget; do not launch or truncate')
