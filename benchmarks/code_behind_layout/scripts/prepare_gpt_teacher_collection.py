"""Draft the explicitly separate isolated-GPT full-source collection."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import packet
v2_path=ROOT/'runtime/train_collections/c01_collection_v2/collection.json';v2=json.loads(v2_path.read_text())
states=[json.loads(line) for line in Path(v2['initial_states_path']).read_text().splitlines() if line.strip()]
for state in states:
    old=state['initial_state_id'];state['initial_state_id']=old+'__GPT_source_teacher_v1'
    state['ancestry']={**state['ancestry'],'prospective_teacher_context_copy_of':old,'old_outcomes_relabeled':False}
out=ROOT/'runtime/collection_preparation'/('gpt_teacher_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
(out/'initial_states.jsonl').write_text(''.join(json.dumps(state,ensure_ascii=False)+'\n' for state in states))
draft={'status':'DRAFT_NOT_FROZEN','role':'train_collection','collection_id':'c01_gpt_teacher_v1',
    'base_collection_manifest':str(v2_path),'source_pack':v2['source_pack'],'trusted_bundle':v2['trusted_bundle'],
    'registry_path':v2['registry_path'],'label_rule_path':v2['label_rule_path'],'initial_states_path':str(out/'initial_states.jsonl'),
    'initial_state_count':3,'editable_paths':['textbook_sharing/layout.py'],'gold_controls':v2['gold_controls'],
    'sampling':{'backend':'isolated_gpt_cli','mode':'train_collection_source_gpt','model':'gpt-6.1-sol','reasoning_effort':'high',
        'trials':list(range(1,9)),'proposal_workers':2,'seed':None,'seed_control_available':False,
        'proposal_format':'full_source_teacher','max_new_tokens':3072,'max_context_tokens':8192,'timeout_seconds':240},
    'physical':{**v2['physical'],'workers':2},'budget':{**v2['budget'],'initial_batch_initial_states':3},
    'deduplication':v2.get('deduplication',{'method':'exact_ast_dump','include_attributes':False,'numeric_normalization':False}),
    'transport':{'remote_endpoint':'http://127.0.0.1:8115','local_listen':'127.0.0.1:8115',
        'mechanism':'SSH reverse forwarding to local authenticated GPT CLI broker; credentials remain on original host',
        'service_script':'scripts/corpus_gpt_teacher_service.py','command_source':'command() uses the same native-capability disable flags as the existing isolated policy adapter'},
    'isolation':{'fresh_ephemeral_session_per_trial':True,'sandbox':'read-only','native_tools':False,'web_search':False,'apps_plugins_mcp_memory':False,
        'project_instructions':False,'working_directory':'opaque random UUID, never trial-index text','shared_prompt_within_state':'byte-identical source_proposal_prompt(request)'},
    'costs':'Keep every exact CLI argv/request/events/stderr/proposal/exit/wall and available public usage; no provider checkpoint, seed, hidden reasoning or billable price is inferred',
    'output_budget_scope':'Pinned Qwen tokenizer counts complete returned JSON + EOS; excess outputs are retained but not applied, with no truncation',
    'source_program_counting':'Same three initial AST programs as Qwen v2, not three new lineages or independent source programs; report unique terminal ASTs and useful initial states separately from DPO pairs',
    'old_development_outcomes_admitted':False,'new_baseline9_per_state_and_new_teacher_proposals_required':True,'formal_collection_launched':False}
(out/'preparation.json').write_text(json.dumps(draft,indent=2)+'\n')
registry=json.loads(Path(v2['registry_path']).read_text());first=Path(v2['output_root'])/'c01_original_compiler_source_teacher_v2/baseline_results.json'
prior=json.loads(first.read_text())
if len(prior)!=9:raise ValueError('Wait for the actual first v2 nine-point baseline before context calibration')
baseline={cid:{'checked':{'S0':True,'S1':True,'S2':True,'failure_class':None},'result':result} for cid,result in prior.items()}
task,history=packet(draft,states[0],registry['configurations'],baseline)
body={'mode':'train_collection_source_gpt','trial_id':1,'request':{'task_packet':task,'visible_history':history}}
(out/'request_example.json').write_text(json.dumps(body,indent=2)+'\n')
print(json.dumps({'preparation':str(out/'preparation.json'),'request_example':str(out/'request_example.json'),'status':'DRAFT_NOT_LAUNCHED'}))
