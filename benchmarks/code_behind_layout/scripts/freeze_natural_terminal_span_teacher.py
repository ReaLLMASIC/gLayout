"""Prepare only the two natural-terminal span16 after actual fresh18; no model/EDA calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.run_natural_terminal_baselines import load
from scripts.audit_train_pair_nf_rc import contracted_devices
from src.training import TrustedPhysicalStore
from src.device_intent import compare_device_intent
from scripts.prepare_natural_terminal_baselines import packet, preflight
from src.train_natural_terminal_span_bundle import BUNDLE_VERSION, CONTEXTS, load_bundle
from src.train_span_proposer import MODE,ROLE,VERSION,SCHEMA,teacher_request,mapping_proof


def read(p):return json.loads(Path(p).read_text())
def save(p,value):Path(p).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_control(result,point,collection,registry,state):
    """Read actual fresh controls without overwriting any prior audit or cost."""
    run=Path(result['run_directory']);manifest=read(run/'manifest.json')
    if manifest.get('phase')!='formal_train' or manifest['context'].get('evidence_roles')!=['trusted_evaluator_control']:
        raise ValueError('Only these fresh formal baseline/control runs can bind the new initial')
    point['gold_control']={'run_directory':str(run)}
    row={'candidate_id':state['initial_state_id']+'__baseline','initial_state_id':state['initial_state_id'],
        'parent_lineage':state['parent_lineage'],'pdk_revision':collection['pdk_revision'],
        'visible_contract':{'task_id':state['task_id'],'editable_paths':list(state['base_source'])}}
    checked=TrustedPhysicalStore(ROOT,registry)._read_run(str((run/'manifest.json').relative_to(ROOT)),
        row,point['configuration_id'],state['base_source'],row['candidate_id'])
    pex=read(run/'evidence/validation.json')['artifacts']['pex']
    if pex['ports']!=point['parameters']['circuit']['ports']:raise ValueError('Unchanged bench port order differs')
    view=contracted_devices((run/'evidence'/pex['netlist']).read_text(),pex['top_cell'],pex['ports'])
    graph=compare_device_intent(view,(run/'trusted/references'/(point['configuration_id']+'.spice')).read_text())
    if not checked.get('point_evaluation_complete') or not checked['S2'] or not graph['is_clean']:
        raise ValueError('Every fresh baseline must retain complete S2 and exact fullRC device graph')
    return {**checked,'full_RC_device_graph_audit':graph}


def prepare(plan_path, output, tokenizer_path):
    began=time.monotonic(); cpu=time.process_time()
    from transformers import AutoTokenizer
    plan_path=Path(plan_path).resolve();plan,data=load(plan_path);actual=Path(plan['output_root'])
    if not (actual/'completion.json').is_file():
        raise ValueError('Natural-terminal proposals stay DRAFT until the complete fresh formal18 has a real terminal receipt')
    terminal=read(actual/'completion.json')
    if (terminal['status']!='COMPLETED_FORMAL18_ALL_QUALIFIED_NO_MODELS'
            or terminal.get('qualified_points')!=18 or terminal.get('not_run')
            or len(terminal['cells'])!=18 or any(c['status']!='COMPLETE_QUALIFIED_FORMAL_BASELINE' for c in terminal['cells'])):
        raise ValueError('Natural-terminal proposals stay DRAFT until the complete fresh formal18 terminates successfully')
    tokenizer=AutoTokenizer.from_pretrained(str(tokenizer_path),local_files_only=True,trust_remote_code=False)
    if tokenizer.eos_token_id!=151645:raise ValueError('Unexpected pinned tokenizer EOS')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    interface=output/'interface';(interface/'src').mkdir(parents=True)
    (interface/'src/__init__.py').write_text('')
    for name in ['train_span_proposer','train_span_cli','model_adapter','local_model_adapter','policy_state',
                 'student_interface','training','measurement','report_parsers','spice_validation']:
        shutil.copyfile(ROOT/'src'/(name+'.py'),interface/'src'/(name+'.py'))
    # This is an explicitly new interface snapshot, not a modification of the old bundle/loader.
    shutil.copyfile(ROOT/'src/train_natural_terminal_span_bundle.py',interface/'src/train_span_bundle.py')
    shutil.copyfile(ROOT/'scripts/serve_train_span_teacher.py',interface/'broker.py')
    collector=(ROOT/'scripts/collect_train_span_proposals.py').read_text()
    old="'initial_contexts_reused': 2, 'independent_contexts_added': 0, 'new_physical_calls': 0,"
    new="'new_physical_domain_contexts': 0, 'new_initial_source_ASTs': 2, 'new_lineages': 0, 'new_physical_calls': 0,"
    if collector.count(old)!=1:raise ValueError('Review the concrete collector accounting export before preparing natural-terminal')
    collector=collector.replace(old,new)
    (interface/'collector.py').write_text(collector)
    shutil.copyfile(Path(__file__),interface/'freezer.py');save(interface/'span_schema.json',SCHEMA)
    save(interface/'prospective_export.json',{'natural_terminal_loader_source':'src/train_natural_terminal_span_bundle.py',
        'collector_source':'scripts/collect_train_span_proposals.py','exact_old_accounting_text':old,'exact_new_accounting_text':new,
        'readiness':'All eighteen fresh controls and fullRC graphs required before this separate bundle can freeze; Root alone drains and changes the broker.',
        'compiler_CLI_schema_prompt_and_model_dispatch_code_changed':False,'old_bundle_or_LIVE_changed':False})
    save(output/'tokenizer_inventory.json',{'revision':'381fc969f78efac66bc87ff7ddeadb7e73c218a7','eos_token_id':151645,
        'files_sha256':{name:sha(Path(tokenizer_path)/name) for name in ['vocab.json','merges.txt','tokenizer.json','tokenizer_config.json']}})
    records=[];contexts=[];flights=[]
    for source,(parent_id,sid) in zip(data,CONTEXTS):
        collection,registry,state=source['collection'],source['registry'],source['initial_state']
        if collection['collection_id']!=parent_id or state['initial_state_id']!=sid:raise ValueError('Natural-terminal context identity differs')
        cid=collection['circuit_id'];raw=actual/cid;baselines=read(raw/'baseline_results.json');summaries=[]
        if set(baselines)!={p['configuration_id'] for p in registry['configurations']}:raise ValueError('Do not omit a declared point')
        for point in registry['configurations']:
            result=baselines[point['configuration_id']];checked=read_control(result,point,collection,registry,state)
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
    audit_inputs=[c[key] for c in contexts for key in ['original_request','teacher_request','student_request','initial_state','baseline_results','effective_registry']]
    save(output/'baseline_audit.json',{'phase':'formal_train','all_eighteen_points_complete':True,'records':records,
        'input_files_sha256':{name:sha(output/name) for name in audit_inputs},
        'audited_at_utc':datetime.now(timezone.utc).isoformat(),'actual_wall_seconds':time.monotonic()-began,
        'actual_CPU_seconds':time.process_time()-cpu,'new_model_calls':0,'new_physical_calls':0,'training_examples':0})
    save(output/'teacher_context_preflight.json',flights)
    manifest={'status':'DRAFT_NO_MODEL_CALLS','role':'train_proposal_collection','collection_id':'natural_terminal_c01_c02_literal_span16_v1',
        'bundle_version':BUNDLE_VERSION,'teacher_interface_version':VERSION,'source_role':ROLE,'contexts':contexts,
        'planned_proposals':16,'new_physical_domain_contexts':0,'new_initial_source_ASTs':2,'new_lineages':0,
        'useful_SFT_contexts_established':0,'Point_Family_opposite_pairs_established':0,
        'sampling':{'backend':'isolated_gpt_cli','model':'gpt-6.1-sol','reasoning_effort':'high','mode':MODE,
            'trials':list(range(1,9)),'seed':None,'proposal_workers':2,'max_new_tokens':3072,'max_context_tokens':16384,'timeout_seconds':240},
        'student_preselection':{'interface_version':'ordinary_policy_action_context_v2','max_new_tokens':1024,'max_context_tokens':16384,'stage':'before_physics'},
        'endpoint':'http://127.0.0.1:8116/spans/decision','broker_endpoint':'http://127.0.0.1:8122/decision',
        'output_root':str(ROOT/'runs/train_proposals/natural_terminal_literal_span16_v1'),'maximum_dispatch_hours':4,
        'shared_global_inference_slots':2,'physical_runs_in_this_collection':0,'training_rows_in_this_collection':0,
        'prepared_at_utc':datetime.now(timezone.utc).isoformat(),'parent_formal18_plan':str(plan_path),
        'prospective_input_change':'Unlike the old span16, both teacher and ordinary student receive the full actual generator.py as a read-only document. This is additional visible execution information, not a controlled producer-only comparison. Editable source/N/spec/defaultmode remain unchanged; no repair hint is added.',
        'dispatch_condition':'After fresh18/current gate/preflight and Root review/freeze: the actual current8122 proposal collector and every accepted broker session are terminal, active_requests=0, and gate-to8122 has no ESTABLISHED connections. Root alone reviews those actual identities and changes the8122 upstream bundle. Shared global2 and other routes remain running. Preparation never signals/reloads services or issues model requests.',
        'counting':'Two new natural initial full-source ASTs, zero new circuits/domains or source lineages. All16 proposals may yield zero useful contexts or zero opposite pairs.'}
    save(output/'collection.json',manifest)
    return {'status':manifest['status'],'collection':str(output/'collection.json'),'audited_fresh_formal_points':len(records),'preflights':flights,'new_model_calls':0,'new_physical_calls':0}


def freeze(collection):
    path=Path(collection).resolve();root=path.parent;manifest=read(path)
    if manifest['status']!='DRAFT_NO_MODEL_CALLS':raise ValueError('Freeze only the independently reviewed new natural-terminal draft')
    for name,digest in read(root/'baseline_audit.json')['input_files_sha256'].items():
        if sha(root/name)!=digest:raise ValueError('Natural-terminal context changed after actual eighteen-control audit')
    manifest.update(status='frozen',frozen_at_utc=datetime.now(timezone.utc).isoformat());save(path,manifest)
    save(root/'freeze_identity.json',{str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts})
    for p in sorted(root.rglob('*'),key=lambda p:len(p.parts),reverse=True):p.chmod(0o555 if p.is_dir() else 0o444)
    root.chmod(0o555);load_bundle(path)
    return {'status':'FROZEN_NATURAL_TERMINAL_PROPOSAL_ONLY_NO_MODEL_CALLS','collection':str(path),'new_model_calls':0,'new_physical_calls':0}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--tokenizer',type=Path);p.add_argument('--collection',type=Path)
    modes=p.add_mutually_exclusive_group(required=True);modes.add_argument('--prepare',action='store_true');modes.add_argument('--freeze',action='store_true')
    a=p.parse_args();print(json.dumps(prepare(a.plan,a.output,a.tokenizer) if a.prepare else freeze(a.collection),indent=2,allow_nan=False))
