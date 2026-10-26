"""Prepare, but never freeze or launch, the prospective full-source teacher."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.collect_training import packet

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--observed',type=Path,required=True);a=p.parse_args()
old=ROOT/'runtime/train_collections/c01_collection_v1/collection.json';v1=json.loads(old.read_text())
prep=json.loads(a.observed.read_text());observed=[json.loads(line) for line in Path(prep['initial_states_path']).read_text().splitlines()]
path='textbook_sharing/layout.py';source=Path(v1['source_pack'])
states=[{'initial_state_id':'c01_original_compiler_source_teacher_v2','parent_lineage':'textbook_universal_compiler_cropped',
    'origin':'natural','editable_paths':[path],'base_source':{path:(source/path).read_text()},
    'ancestry':{'kind':'unmodified_public_compiler','source_revision':'1f90e33913208e572744b7c5a144a7da8c073235','source_pack':str(source)}}]
for seed in [101,241]:
    row=next(row for row in observed if row['ancestry']['producer_seed']==seed)
    states.append({**row,'initial_state_id':'c01_observed_T0_seed_'+str(seed)+'_source_teacher_v2','editable_paths':[path],'base_source':{path:row['base_source'][path]}})
out=ROOT/'runtime/collection_preparation'/('c01_collection_v2_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
states_path=out/'initial_states.jsonl';states_path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in states))
gold_path=Path(v1['output_root'])/'gold_controls.json';controls=json.loads(gold_path.read_text())
if len(controls)!=9:raise ValueError('The v1 same-configuration complete original controls do not exist')
sampling={**v1['sampling'],'mode':'train_collection_source','proposal_format':'full_source_teacher','max_new_tokens':3072,'timeout_seconds':240}
draft={'status':'DRAFT_NOT_FROZEN','role':'train_collection','collection_id':'c01_collection_v2',
    'base_collection_manifest':str(old),'source_pack':str(source),'trusted_bundle':v1['trusted_bundle'],
    'registry_path':v1['registry_path'],'label_rule_path':v1['label_rule_path'],
    'initial_states_path':str(states_path),'initial_state_count':3,'editable_paths':[path],
    'frozen_additional_module':'glayout/sharing/enumeration.py','gold_controls':controls,'gold_control_origin':str(gold_path),
    'sampling':sampling,'physical':v1['physical'],
    'budget':{**v1['budget'],'initial_batch_initial_states':3},
    'deduplication':{'method':'exact_ast_dump','include_attributes':False,'numeric_normalization':False,
        'preserve_literals_identifiers_docstrings':True,'unparseable_source':'Exact text identity only; real executor and gold required for any negative',
        'duplicate_attempt_status':'semantic_duplicate_before_physics','all_generation_costs_retained':True},
    'prospective_change':'Separate full-source proposal generation, mechanical exact diff, complete layout-only scope; existing tested-policy ACTION_SCHEMA and v1 results/budgets unchanged.',
    'deadline_calibration':{'full_original_layout_JSON_output_tokens':1790,'observed_v1_output_tokens':[273,298,297,312,325,103,237,302],
        'observed_v1_generation_seconds':[27.1361,28.4949,28.4213,28.4450,28.8337,12.3011,23.1488,26.9524],
        'raw_evidence':str(Path(v1['output_root'])/'attempts.json'),'reason_for_240_seconds':'Actual approximately 10-11 tokens/s requires roughly 160-180 seconds for the complete module.'},
    'old_development_outcomes_admitted':False,'new_baseline9_per_state_and_new_teacher_proposals_required':True,
    'excluded_observed_state_379':'Custom-plan assignment is overwritten immediately; distinct text did not establish distinct behavior.',
    'formal_collection_launched':False}
(out/'preparation.json').write_text(json.dumps(draft,indent=2)+'\n')
registry=json.loads(Path(v1['registry_path']).read_text());prior=json.loads((Path(v1['output_root'])/'c01_original_compiler_collection_v1/baseline_results.json').read_text())
baseline={cid:{'checked':{'S0':True,'S1':True,'S2':True,'failure_class':None},'result':result} for cid,result in prior.items()}
task,history=packet(draft,states[0],registry['configurations'],baseline)
request={'variant':'T0','mode':'train_collection_source','sampling':{'temperature':.7,'top_p':.95,'seed':101},'request':{'task_packet':task,'visible_history':history}}
(out/'request_example.json').write_text(json.dumps(request,indent=2)+'\n')
print(json.dumps({'preparation':str(out/'preparation.json'),'request_example':str(out/'request_example.json'),'initial_states':len(states),'status':'DRAFT_NOT_LAUNCHED'}))
