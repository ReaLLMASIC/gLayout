"""Draft a separately labeled prospective deterministic-rule candidate pool."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import source_identity,source_patch
from scripts.corpus_rule_proposer import BORROWED_FROM,RULE_IDS,propose


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True);a=p.parse_args()
    prep=json.loads(a.preparation.read_text());source=Path(prep['source_pack']);path='textbook_sharing/layout.py'
    if prep.get('circuit_id') in ['C05','C08']:cid=prep['circuit_id']
    else:cid=prep['configurations'][0]['parameters']['circuit']['circuit_id']
    if cid not in ['C01','C05','C08']:raise ValueError('Rule pool needs an actually qualified train topology')
    out=ROOT/'runtime/collection_preparation'/(cid.lower()+'_rule_collection_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
    original=(source/path).read_text();initial={'initial_state_id':cid.lower()+'_original_compiler_rule_teacher',
        'task_id':'train_collection_'+cid.lower(),'parent_lineage':prep['parent_lineage'],'origin':'natural',
        'editable_paths':[path],'base_source':{path:original},'ancestry':{'kind':'unmodified_public_compiler',
        'source_revision':prep['source_revision'],'source_pack':str(source),'rule_generator_is_not_model':True}}
    states=out/'initial_states.jsonl';states.write_text(json.dumps(initial,ensure_ascii=False)+'\n')
    shutil.copyfile(ROOT/'scripts/corpus_rule_proposer.py',out/'rule_proposer.py')
    candidates=[];seen=[]
    for rule in RULE_IDS:
        wall=time.monotonic();cpu=time.process_time();text=propose(original,rule)
        identity=source_identity({path:text},True)
        if identity in seen or identity==source_identity({path:original},True):raise ValueError('The declared rules must produce eight distinct nonnoop programs')
        seen.append(identity);program=out/(rule+'.py');program.write_text(text)
        candidates.append({'rule_id':rule,'complete_source_file':str(program),'candidate_patch':source_patch(original,text,path),
            'draft_generation_wall_seconds':time.monotonic()-wall,'draft_generation_process_cpu_seconds':time.process_time()-cpu})
    metadata={'status':'DRAFT_PROSPECTIVE_RULE_COLLECTION_NOT_FROZEN','role':'train_collection','circuit_id':cid,
        'collection_id':cid.lower()+'_rules_v1','capsule_preparation':str(a.preparation.resolve()),'source_pack':str(source),
        'trusted_bundle':prep['trusted_bundle'],'initial_states_path':str(states),'initial_state_count':1,
        'editable_paths':[path],'parent_lineage':prep['parent_lineage'],'source_revision':prep['source_revision'],
        'rule_proposer_path':str(out/'rule_proposer.py'),'rule_ids':RULE_IDS,'borrowed_from':BORROWED_FROM,'candidates':candidates,
        'proposed_collection_mode':'train_collection_rules','sampling':{'backend':'frozen_rule_proposer','rule_ids':RULE_IDS,
            'model':None,'seed':None,'model_inferences':0,'generation_timeout_seconds':5},
        'physical':{'workers':2,'cpus_per_job':2,'generation_timeout_seconds':240,'evaluator_timeout_seconds':720},
        'new_physical_point_budget':81,'source_diversity':'Eight programs, one original initial AST and the same one public compiler lineage; no extra lineage from rule count.',
        'label_scope':'Use new frozen-contract physical runs only, with one fresh nine-point baseline and every candidate at all nine points. Old development outcomes stay excluded.',
        'student_context':'Teacher source/format is provenance. Student supervision must retain full source/contract/feedback while requesting the frozen unified-diff action format.',
        'counting':'Report unique useful initial states, unique terminal ASTs, per-method matched examples, anchor versus family winners, opposite non-tie pair preferences, and ties separately.',
        'no_inverse_fault_injection':True,'formal_collection_started':False,'old_outcomes_relabelled':False}
    (out/'preparation.json').write_text(json.dumps(metadata,indent=2)+'\n')
    for q in sorted(out.rglob('*'),reverse=True):q.chmod(0o555 if q.is_dir() else 0o444)
    out.chmod(0o555)
    print(json.dumps({'preparation':str(out/'preparation.json'),'rules':len(candidates),'initial_states':1,'state':'DRAFT_NOT_FROZEN_OR_LAUNCHED'}))


if __name__=='__main__':main()
