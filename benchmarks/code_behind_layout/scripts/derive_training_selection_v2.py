"""Freeze the one-change SFT v2 rule, then readmit and compare v1/v2 train yield."""
import argparse
import ast
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.prepare_student_data import bound_registry,completed_state_scope,interrupted_context_overflow
from scripts.run_frozen_training_collection import load_definition
from src.student_interface import CONTEXT_VERSION,derive_matched_samples,interface_definition
from src.training import TrustedPhysicalStore,admit_candidates,sample_identity
from src.training_selection_v2 import VERSION,make_rule

BASE_FUNCTIONS=('state_label_rule','build_matched_samples','patch_context','compare_outcomes')


def read(path):return json.loads(Path(path).read_text())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_base_selection(source):
    tree=ast.parse(source);functions={node.name:ast.get_source_segment(source,node) for node in tree.body
        if isinstance(node,ast.FunctionDef) and node.name in BASE_FUNCTIONS}
    if set(functions)!=set(BASE_FUNCTIONS):raise ValueError('The real legacy selection API changed; do not infer a replacement')
    return '"""Exact complete legacy selection functions; no physical gate snapshot is executed here."""\nimport json\nimport math\n\n'+'\n\n'.join(functions[name] for name in BASE_FUNCTIONS)+'\n'


def freeze_rule(collection,output):
    manifest,_,_,_=load_definition(collection);parent_path=Path(manifest['label_rule_path']);parent=read(parent_path)
    rule=make_rule(parent,manifest['sampling']);output.mkdir(parents=True,exist_ok=False)
    save(output/'rule.json',rule);shutil.copyfile(parent_path,output/'parent_rule.json')
    shutil.copyfile(ROOT/'src/training_selection_v2.py',output/'selection_v2.py')
    (output/'base_selection.py').write_text(frozen_base_selection((ROOT/'src/training.py').read_text()))
    definition=interface_definition(CONTEXT_VERSION,16384)
    save(output/'selection.json',{'status':'FROZEN_TRAIN_SELECTION_V2','version':VERSION,
        'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'parent_collection':str(collection.resolve()),
        'parent_collection_sha256':digest(collection),'parent_label_rule_path':str(parent_path),
        'parent_label_rule_sha256':digest(parent_path),'sampling':manifest['sampling'],'student_interface':definition,
        'base_selection_functions':list(BASE_FUNCTIONS),
        'change':'Only unique-best SFT becomes equivalent-best earliest actual declared trial. Method scopes, numerical/effect tolerances, baseline improvement and DPO ties/preferences unchanged.',
        'old_collection_or_raw_changed':False,'new_model_calls':0,'new_physical_calls':0,'formal_training_runs':0})
    names=[p.name for p in output.iterdir() if p.is_file()]
    save(output/'freeze_identity.json',{name:digest(output/name) for name in names})
    for path in output.iterdir():path.chmod(0o444)
    output.chmod(0o555)
    return {'status':'FROZEN_TRAIN_SELECTION_V2_NOT_DERIVED','rule':str(output/'rule.json'),'new_calls':0}


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value);return value


