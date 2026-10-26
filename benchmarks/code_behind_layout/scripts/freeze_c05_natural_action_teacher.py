"""Freeze three real natural failures with ordinary ACTION and complete API feedback."""
import argparse
import ast
from datetime import datetime,timezone
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import load
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget
from scripts.run_frozen_training_collection import load_definition


def save(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preparation',type=Path,required=True);args=parser.parse_args()
    prep=json.loads(args.preparation.read_text());base,registry,_,_=load(Path(prep['base_collection_manifest']))
    if prep['collection_id']!='c05_natural_api_repair_teacher_v1' or prep['initial_state_count']!=3 or len(prep['gold_controls'])!=9:
        raise ValueError('Only the three approved genuine model-produced C05 failures are in scope')
    states=[json.loads(line) for line in Path(prep['initial_states_path']).read_text().splitlines() if line.strip()]
    if any(list(state['base_source'])!=['textbook_sharing/layout.py'] or not state['ancestry'].get('not_manually_injected_or_reverse_patched') for state in states):
        raise ValueError('Preserve the complete three actual layout programs and original ancestry')
    parent=Path(base['output_root']);readmission=json.loads((ROOT/'runs/train_collection/c05_minimal_gpt_teacher_v1_student_readmission_v1/physical_readmission.json').read_text())
    if readmission['status']!='RE_ADMITTED_FROM_RAW' or readmission['admitted_candidates']!=7:raise ValueError('Current strict parent-pool admission required')
    identifier='c05_natural_action_teacher_v1';output=ROOT/'runtime/train_collections'/identifier;output.mkdir()
    prior_interface=ROOT/'runtime/train_collections/c01_planning_action_gpt_teacher_v1/interface';shutil.copytree(prior_interface,output/'interface')
    for path in (output/'interface').rglob('*'):path.chmod(0o755 if path.is_dir() else 0o644)
    (output/'interface').chmod(0o755)
    source=(prior_interface/'collector.py').read_text();old=source
    marker="    observation={'status':'begin','actual_new_baseline':"
    insertion="    if manifest.get('teacher_packet_version')=='ordinary_action_generation_feedback_v1':\n        visible['documents']['assembly_api']=json.loads(Path(manifest['teacher_public_api_document']).read_text())\n        visible['documents']['frozen_api']='The public assembly API window contains the complete RowSpec, AssemblyError and assemble declarations. Its private implementation and all other modules are frozen. Only the entire visible layout module may be edited.'\n        visible['goal']='Return one ordinary propose_patch ACTION_JSON with the smallest necessary executable layout changes. Preserve unaffected lines, all frozen APIs and physical constraints; use the actual baseline generation feedback. No coordinator patch repair occurs.'\n"
    if source.count(marker)!=1:raise ValueError('Expected the exact approved collector packet builder')
    source=source.replace(marker,insertion+marker)
    needle="    if manifest['sampling']['mode'] in ['train_collection_source','train_collection_source_gpt']:\n        diagnostics={}"
    if source.count(needle)!=1:raise ValueError('Expected the exact retained generation-diagnostic builder')
    source=source.replace(needle,"    if manifest['sampling']['mode'] in ['train_collection_source','train_collection_source_gpt'] or manifest.get('teacher_packet_version')=='ordinary_action_generation_feedback_v1':\n        diagnostics={}")
    (output/'interface/collector.py').write_text(source)
    (output/'interface/base_collector.py').write_text(old)
    (output/'interface/collector_changes.diff').write_text(''.join(difflib.unified_diff(old.splitlines(True),source.splitlines(True),fromfile='base_collector.py',tofile='collector.py')))
    # Complete public API semantic window, not a shortened editable module.
    api_path=Path(base['source_pack'])/'textbook_sharing/assembly/engine.py';api_source=api_path.read_text();tree=ast.parse(api_source);lines=api_source.splitlines(True)
    symbols=['AssemblyError','RowSpec','assemble'];declarations=[]
    for name in symbols:
        node=next(node for node in tree.body if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name==name)
        first=min([node.lineno]+[d.lineno for d in getattr(node,'decorator_list',[])])
        declarations.append({'symbol':name,'start_line':first,'end_line':node.end_lineno,'source':''.join(lines[first-1:node.end_lineno])})
    public_api={'source_module':'textbook_sharing/assembly/engine.py','visibility':'complete_public_API_declarations',
        'scope':'Exact complete public entrypoint and data/error declarations; private geometry implementation remains frozen and is not an editable source window.',
        'imports':'from __future__ import annotations\nfrom dataclasses import dataclass\nfrom typing import Optional\n',
        'declarations':declarations,'source_bytes_in_entire_frozen_module':len(api_source.encode()),'source_truncated_within_declared_symbols':False}
    save(output/'interface/public_assembly_api.json',public_api)
    template=json.loads((prior_interface.parent/'collection.json').read_text())
    shutil.copyfile(base['registry_path'],output/'registry.json');shutil.copyfile(base['label_rule_path'],output/'label_rule.json')
    shutil.copyfile(args.preparation,output/'parent_source_teacher_DRAFT.json')
    shutil.copyfile(prep['initial_states_path'],output/'initial_states.jsonl')
    manifest={**base,'collection_id':identifier,'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'registry_path':str(output/'registry.json'),'label_rule_path':str(output/'label_rule.json'),'initial_states_path':str(output/'initial_states.jsonl'),
        'output_root':str(ROOT/'runs/train_collection'/identifier),'evidence_root':str(ROOT/'runs/train_collection'/identifier),
        'sampling':template['sampling'],'student_preselection':template['student_preselection'],
        'teacher_interface_version':'ordinary_action_teacher_v1','teacher_interface_path':str(output/'interface'),
        'teacher_packet_version':'ordinary_action_generation_feedback_v1','teacher_public_api_document':str(output/'interface/public_assembly_api.json'),
        'frozen_collector_entrypoint':'interface/collector.py','budget_tokenizer_revision':template['budget_tokenizer_revision'],
        'gold_controls':prep['gold_controls'],'physical':{**base['physical'],'workers':1},
        'budget':{**base['budget'],'initial_batch_initial_states':3},'transport':template['transport'],'isolation':template['isolation'],
        'output_budget_scope':template['output_budget_scope'],'parent_collection_scope':prep['original_parent_collection_plan_retained'],
        'source_scope':'Complete actual layout.py only; all other source bytes fixed. Complete public assemble/RowSpec/AssemblyError API declarations are visible documents, with exact source locations.',
        'admission':'New failed-source baseline9 and eight new ordinary ACTION proposals per natural initial program; full current strict physical admission and paired student budgets. Old24/8/16 parent status retained. No old outcome is relabelled as a new run.',
        'source_program_counting':'Three genuinely different initial planning programs, one compiler lineage. Repeated repaired terminal ASTs are reported separately.',
        'old_raw_or_completion_changed':False,'formal_training_runs':0}
    manifest.pop('teacher_instruction_version',None)
    # Use the newly frozen packet implementation for exact preflight, while ROOT
    # continues to name this research workspace rather than the snapshot folder.
    spec=importlib.util.spec_from_file_location('_c05_action_feedback_preflight',output/'interface/collector.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.ROOT=ROOT
    from src.training import TrustedPhysicalStore
    from transformers import AutoTokenizer
    cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text());tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
    raw=[json.loads(line) for line in (parent/'candidates.jsonl').read_text().splitlines() if line.strip()];effective=json.loads((parent/'effective_registry.json').read_text());points=effective['configurations'];point_map={point['configuration_id']:point for point in points}
    assignment=next(row for row in registry['lineages'] if row['lineage_id']==states[0]['parent_lineage']);flights=[]
    for state in states:
        candidate=next(row for row in raw if row['candidate_id']==state['ancestry']['parent_candidate_id']);baseline={}
        for outcome in candidate['outcomes']:
            point={**point_map[outcome['configuration_id']],**{key:assignment[key] for key in ['editable_paths','frozen_source_pack','frozen_source_files']}}
            point.update(lineage_editable_paths=assignment['editable_paths'],editable_paths=list(state['base_source']))
            run=(parent/outcome['evidence_path']).parent;result={**json.loads((run/'manifest.json').read_text()),'run_directory':str(run)}
            checked=TrustedPhysicalStore._inspect_execution_run(run,point,state['base_source']);baseline[outcome['configuration_id']]={'checked':checked,'result':result}
        task,history=module.packet(manifest,state,points,baseline)
        request={'mode':'train_collection_action_gpt','trial_id':1,'request':{'task_packet':task,'visible_history':history}}
        save(output/(state['initial_state_id']+'_request.json'),request)
        budget=prompt_token_budget(tokenizer,decision_prompt(request['request']),{'max_new_tokens':1024,'max_context_tokens':8192})
        flights.append({'initial_state_id':state['initial_state_id'],**budget,'complete_editable_source_bytes':len(state['base_source']['textbook_sharing/layout.py'].encode()),
            'complete_API_symbols':symbols,'actual_generation_diagnostics_present':bool(history[0]['observation'].get('baseline_generation_diagnostics'))})
    flight={'scope':'exact_new_ACTION_complete_source_API_and_actual_feedback_preflight','model_inferences':0,'new_physical_runs':0,'requests':flights,
        'all_requests_fit':all(f['fits_with_full_output_reserve'] and not f['source_or_history_truncated'] and f['actual_generation_diagnostics_present'] for f in flights)}
    save(output/'teacher_context_preflight.json',flight);manifest['teacher_context_preflight']=str(output/'teacher_context_preflight.json')
    if not flight['all_requests_fit']:raise ValueError('Do not freeze or truncate an oversized complete ACTION context')
    save(output/'collection.json',manifest)
    names=sorted(str(path.relative_to(output)) for path in output.rglob('*') if path.is_file())
    save(output/'freeze_identity.json',{name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in names})
    load_definition(output/'collection.json')
    for path in sorted(output.rglob('*'),reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
    output.chmod(0o555)
    print(json.dumps({'collection':str(output/'collection.json'),'status':'frozen','initial_states':3,'planned_requests':24,'model_requests_at_freeze':0,'preflight':flight},indent=2))


if __name__=='__main__':main()
