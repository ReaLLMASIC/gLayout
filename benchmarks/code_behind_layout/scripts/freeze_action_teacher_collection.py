"""Freeze the approved eight-proposal two-module ACTION teacher, before inference."""
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
    prep=json.loads(preparation.read_text());base_path=Path(prep['base_collection_manifest']);base,_,_,_=load(base_path)
    flight=json.loads(Path(prep['teacher_context_preflight']).read_text());sampling=prep['sampling']
    if (prep['collection_id']!='c01_planning_action_gpt_teacher_v1' or prep['teacher_interface_version']!='ordinary_action_teacher_v1' or
        sampling!={'backend':'isolated_gpt_cli','mode':'train_collection_action_gpt','model':'gpt-6.1-sol','reasoning_effort':'high',
            'trials':list(range(1,9)),'proposal_workers':2,'seed':None,'seed_control_available':False,'proposal_format':'ordinary_action_json',
            'max_new_tokens':1024,'max_context_tokens':8192,'timeout_seconds':240} or
        not flight['fits_with_full_output_reserve'] or flight['source_or_history_truncated'] or flight['model_inferences_issued']!=0 or
        flight['prompt_tokens']+flight['output_reserve']>8192 or len(prep['gold_controls'])!=9):
        raise ValueError('Only the approved exact complete-context zero-inference ACTION teacher can be frozen')
    for key in ['source_pack','trusted_bundle','registry_path','label_rule_path']:
        if prep[key]!=base[key]:raise ValueError('The new proposal interface cannot change the frozen source, physical contracts or labels')
    states=Path(prep['initial_states_path']).read_text();rows=[json.loads(line) for line in states.splitlines() if line.strip()]
    paths=['textbook_sharing/layout.py','glayout/sharing/enumeration.py']
    if len(rows)!=1 or list(rows[0]['base_source'])!=paths:raise ValueError('Exactly one original complete two-module state is approved')
    for name,text in rows[0]['base_source'].items():
        if (Path(prep['source_pack'])/name).read_text()!=text:raise ValueError('Initial program is not the actual original compiler')
    output=ROOT/'runtime/train_collections'/prep['collection_id'];output.mkdir()
    shutil.copyfile(base['registry_path'],output/'registry.json');shutil.copyfile(base['label_rule_path'],output/'label_rule.json')
    shutil.copyfile(preparation,output/'preparation.json');shutil.copyfile(Path(prep['teacher_context_preflight']),output/'teacher_context_preflight.json')
    shutil.copyfile(Path(prep['request_example']),output/'request_example.json');shutil.copyfile(preparation.parent/'exact_prompt.txt',output/'exact_prompt.txt')
    shutil.copytree(Path(prep['teacher_interface_path']),output/'interface');(output/'initial_states.jsonl').write_text(states)
    manifest={**base,**prep,'status':'frozen','frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'registry_path':str(output/'registry.json'),'label_rule_path':str(output/'label_rule.json'),'initial_states_path':str(output/'initial_states.jsonl'),
        'teacher_interface_path':str(output/'interface'),'teacher_context_preflight':str(output/'teacher_context_preflight.json'),'request_example':str(output/'request_example.json'),
        'output_root':str(ROOT/'runs/train_collection'/prep['collection_id']),'evidence_root':str(ROOT/'runs/train_collection'/prep['collection_id']),
        'main_benchmark_protocol_status':'draft','admission':'Fresh original-source nine-point baseline and eight new tool-disabled GPT ACTION proposals. Raw ACTION and canonical student budgets checked separately. Every legal distinct source receives all nine independent N(z)/device-graph evaluations. Invalid diffs are never repaired.'}
    save(output/'collection.json',manifest)
    names=sorted(str(path.relative_to(output)) for path in output.rglob('*') if path.is_file())
    save(output/'freeze_identity.json',{name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in names})
    load(output/'collection.json')
    for path in sorted(output.rglob('*'),reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
    output.chmod(0o555)
    return {'collection':str(output/'collection.json'),'status':'frozen','initial_states':1,'planned_proposals':8,
            'prompt_tokens':flight['prompt_tokens'],'output_reserve':1024,'GPT_requests_at_freeze':0,'interface_files_frozen':len(names),'main_benchmark_status':'draft'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preparation',type=Path,required=True)
    print(json.dumps(freeze(parser.parse_args().preparation)))