def derive(args):
    rule_path=args.rule.resolve();folder=rule_path.parent;metadata=read(folder/'selection.json')
    if metadata.get('status')!='FROZEN_TRAIN_SELECTION_V2':raise ValueError('Freeze the independent v2 rule before reading yields')
    for name,expected in read(folder/'freeze_identity.json').items():
        if digest(folder/name)!=expected:raise ValueError('Frozen selection implementation changed: '+name)
    collection=Path(metadata['parent_collection'])
    if digest(collection)!=metadata['parent_collection_sha256']:raise ValueError('The frozen source collection changed')
    manifest,frozen,_,_=load_definition(collection)
    if manifest!=read(args.input_root/'collection_manifest.json'):raise ValueError('Raw pool does not belong to this frozen source collection')
    if digest(manifest['label_rule_path'])!=metadata['parent_label_rule_sha256']:raise ValueError('The original v1 rule changed')
    parent=read(folder/'parent_rule.json');rule=read(rule_path)
    implementation=module(folder/'selection_v2.py','_frozen_training_selection_v2')
    legacy=module(folder/'base_selection.py','_frozen_training_selection_base')
    if rule!=implementation.make_rule(parent,manifest['sampling']):raise ValueError('v2 changed more than the declared SFT representative rule')
    registry=bound_registry(frozen,read(args.input_root/'effective_registry.json'))
    completion_path=args.input_root/'completion.json';completion=read(completion_path) if completion_path.exists() else {}
    interruption=interrupted_context_overflow(args.input_root,manifest,args.interrupted_collection_evidence) if args.interrupted_collection_evidence else None
    if interruption and not args.completed_initial_state_id:raise ValueError('Explicitly select complete interrupted initial states')
    selected,scope=completed_state_scope(args.input_root,manifest,registry,args.completed_initial_state_id,completion,interruption)
    rows=[json.loads(line) for line in (args.input_root/'candidates.jsonl').read_text().splitlines() if line.strip()]
    if selected is not None:rows=[row for row in rows if row['initial_state_id'] in selected]
    attempts=read(args.input_root/'attempts.json');actual={row['candidate_id']:row for row in attempts};field=rule['sft_selection']['actual_trial_field']
    store=TrustedPhysicalStore(args.input_root,registry);admitted=[];rejections=[]
    for row in rows:
        logged=actual.get(row['candidate_id'],{})
        if (logged.get('initial_state_id')!=row['initial_state_id'] or field not in logged
            or row.get('proposal_generation',{}).get(field)!=logged[field]):
            rejections.append({'candidate_id':row['candidate_id'],'error':'Actual trial identity differs from its host attempt log'});continue
        try:admitted.extend(admit_candidates([row],registry,store))
        except (ValueError,OSError,KeyError) as exc:rejections.append({'candidate_id':row['candidate_id'],'error':str(exc)})
    args.output_root.mkdir(parents=True,exist_ok=False)
    for name in ('training.py','device_intent.py'):shutil.copyfile(ROOT/'src'/name,args.output_root/('admission_'+name))
    admission={'status':'QUARANTINED' if rejections else 'RE_ADMITTED_FROM_RAW','raw_candidates':len(rows),
        'admitted_candidates':len(admitted),'rejections':rejections,'collection_scope':scope,
        'gate':'current_TrustedPhysicalStore_and_real_trial_log_binding','old_T1_T4_reused':False,'negative_labels_from_quarantine':False}
    save(args.output_root/'physical_readmission.json',admission)
    if rejections:return {'status':'QUARANTINED_NO_DATASET','report':str(args.output_root/'physical_readmission.json'),'new_calls':0}
    if admitted:
        first,report1=legacy.build_matched_samples(admitted,parent)
        second,report2=implementation.build_matched_samples_v2(admitted,rule,legacy)
    else:
        first={key:[] for key in ('T1','T2','T3','T4')};second={key:[] for key in first}
        report1=report2={'initial_states':0,'samples':{key:0 for key in first}}
    for method in ('T3','T4'):
        comparable=lambda values:[{k:v for k,v in row.items() if k!='label_rule_version'} for row in values]
        if comparable(first[method])!=comparable(second[method]):raise ValueError('v2 unexpectedly changed a DPO pair, context or preference')
    from transformers import AutoTokenizer
    cache=read(ROOT/'configs/training/backbone_cache.json')
    tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
    datasets1,budget1=derive_matched_samples(first,tokenizer,16384,interface_version=CONTEXT_VERSION)
    datasets2,budget2=derive_matched_samples(second,tokenizer,16384,interface_version=CONTEXT_VERSION)
    for method,values in datasets2.items():
        (args.output_root/(method+'.jsonl')).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in values))
    for method,values in datasets1.items():
        (args.output_root/('v1_sensitivity_'+method+'.jsonl')).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in values))
    save(args.output_root/'trusted_evidence_manifest.json',{'status':'admitted','role':'formal_train',
        'readmission_report':'physical_readmission.json','registry_sha256':digest(args.input_root/'effective_registry.json'),
        'admitted_sample_ids':[row['sample_id'] for values in second.values() for row in values],
        'sample_sha256':{row['sample_id']:sample_identity(row) for values in second.values() for row in values}})
    budget2.update(status='DERIVED_REQUIRES_TRAINING_MANIFEST_FREEZE',derived_at_utc=datetime.now(timezone.utc).isoformat(),
        raw_collection_root=str(args.input_root.resolve()),student_interface_source_version=CONTEXT_VERSION,
        tokenizer_revision=cache['revision'],
        physical_readmission_report='physical_readmission.json',raw_evidence_re_admitted=True,collection_scope=scope,
        effective_registry_path=str((args.input_root/'effective_registry.json').resolve()),selection_rule=str(rule_path),
        formal_training_started=False)
    save(args.output_root/'student_selection.json',budget2)
    comparison={'status':'ACTUAL_COMMON_TRAIN_POOL_V1_V2_DERIVED_NO_TRAINING','selection_rule':str(rule_path),
        'raw_pool':str(args.input_root.resolve()),'collection_scope':scope,'current_gate_admitted_candidates':len(admitted),
        'v1_physical_selection':report1,'v2_physical_selection':report2,'v1_student_budget_selection':budget1,
        'v2_student_budget_selection':budget2,'DPO_preferences_contexts_and_pairs_exactly_unchanged':True,
        'independent_initial_states_not_multiplied':True,'validation_or_test_outcomes_used':False,
        'new_model_calls':0,'new_physical_calls':0,'formal_training_runs':0}
    save(args.output_root/'v1_v2_yield_comparison.json',comparison)
    return {'status':comparison['status'],'comparison':str(args.output_root/'v1_v2_yield_comparison.json'),
        'v1_usable_counts':{k:len(v) for k,v in datasets1.items()},'v2_usable_counts':{k:len(v) for k,v in datasets2.items()},'new_calls':0}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--freeze-rule',action='store_true');g.add_argument('--derive',action='store_true')
    p.add_argument('--collection',type=Path);p.add_argument('--rule',type=Path);p.add_argument('--input-root',type=Path)
    p.add_argument('--output-root',type=Path,required=True);p.add_argument('--completed-initial-state-id',action='append')
    p.add_argument('--interrupted-collection-evidence',type=Path);a=p.parse_args()
    if a.freeze_rule:
        if a.collection is None:p.error('--freeze-rule needs the real frozen collection')
        result=freeze_rule(a.collection,a.output_root)
    else:
        if a.rule is None or a.input_root is None:p.error('--derive needs the frozen v2 rule and actual raw pool')
        result=derive(a)
    print(json.dumps(result,indent=2))
