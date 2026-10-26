"""Freeze only the approved prospective minimal-source teacher branch."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import load


def save(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def freeze(preparation):
    prep=json.loads(preparation.read_text());base_path=Path(prep['base_collection_manifest'])
    base,registry,_,_=load(base_path);flight_path=preparation.parent/'teacher_context_preflight.json';flight=json.loads(flight_path.read_text())
    allowed={'c01_failure_minimal_gpt_teacher_v1':1,'c05_minimal_gpt_teacher_v1':3,'c08_minimal_gpt_teacher_v1':3}
    identifier=prep['collection_id'];sampling=prep['sampling']
    if (identifier not in allowed or prep['teacher_instruction_version']!='minimal_source_edit_v1' or
        prep['student_preselection']!={'student_interface_version':'ordinary_policy_action_v1','max_new_tokens':1024,'max_context_tokens':8192,'stage':'before_physics'} or
        sampling!={'mode':'train_collection_source_gpt','backend':'isolated_gpt_cli','model':'gpt-6.1-sol','reasoning_effort':'high','trials':list(range(1,9)),
            'proposal_workers':2,'seed':None,'seed_control_available':False,'proposal_format':'full_source_teacher','max_new_tokens':3072,'max_context_tokens':8192,'timeout_seconds':240} or
        not flight['all_requests_fit'] or flight['model_inferences']!=0 or flight['physical_runs']!=0):
        raise ValueError('Only the explicitly approved, zero-inference minimal-source teacher contract can be frozen')
    for key in ['source_pack','trusted_bundle','registry_path','label_rule_path']:
        if prep[key]!=base[key]:raise ValueError('A minimal teacher cannot alter its existing source, trusted evaluator or physical labels')
    states=Path(prep['initial_states_path']).read_text();rows=[json.loads(line) for line in states.splitlines() if line.strip()]
    if len(rows)!=allowed[identifier]:raise ValueError('Unexpected initial-state inventory')
    if identifier.startswith('c01_') and (rows[0]['ancestry'].get('producer_seed')!=241 or len(prep.get('gold_controls',{}))!=9):raise ValueError('The C01 repair branch needs its genuine observed failure and complete original controls')
    output=ROOT/'runtime/train_collections'/identifier;output.mkdir()
    shutil.copyfile(base['registry_path'],output/'registry.json');shutil.copyfile(base['label_rule_path'],output/'label_rule.json')
    shutil.copyfile(preparation,output/'preparation.json');shutil.copyfile(flight_path,output/'teacher_context_preflight.json')
    (output/'initial_states.jsonl').write_text(states)
    manifest={**base,**prep,'status':'frozen','frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'registry_path':str(output/'registry.json'),'label_rule_path':str(output/'label_rule.json'),'initial_states_path':str(output/'initial_states.jsonl'),
        'output_root':str(ROOT/'runs/train_collection'/identifier),'evidence_root':str(ROOT/'runs/train_collection'/identifier),
        'main_benchmark_protocol_status':'draft','admission':'Fresh initial baselines and new minimally edited teacher programs only. Full-source output and generation costs preserved; ordinary-action budget rejected before physics; no teacher repair or truncation.'}
    save(output/'collection.json',manifest)
    names=['collection.json','registry.json','label_rule.json','initial_states.jsonl','preparation.json','teacher_context_preflight.json']
    save(output/'freeze_identity.json',{name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in names})
    load(output/'collection.json')
    for path in output.iterdir():path.chmod(0o444)
    output.chmod(0o555)
    return {'collection':str(output/'collection.json'),'status':'frozen','initial_states':len(rows),'GPT_requests':0,'main_benchmark_status':'draft'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True)
    print(json.dumps(freeze(p.parse_args().preparation)))
