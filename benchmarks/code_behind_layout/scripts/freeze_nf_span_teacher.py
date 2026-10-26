"""Prepare the NF-only next span16 after fresh formal18; no model or EDA calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.run_nf_span_baselines import load, check_result
from scripts.prepare_nf_span_baselines import packet, preflight
from src.train_nf_span_bundle import NF_VERSION, CONTEXTS, load_bundle, with_readonly_entrypoint
from src.train_span_proposer import MODE,ROLE,VERSION,SCHEMA,teacher_request,mapping_proof


def read(p):return json.loads(Path(p).read_text())
def save(p,value):Path(p).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare(plan_path, output, tokenizer_path):
    from transformers import AutoTokenizer
    plan_path=Path(plan_path).resolve();plan,data=load(plan_path);actual=Path(plan['output_root'])
    if not (actual/'completion.json').is_file():
        raise ValueError('NF proposals stay DRAFT until the complete fresh formal18 has a real terminal receipt')
    terminal=read(actual/'completion.json')
    if (terminal['status']!='COMPLETED_FORMAL18_ALL_QUALIFIED_NO_MODELS'
            or terminal.get('qualified_points')!=18 or terminal.get('not_run')
            or len(terminal['cells'])!=18 or any(c['status']!='COMPLETE_QUALIFIED_FORMAL_BASELINE' for c in terminal['cells'])):
        raise ValueError('NF proposals stay DRAFT until the complete fresh formal18 terminates successfully')
    tokenizer=AutoTokenizer.from_pretrained(str(tokenizer_path),local_files_only=True,trust_remote_code=False)
    if tokenizer.eos_token_id!=151645:raise ValueError('Unexpected pinned tokenizer EOS')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    interface=output/'interface';(interface/'src').mkdir(parents=True)
    (interface/'src/__init__.py').write_text('')
    for name in ['train_span_proposer','train_span_cli','model_adapter','local_model_adapter','policy_state',
                 'student_interface','training','measurement','report_parsers','spice_validation']:
        shutil.copyfile(ROOT/'src'/(name+'.py'),interface/'src'/(name+'.py'))
    # This is an explicitly new interface snapshot, not a modification of the old bundle/loader.
    shutil.copyfile(ROOT/'src/train_nf_span_bundle.py',interface/'src/train_span_bundle.py')
    broker=(ROOT/'scripts/serve_train_span_teacher.py').read_text()
    anchor="    manifest = load_bundle(args.collection)\n    validate_tokenizer(args.tokenizer, bundle)"
    replacement="    manifest = load_bundle(args.collection)\n    from src.train_span_bundle import validate_rules_ready\n    validate_rules_ready(json.loads(args.rules_ready.read_text()), hashlib.sha256(args.collection.read_bytes()).hexdigest())\n    validate_tokenizer(args.tokenizer, bundle)"
    if broker.count(anchor)!=1:raise ValueError('Review changed broker startup before NF export')
    broker=broker.replace(anchor,replacement)
    anchor2="    serve(parser.parse_args())"
    if broker.count(anchor2)!=1:raise ValueError('Review changed broker CLI before NF export')
    broker=broker.replace(anchor2,"    parser.add_argument('--rules-ready', type=Path, required=True)\n"+anchor2)
    (interface/'broker.py').write_text(broker)
    collector=(ROOT/'scripts/collect_train_span_proposals.py').read_text()
    old="'initial_contexts_reused': 2, 'independent_contexts_added': 0, 'new_physical_calls': 0,"
    new="'new_physical_domain_contexts': 2, 'new_initial_source_ASTs': 0, 'new_lineages': 0, 'new_physical_calls': 0,"
    if collector.count(old)!=1:raise ValueError('Review the concrete collector accounting export before preparing NF')
    collector=collector.replace(old,new)
    guard="    from src.train_span_bundle import validate_rules_ready\n    validate_rules_ready(read(Path(manifest['rules_ready_path'])), hashlib.sha256(args.collection.read_bytes()).hexdigest(), Path(manifest['joint_acceptance_plan']))\n"
    if collector.count('    def get(url):')!=1:raise ValueError('Review changed collector startup before NF export')
    (interface/'collector.py').write_text(collector.replace('    def get(url):',guard+'    def get(url):'))
    shutil.copyfile(Path(__file__),interface/'freezer.py');save(interface/'span_schema.json',SCHEMA)
    save(interface/'prospective_export.json',{'NF_loader_source':'src/train_nf_span_bundle.py',
        'collector_source':'scripts/collect_train_span_proposals.py','exact_old_accounting_text':old,'exact_new_accounting_text':new,
        'rules_ready_gate':'New NF-only broker requires operator-provided rule-ready receipt; remote collector binds actual frozen acceptance SHA before any HTTP inference request. Ordinary old broker/collector remain untouched.',
        'compiler_CLI_schema_prompt_and_model_dispatch_code_changed':False,'old_bundle_or_LIVE_changed':False})
    save(output/'tokenizer_inventory.json',{'revision':'381fc969f78efac66bc87ff7ddeadb7e73c218a7','eos_token_id':151645,
        'files_sha256':{name:sha(Path(tokenizer_path)/name) for name in ['vocab.json','merges.txt','tokenizer.json','tokenizer_config.json']}})
    records=[];contexts=[];flights=[]
    for source,(parent_id,sid) in zip(data,CONTEXTS):
        collection,registry,state=source['collection'],source['registry'],source['initial_state']
        if collection['collection_id']!=parent_id or state['initial_state_id']!=sid:raise ValueError('NF context identity differs')
        cid=collection['circuit_id'];raw=actual/cid;baselines=read(raw/'baseline_results.json');summaries=[]
        if set(baselines)!={p['configuration_id'] for p in registry['configurations']}:raise ValueError('Do not omit a declared point')
        for point in registry['configurations']:
            result=baselines[point['configuration_id']];checked=check_result(result,point,collection,registry,state)
            records.append({'initial_state_id':sid,'configuration_id':point['configuration_id'],'phase':'formal_train',
                'run_directory':result['run_directory'],'S2':checked['S2'],'point_evaluation_complete':checked['point_evaluation_complete'],
                'full_RC_device_graph_clean':checked['full_RC_device_graph_audit']['is_clean']})
            summaries.append({'configuration_id':point['configuration_id'],'S0':checked['S0'],'S1':checked['S1'],
                'S2':checked['S2'],'objective':checked['objective'],'failure_class':checked.get('failure_class'),'reason':checked.get('reason')})
        ordinary,teacher,mapping=packet(collection,state,registry['configurations'],summaries)
        student=mapping.pop('ordinary_request')
        if any(json.dumps(value)!=json.dumps(read(raw/name)) for value,name in [
                (ordinary,'ordinary_request.json'),(teacher,'teacher_request.json'),(student,'student_request.json')]):
            raise ValueError('Fresh raw controls do not reproduce the exact materialized context and serialization order')
        entrypoint=(Path(collection['source_pack'])/'generator.py').read_bytes()
        if any((Path(result['run_directory'])/'source/generator.py').read_bytes()!=entrypoint for result in baselines.values()):
            raise ValueError('Do not describe an entrypoint different from actual formal execution')
        ordinary=with_readonly_entrypoint(ordinary,entrypoint.decode('utf-8'))
        teacher=teacher_request(ordinary);mapping=mapping_proof(ordinary,teacher);student=mapping.pop('ordinary_request')
        flight=preflight(tokenizer,ordinary,teacher)
        folder=output/'contexts'/sid;folder.mkdir(parents=True)
        (folder/'readonly_generator.py').write_bytes(entrypoint)
        values={'original_request':ordinary,'teacher_request':teacher,'student_request':student,'mapping_proof':mapping,
            'initial_state':state,'baseline_results':baselines,'effective_registry':registry,'parent_collection':collection,
            'label_rule':read(Path(collection['registry_path']).parent/'parent_label_rule.json')}
        record={'initial_state_id':sid,'parent_collection_id':parent_id,'parent_lineage':state['parent_lineage'],
                'readonly_entrypoint':str((folder/'readonly_generator.py').relative_to(output)),
                'parent_actual_baseline_path':str(raw/'baseline_results.json')}
        for name,value in values.items():
            file=folder/(name+'.json');save(file,value);record[name]=str(file.relative_to(output))
        contexts.append(record);flights.append({'initial_state_id':sid,**flight,'actual_fresh_formal_feedback':True})
    shutil.copyfile(plan_path.parent/'hypothesis.json',output/'hypothesis.json')
    audit_inputs=[c[key] for c in contexts for key in ['original_request','teacher_request','student_request','initial_state','baseline_results','effective_registry']]
    save(output/'baseline_audit.json',{'phase':'formal_train','all_eighteen_points_complete':True,'records':records,
        'input_files_sha256':{name:sha(output/name) for name in audit_inputs},
        'audited_at_utc':datetime.now(timezone.utc).isoformat(),'new_model_calls':0,'new_physical_calls':0,'training_examples':0})
    save(output/'teacher_context_preflight.json',flights)
    manifest={'status':'DRAFT_NO_MODEL_CALLS','role':'train_proposal_collection','collection_id':'c02_c07_matched_nf_literal_span_v2',
        'NF_bundle_version':NF_VERSION,'teacher_interface_version':VERSION,'source_role':ROLE,'contexts':contexts,
        'planned_proposals':16,'new_physical_domain_contexts':2,'new_initial_source_ASTs':0,'new_lineages':0,
        'useful_SFT_contexts_established':0,'Point_Family_opposite_pairs_established':0,
        'sampling':{'backend':'isolated_gpt_cli','model':'gpt-6.1-sol','reasoning_effort':'high','mode':MODE,
            'trials':list(range(1,9)),'seed':None,'proposal_workers':2,'max_new_tokens':3072,'max_context_tokens':16384,'timeout_seconds':240},
        'student_preselection':{'interface_version':'ordinary_policy_action_context_v2','max_new_tokens':1024,'max_context_tokens':16384,'stage':'before_physics'},
        'endpoint':'http://127.0.0.1:8116/spans/decision','broker_endpoint':'http://127.0.0.1:8122/decision',
        'output_root':str(ROOT/'runs/train_proposals/c02_c07_matched_nf_literal_span_v2'),'maximum_dispatch_hours':4,
        'rules_ready_path':str(ROOT/'runs/train_collection/NF_joint_v2/rules_ready.json'),
        'joint_acceptance_plan':str(ROOT/'runtime/train_collection_acceptance/NF_joint_v2/acceptance.json'),
        'shared_global_inference_slots':2,'physical_runs_in_this_collection':0,'training_rows_in_this_collection':0,
        'prepared_at_utc':datetime.now(timezone.utc).isoformat(),'parent_formal18_plan':str(plan_path),
        'prospective_input_change':'Unlike the old span16, both teacher and ordinary student receive the full actual generator.py as a read-only document. This is additional visible execution information, not a controlled producer-only comparison. Editable source/N/spec/defaultmode remain unchanged; no repair hint is added.',
        'dispatch_condition':'After fresh18/current gate/preflight and Root review/freeze: current span16 remote proposal collector is terminal, local8122 all16 sessions terminal with active_requests=0, and gate-to8122 has no ESTABLISHED connections. Root changes only the8122 upstream bundle; shared gate29979/global2 and old8118/96 routes remain running. Oldspan physical consumer may continue. Preparation never signals/reloads services or issues models.',
        'counting':'Two new physical circuit-domain contexts, zero new initial-source AST or source lineage. All16 proposals can yield zero useful contexts or zero opposite pairs.'}
    save(output/'collection.json',manifest)
    return {'status':manifest['status'],'collection':str(output/'collection.json'),'audited_fresh_formal_points':len(records),'preflights':flights,'new_model_calls':0,'new_physical_calls':0}


def freeze(collection):
    path=Path(collection).resolve();root=path.parent;manifest=read(path)
    if manifest['status']!='DRAFT_NO_MODEL_CALLS':raise ValueError('Freeze only the independently reviewed new NF draft')
    for name,digest in read(root/'baseline_audit.json')['input_files_sha256'].items():
        if sha(root/name)!=digest:raise ValueError('NF context changed after actual eighteen-control audit')
    manifest.update(status='frozen',frozen_at_utc=datetime.now(timezone.utc).isoformat());save(path,manifest)
    save(root/'freeze_identity.json',{str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts})
    for p in sorted(root.rglob('*'),key=lambda p:len(p.parts),reverse=True):p.chmod(0o555 if p.is_dir() else 0o444)
    root.chmod(0o555);load_bundle(path)
    return {'status':'FROZEN_NF_PROPOSAL_ONLY_NO_MODEL_CALLS','collection':str(path),'new_model_calls':0,'new_physical_calls':0}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--tokenizer',type=Path);p.add_argument('--collection',type=Path)
    modes=p.add_mutually_exclusive_group(required=True);modes.add_argument('--prepare',action='store_true');modes.add_argument('--freeze',action='store_true')
    a=p.parse_args();print(json.dumps(prepare(a.plan,a.output,a.tokenizer) if a.prepare else freeze(a.collection),indent=2,allow_nan=False))
