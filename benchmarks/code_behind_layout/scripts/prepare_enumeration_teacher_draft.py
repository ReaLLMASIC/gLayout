"""Preflight a whole-enumeration ordinary ACTION teacher; never dispatch or freeze."""
import ast
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget
from transformers import AutoTokenizer

parent=ROOT/'runtime/train_collections/c01_planning_action_gpt_teacher_v1/collection.json';manifest=json.loads(parent.read_text());pack=Path(manifest['source_pack'])
raw=Path(manifest['output_root'])/'c01_original_compiler_planning_action_teacher_v1';task=json.loads((raw/'task_packet.json').read_text());history=json.loads((raw/'visible_history.json').read_text())
path='glayout/sharing/enumeration.py';source=(pack/path).read_text();task['allowed_paths']=[path];task['visible_sources']={path:source}
api=[]
for filename,names in [('glayout/sharing/spec.py',['DeviceSpec','FingerRef','GateGroup','SharingPlan']),('glayout/sharing/group.py',['independent_plan'])]:
    text=(pack/filename).read_text();lines=text.splitlines(True);tree=ast.parse(text)
    for name in names:
        node=next(n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==name);first=min([node.lineno]+[d.lineno for d in getattr(node,'decorator_list',[])])
        api.append({'module':filename,'symbol':name,'start_line':first,'end_line':node.end_lineno,'visibility':'complete_declaration','source':''.join(lines[first-1:node.end_lineno])})
text=(pack/'glayout/sharing/group.py').read_text();node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='validate_plan')
api.append({'module':'glayout/sharing/group.py','symbol':'validate_plan','visibility':'exact_signature_and_original_docstring_frozen_implementation','signature':text.splitlines()[node.lineno-1],'docstring':ast.get_docstring(node,clean=False)})
task['documents']['frozen_api']='All other compiler bytes, including the layout consumer, are frozen. This is one complete enumeration module edit window. Public type declarations below are complete; validate_plan is exposed by its actual signature/docstring as an immutable public API. This is the same compiler lineage and original source program as earlier C01 collections.'
task['documents']['enumeration_api']=api
task['documents']['frozen_layout_consumer']='The immutable layout.build invokes named_plans(pdk,devs) and selects nm.get(mode) or nm["independent"]. The backend mode is independent. Return types and physical intent must remain unchanged.'
task['goal']='Return one ordinary propose_patch ACTION_JSON improving feasible physical area across the declared domain by changing the complete enumeration algorithm. Preserve public APIs and unaffected lines. Only glayout/sharing/enumeration.py is editable; the layout consumer and physical definitions are frozen. Every proposed source is physically evaluated on all nine points; no patch repair or truncation occurs.'
request={'mode':'train_collection_action_gpt','trial_id':1,'request':{'task_packet':task,'visible_history':history}}
cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text());tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
flight=prompt_token_budget(tokenizer,decision_prompt(request['request']),{'max_new_tokens':1024,'max_context_tokens':8192})
out=ROOT/'runtime/collection_preparation'/('c01_enumeration_action_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
def save(name,value):(out/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
save('request_example.json',request);save('teacher_context_preflight.json',flight)
state={'initial_state_id':'c01_original_enumeration_scope_draft','task_id':'train_collection_c01','parent_lineage':'textbook_universal_compiler_cropped','origin':'natural','editable_paths':[path],'base_source':{path:source},'ancestry':{'kind':'same_original_public_compiler_program_expanded_proposal_scope','parent_collection_manifest':str(parent),'not_a_new_independent_initial_program':True,'not_a_new_lineage':True}}
(out/'initial_states.jsonl').write_text(json.dumps(state,ensure_ascii=False)+'\n')
save('preparation.json',{'status':'DRAFT_NOT_FROZEN_NOT_DISPATCHABLE','collection_id':'c01_enumeration_action_teacher_draft','parent_collection_manifest':str(parent),'complete_editable_module':path,'initial_states_path':str(out/'initial_states.jsonl'),'request_example':str(out/'request_example.json'),'public_API_visibility':api,'token_preflight':flight,'proposals_planned':8,'model_inferences_issued':0,'new_physical_runs':0,'source_lineages':1,'new_independent_initial_programs':0,'student_action_1024_context8192_unchanged':True,'requires_own_prospective_collector_packet_snapshot_and_freeze':True})
print(json.dumps({'preparation':str(out/'preparation.json'),'preflight':flight,'model_inferences':0}))
