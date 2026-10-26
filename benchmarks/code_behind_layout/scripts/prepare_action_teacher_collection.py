"""Draft eight fresh GPT ACTION proposals over two complete train-only modules."""
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import packet
from src.local_model_adapter import decision_prompt
from src.model_adapter import ACTION_SCHEMA,prompt_token_budget

base_path=ROOT/'runtime/train_collections/c01_collection_v1/collection.json';base=json.loads(base_path.read_text())
source=Path(base['source_pack']);paths=['textbook_sharing/layout.py','glayout/sharing/enumeration.py']
states=[{'initial_state_id':'c01_original_compiler_planning_action_teacher_v1','parent_lineage':'textbook_universal_compiler_cropped',
    'origin':'natural','editable_paths':paths,'base_source':{path:(source/path).read_text() for path in paths},
    'ancestry':{'kind':'unmodified_public_compiler','source_revision':'1f90e33913208e572744b7c5a144a7da8c073235',
        'source_pack':str(source),'complete_source_scope':paths,'same_original_program_as_other_C01_collections':True}}]
out=ROOT/'runtime/collection_preparation'/('c01_action_teacher_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
interface=out/'interface';(interface/'src').mkdir(parents=True)
for name in ['model_adapter.py','local_model_adapter.py','policy_state.py']:shutil.copyfile(ROOT/'src'/name,interface/'src'/name)
(interface/'src/__init__.py').write_text('')
shutil.copyfile(ROOT/'scripts/corpus_gpt_action_teacher_service.py',interface/'broker.py')
shutil.copyfile(ROOT/'scripts/collect_training.py',interface/'collector.py')
(interface/'action_schema.json').write_text(json.dumps(ACTION_SCHEMA,indent=2)+'\n')
(out/'initial_states.jsonl').write_text(''.join(json.dumps(state,ensure_ascii=False)+'\n' for state in states))
draft={'status':'DRAFT_NOT_FROZEN','role':'train_collection','collection_id':'c01_planning_action_gpt_teacher_v1',
    'base_collection_manifest':str(base_path),'source_pack':str(source),'trusted_bundle':base['trusted_bundle'],
    'registry_path':base['registry_path'],'label_rule_path':base['label_rule_path'],'initial_states_path':str(out/'initial_states.jsonl'),
    'initial_state_count':1,'editable_paths':paths,'gold_controls':json.loads((Path(base['output_root'])/'gold_controls.json').read_text()),
    'teacher_interface_version':'ordinary_action_teacher_v1','teacher_interface_path':str(interface),
    'budget_tokenizer_revision':'381fc969f78efac66bc87ff7ddeadb7e73c218a7',
    'sampling':{'backend':'isolated_gpt_cli','mode':'train_collection_action_gpt','model':'gpt-6.1-sol','reasoning_effort':'high',
        'trials':list(range(1,9)),'proposal_workers':2,'seed':None,'seed_control_available':False,'proposal_format':'ordinary_action_json',
        'max_new_tokens':1024,'max_context_tokens':8192,'timeout_seconds':240},
    'student_preselection':{'student_interface_version':'ordinary_policy_action_v1','max_new_tokens':1024,'max_context_tokens':8192,'stage':'before_physics'},
    'physical':{**base['physical'],'workers':2},'budget':{**base['budget'],'initial_batch_initial_states':1},
    'deduplication':{'method':'exact_ast_dump','include_attributes':False,'numeric_normalization':False,
        'preserve_literals_identifiers_docstrings':True,'all_generation_costs_retained':True},
    'transport':{'remote_endpoint':'http://127.0.0.1:8116','local_listen':'127.0.0.1:8116','mechanism':'private SSH reverse loopback; credentials remain on local host'},
    'isolation':{'fresh_ephemeral_session_per_trial':True,'native_tools':False,'source_and_ACTION_teachers_global_slots':2,
        'queue_rule':'Serialize against the currently active source-teacher collections; no extra GPT slots',
        'shared_prompt_within_state':'Byte-identical ordinary decision_prompt(request); trial index stays outside the model prompt'},
    'output_budget_scope':'Exact raw returned ACTION text plus EOS <=1024; canonical student ACTION is independently checked before physics. No diff correction, truncation or header repair.',
    'source_program_counting':'The original compiler is the same initial program as prior C01 collections; the second editable module expands the action space, not the count of independent source lineages.',
    'sizing_semantics':'w is total device width in microns, nf is finger count, independent gold uses per-finger width w/nf. Existing nf1..8 is retained; no claim that nf was constant.',
    'new_baseline9_per_state_and_new_teacher_proposals_required':True,'old_development_outcomes_admitted':False,'formal_collection_launched':False}
prior=json.loads((Path(base['output_root'])/'c01_original_compiler_collection_v1/baseline_results.json').read_text())
registry=json.loads(Path(base['registry_path']).read_text());baseline={identifier:{'checked':{'S0':True,'S1':True,'S2':True,'failure_class':None},'result':result} for identifier,result in prior.items()}
task,history=packet(draft,states[0],registry['configurations'],baseline)
request={'mode':'train_collection_action_gpt','trial_id':1,'request':{'task_packet':task,'visible_history':history}}
(out/'request_example.json').write_text(json.dumps(request,indent=2)+'\n');prompt=decision_prompt(request['request']);(out/'exact_prompt.txt').write_text(prompt)
from transformers import AutoTokenizer
cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text());tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
preflight=prompt_token_budget(tokenizer,prompt,{'max_new_tokens':1024,'max_context_tokens':8192})
preflight.update(role='exact_complete_packet_calibration_no_new_model_inference_or_labels',
    source_files={path:{'bytes':len(text.encode()),'whole_module':True} for path,text in states[0]['base_source'].items()},
    tokenizer_revision=cache['revision'],observed_context_baseline_source=str(Path(base['output_root'])/'c01_original_compiler_collection_v1/baseline_results.json'),
    actual_collection_requires_new_baseline9_and_recount=True,model_inferences_issued=0)
if not preflight['fits_with_full_output_reserve']:raise ValueError('Complete two-module packet does not fit; do not truncate or issue proposals')
(out/'teacher_context_preflight.json').write_text(json.dumps(preflight,indent=2)+'\n')
draft['teacher_context_preflight']=str(out/'teacher_context_preflight.json');draft['request_example']=str(out/'request_example.json')
(out/'preparation.json').write_text(json.dumps(draft,indent=2)+'\n')
print(json.dumps({'preparation':str(out/'preparation.json'),'request_example':str(out/'request_example.json'),'interface':str(interface),'preflight':preflight,'status':'DRAFT_NO_NEW_INFERENCE'}))
