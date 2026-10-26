"""Draft four genuine failed C01 teacher programs as new repair initial states."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_frozen_training_collection import frozen_module
from scripts.collect_training import load
from src.training import TrustedPhysicalStore
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget
from transformers import AutoTokenizer

parent=ROOT/'runtime/train_collections/c01_planning_action_gpt_teacher_v1/collection.json';base,registry,_,_=load(parent);raw=Path(base['output_root']);derived=Path(str(raw)+'_student_readmission_v1');admission=json.loads((derived/'physical_readmission.json').read_text())
if admission['status']!='RE_ADMITTED_FROM_RAW' or admission['admitted_candidates']!=6:raise ValueError('All six actual parent programs must pass the current trusted gate')
controls=json.loads((raw/'gold_controls.json').read_text());effective=json.loads((raw/'effective_registry.json').read_text());pointmap={p['configuration_id']:p for p in effective['configurations']};assignment=next(p for p in registry['lineages'] if p['lineage_id']=='textbook_universal_compiler_cropped')
module=frozen_module(ROOT/'runtime/train_collections/c05_natural_action_teacher_v1/collection.json')
manifest={**base,'collection_id':'c01_natural_action_repair_draft','teacher_packet_version':'ordinary_action_generation_feedback_v1','teacher_public_api_document':str(ROOT/'runtime/train_collections/c05_natural_action_teacher_v1/interface/public_assembly_api.json')}
cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text());tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
out=ROOT/'runtime/collection_preparation'/('c01_natural_action_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir();states=[];flights=[]
for row in map(json.loads,(raw/'candidates.jsonl').read_text().splitlines()):
    baseline={};edited={name:text for name,text in row['candidate_source'].items() if text!=(Path(base['source_pack'])/name).read_text()}
    if list(edited)!=['textbook_sharing/layout.py']:raise ValueError('Retain all changed program modules; this draft does not hide a second changed module')
    for outcome in row['outcomes']:
        point={**pointmap[outcome['configuration_id']],**{key:assignment[key] for key in ['editable_paths','frozen_source_pack','frozen_source_files']}}
        point.update(lineage_editable_paths=assignment['editable_paths'],editable_paths=list(edited))
        run=(raw/outcome['evidence_path']).parent;checked=TrustedPhysicalStore._inspect_execution_run(run,point,edited)
        baseline[outcome['configuration_id']]={'checked':checked,'result':{**json.loads((run/'manifest.json').read_text()),'run_directory':str(run)}}
    if all(b['checked']['S2'] for b in baseline.values()):continue
    if len(baseline)!=9 or any(b['checked']['S2'] for b in baseline.values()):raise ValueError('Only these actual whole-domain failed parent programs are currently declared')
    trial=row['candidate_id'].rsplit('_',1)[-1];state={'initial_state_id':'c01_natural_action_t'+trial+'_draft','task_id':registry['configurations'][0]['contract']['task_id'],'parent_lineage':row['parent_lineage'],'origin':'natural','editable_paths':list(edited),'base_source':edited,
        'ancestry':{'kind':'actual_isolated_GPT_ACTION_program','parent_collection_manifest':str(parent),'parent_initial_state_id':row['initial_state_id'],'parent_candidate_id':row['candidate_id'],'parent_raw_candidate_pool':str(raw/'candidates.jsonl'),'parent_proposal_generation':row['proposal_generation'],'parent_physical_outcomes':row['outcomes'],'not_manually_injected_or_reverse_patched':True,'source_revision':'1f90e33913208e572744b7c5a144a7da8c073235'}}
    task,history=module.packet(manifest,state,registry['configurations'],baseline);request={'mode':'train_collection_action_gpt','trial_id':1,'request':{'task_packet':task,'visible_history':history}}
    filename=out/(state['initial_state_id']+'_request.json');filename.write_text(json.dumps(request,indent=2)+'\n');flight=prompt_token_budget(tokenizer,decision_prompt(request['request']),{'max_new_tokens':1024,'max_context_tokens':8192});flight.update(initial_state_id=state['initial_state_id'],actual_generation_diagnostics_present=bool(history[0]['observation'].get('baseline_generation_diagnostics')),request_path=str(filename));states.append(state);flights.append(flight)
if len(states)!=4:raise ValueError('Preserve all four observed failed programs, not a selected repairable subset')
(out/'initial_states.jsonl').write_text(''.join(json.dumps(s,ensure_ascii=False)+'\n' for s in states))
record={'status':'DRAFT_NOT_FROZEN_NOT_LAUNCHED','collection_id':'c01_natural_action_repair_draft','base_collection_manifest':str(parent),'initial_states_path':str(out/'initial_states.jsonl'),'initial_state_count':4,'gold_controls':controls,'source_lineages':1,'source_scope':'Only the entire actually changed layout.py; enumeration is byte-identical to frozen original and remains frozen. Complete actual parent source and every failed point are retained in ancestry.','prospective_proposals':32,'model_inferences_issued':0,'new_physical_runs':0,'original_parent_plan_retained':{'planned':8,'returned':8,'remaining_not_run':0,'raw_status':'PAUSED_ADMISSION_UNCERTAINTY'},'teacher_context_preflight':flights,'all_contexts_fit':all(f['fits_with_full_output_reserve'] for f in flights),'no_training_labels_generated':True,'duplicate_repaired_terminal_ASTs_must_be_reported_separately':True}
(out/'preparation.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({'preparation':str(out/'preparation.json'),'initial_states':len(states),'preflight':flights,'new_model_or_physical_calls':0}))
