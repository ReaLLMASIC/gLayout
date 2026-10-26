"""Freeze the two approved C01 trajectory/scope teacher drafts prospectively."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import load
from scripts.run_frozen_training_collection import load_definition
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget
from src.training import TrustedPhysicalStore
from transformers import AutoTokenizer

parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preparation',type=Path,required=True);args=parser.parse_args();prep=json.loads(args.preparation.read_text())
enum=prep['collection_id']=='c01_enumeration_action_teacher_draft';natural=prep['collection_id']=='c01_natural_action_repair_draft'
if not(enum or natural) or prep.get('status')!='DRAFT_NOT_FROZEN_NOT_DISPATCHABLE' and prep.get('status')!='DRAFT_NOT_FROZEN_NOT_LAUNCHED':raise ValueError('Only the two approved concrete C01 drafts are in scope')
parent=Path(prep['parent_collection_manifest'] if enum else prep['base_collection_manifest']);base,registry,_,_=load(parent);raw=Path(base['output_root']);assignment=next(p for p in registry['lineages'] if p['lineage_id']=='textbook_universal_compiler_cropped')
states=[json.loads(v) for v in Path(prep['initial_states_path']).read_text().splitlines() if v.strip()]
if len(states)!=(1 if enum else 4):raise ValueError('Preserve the entire approved state inventory')
identifier='c01_enumeration_action_v1' if enum else 'c01_natural_action_repair_v1';out=ROOT/'runtime/train_collections'/identifier;out.mkdir()
def save(name,value):(out/name).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
interface=ROOT/'runtime/train_collections'/('c01_planning_action_gpt_teacher_v1' if enum else 'c05_natural_action_teacher_v1')/'interface';shutil.copytree(interface,out/'interface')
for p in (out/'interface').rglob('*'):p.chmod(0o755 if p.is_dir() else 0o644)
(out/'interface').chmod(0o755)
code=(out/'interface/collector.py').read_text()
if enum:
    marker="    observation={'status':'begin','actual_new_baseline':"
    insertion="    if manifest.get('teacher_packet_version')=='ordinary_action_enumeration_v1':\n        template=json.loads(Path(manifest['teacher_packet_template']).read_text())\n        visible['goal']=template['goal']\n        visible['documents']=template['documents']\n"
    if code.count(marker)!=1:raise ValueError('Expected one exact packet insertion point')
    code=code.replace(marker,insertion+marker);task=json.loads(Path(prep['request_example']).read_text())['request']['task_packet'];save('interface/teacher_packet_template.json',{'goal':task['goal'],'documents':task['documents']})
(out/'interface/collector.py').write_text(code)
for state in states:
    state['ancestry']['draft_initial_state_id']=state['initial_state_id'];state['initial_state_id']=state['initial_state_id'].removesuffix('_draft')+'_v1'
(out/'initial_states.jsonl').write_text(''.join(json.dumps(s,ensure_ascii=False)+'\n' for s in states))
shutil.copyfile(base['registry_path'],out/'registry.json');shutil.copyfile(base['label_rule_path'],out/'label_rule.json');shutil.copyfile(args.preparation,out/'preparation.json')
manifest={**base,'collection_id':identifier,'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'registry_path':str(out/'registry.json'),'label_rule_path':str(out/'label_rule.json'),'initial_states_path':str(out/'initial_states.jsonl'),
    'teacher_interface_path':str(out/'interface'),'frozen_collector_entrypoint':'interface/collector.py','physical':{**base['physical'],'workers':1},'budget':{**base['budget'],'initial_batch_initial_states':len(states)},
    'output_root':str(ROOT/'runs/train_collection'/identifier),'evidence_root':str(ROOT/'runs/train_collection'/identifier),'gold_controls':json.loads((raw/'gold_controls.json').read_text()),'editable_paths':list(states[0]['base_source']),
    'teacher_packet_version':'ordinary_action_enumeration_v1' if enum else 'ordinary_action_generation_feedback_v1','source_scope':prep.get('source_scope','One complete11,106B enumeration module; exact public API declarations and frozen layout consumer contract. Same original compiler program and circuit context, no new independent initial program.'),
    'original_parent_plan_retained':prep.get('original_parent_plan_retained',{'planned':8,'returned':8,'remaining_not_run':0,'raw_status':'PAUSED_ADMISSION_UNCERTAINTY'}),'source_program_counting':'Different module scopes do not create new independent programs or lineages. Actual failed parent programs retain full ancestry. Repeated repaired terminal ASTs and circuit-task contexts are reported separately.',
    'prospective_scope':'New frozen ordinary ACTION teacher collection only; old raw evidence and contracts unchanged','formal_model_training_runs':0}
if enum:manifest['teacher_packet_template']=str(out/'interface/teacher_packet_template.json')
else:manifest['teacher_public_api_document']=str(out/'interface/public_assembly_api.json')
spec=importlib.util.spec_from_file_location('_prospective_c01_packet',out/'interface/collector.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.ROOT=ROOT
cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text());tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False);points=registry['configurations'];pointmap={p['configuration_id']:p for p in json.loads((raw/'effective_registry.json').read_text())['configurations']};rows=[json.loads(v) for v in (raw/'candidates.jsonl').read_text().splitlines() if v.strip()];flights=[]
for state in states:
    baseline={}
    if enum:
        prior=json.loads((raw/'c01_original_compiler_planning_action_teacher_v1/baseline_results.json').read_text());pairs=[(p['configuration_id'],Path(prior[p['configuration_id']]['run_directory']),prior[p['configuration_id']]) for p in points]
    else:
        row=next(v for v in rows if v['candidate_id']==state['ancestry']['parent_candidate_id']);pairs=[]
        for outcome in row['outcomes']:
            run=(raw/outcome['evidence_path']).parent;pairs.append((outcome['configuration_id'],run,{**json.loads((run/'manifest.json').read_text()),'run_directory':str(run)}))
    for cid,run,result in pairs:
        point={**pointmap[cid],**{k:assignment[k] for k in ['editable_paths','frozen_source_pack','frozen_source_files']}};point.update(lineage_editable_paths=assignment['editable_paths'],editable_paths=list(state['base_source']))
        checked=TrustedPhysicalStore._inspect_execution_run(run,point,state['base_source']);baseline[cid]={'checked':checked,'result':result}
    if len(baseline)!=9:raise ValueError('A complete actual baseline is required for preflight')
    task,history=module.packet(manifest,state,points,baseline);request={'mode':'train_collection_action_gpt','trial_id':1,'request':{'task_packet':task,'visible_history':history}};save(state['initial_state_id']+'_request.json',request)
    flight=prompt_token_budget(tokenizer,decision_prompt(request['request']),{'max_new_tokens':1024,'max_context_tokens':8192});flight.update(initial_state_id=state['initial_state_id'],new_model_or_physical_calls=0);flights.append(flight)
flight={'requests':flights,'all_contexts_fit':all(f['fits_with_full_output_reserve'] and not f['source_or_history_truncated'] for f in flights),'model_inferences_at_freeze':0,'physical_calls_at_freeze':0};save('teacher_context_preflight.json',flight)
if not flight['all_contexts_fit']:raise ValueError('Complete source/API/feedback does not fit; no model call permitted')
manifest['teacher_context_preflight']=str(out/'teacher_context_preflight.json');save('collection.json',manifest)
names=sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file());save('freeze_identity.json',{n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in names});load_definition(out/'collection.json')
for p in sorted(out.rglob('*'),reverse=True):p.chmod(0o555 if p.is_dir() else 0o444)
out.chmod(0o555);print(json.dumps({'collection':str(out/'collection.json'),'status':'frozen','initial_states':len(states),'planned_requests':len(states)*8,'preflight':flight,'formal_training_runs':0}))
