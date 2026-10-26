"""Bind prospective states to exact frozen inputs and actual teacher patches.

Existing parent readmission is ancestry evidence only. No parent outcome is
used as the outcome of a new program or of a different circuit context.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.candidate_executor import apply_source_patch
from scripts.training_pilot_status import MODULES,program


def read(path):return json.loads(Path(path).read_text())


def parent_pool():
    archive=ROOT/'results/raw/c05_minimal_first_state_partial_20261019T0326Z.tar.gz'
    with tarfile.open(archive) as stream:
        member=next(m for m in stream if m.name=='runs/train_collection/c05_minimal_gpt_teacher_v1/candidates.jsonl')
        rows=[json.loads(line) for line in stream.extractfile(member).read().decode().splitlines() if line.strip()]
    folder=ROOT/'runs/train_collection/c05_minimal_gpt_teacher_v1_student_readmission_v1'
    admission=read(folder/'physical_readmission.json')
    exact_gate=(folder/admission['classifier_source_snapshot']).read_bytes()==(ROOT/'src/training.py').read_bytes()
    exact_devices=(folder/admission['device_graph_source_snapshot']).read_bytes()==(ROOT/'src/device_intent.py').read_bytes()
    accepted=admission['status']=='RE_ADMITTED_FROM_RAW' and admission['raw_candidates']==len(rows)==admission['admitted_candidates'] and not admission['rejections'] and exact_gate and exact_devices
    return {row['candidate_id']:row for row in rows},{'report':str(folder/'physical_readmission.json'),
        'all_parent_rows_admitted_with_same_current_source':accepted,'gate_source_byte_equal_current':exact_gate,
        'device_source_byte_equal_current':exact_devices,'archive':str(archive),
        'admission_is_not_reused_as_child_outcome':True}


def bind_program(row,original,pool,gate):
    proofs=[];selected=None
    for origin in row['origins']:
        if origin['kind']!='actual_isolated_GPT_ACTION_proposal':continue
        reqpath=ROOT/origin['request_path'];invpath=ROOT/origin['invocation_path']
        request=read(reqpath);response=read(invpath)['response'];packet=request['request']['task_packet']
        if response['inference_id']!=origin['inference_id'] or response['model']['source_role']!='isolated_GPT_formal_train_action_teacher' or response['native_tools']:
            raise ValueError('Actual teacher isolation/provenance differs')
        collection,stateid=packet['task_id'].split('__',1)
        folder=ROOT/'runtime/train_collections'/collection;manifest=read(folder/'collection.json')
        if manifest['status']!='frozen' or manifest['role']!='train_collection':raise ValueError('Parent is not a frozen train collection')
        states=[json.loads(line) for line in (folder/Path(manifest['initial_states_path']).name).read_text().splitlines() if line.strip()]
        state=next(s for s in states if s['initial_state_id']==stateid)
        before={**original,**state['base_source']}
        if set(packet['allowed_paths'])!=set(state['base_source']) or packet['visible_sources']!={name:before[name] for name in packet['allowed_paths']}:
            raise ValueError('The actual complete model input differs from its frozen initial source')
        with tempfile.TemporaryDirectory(prefix='iscas-bind-source-',dir='/private/tmp') as temp:
            for name,text in before.items():
                path=Path(temp)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            apply_source_patch(temp,response['action']['patch'],packet['allowed_paths'])
            after={name:(Path(temp)/name).read_text() for name in MODULES}
        same_ast=program(after,original)==program(row['complete_source'],original)
        if not same_ast:raise ValueError('A prospective program differs from its actual generated terminal AST')
        exact=after==row['complete_source']
        ancestor=state.get('ancestry',{}).get('parent_candidate_id');prior={'status':'FORMAL_BASELINE_RAW_NOT_LOCALLY_ARCHIVED',
            'request_baseline_summary_is_not_independent_gate_evidence':True,'future_fresh_baseline9_required':True}
        if ancestor:
            parent=pool[ancestor]
            if {**original,**parent['candidate_source']}!=before:raise ValueError('The frozen natural input differs from the actual parent program')
            if len(parent['outcomes'])!=9 or len({p['configuration_id'] for p in parent['outcomes']})!=9:raise ValueError('Parent ancestry must preserve its full nine-point domain')
            prior={'status':'EXACT_PARENT_SOURCE_WITH_CURRENT_GATE_READMISSION_EVIDENCE' if gate['all_parent_rows_admitted_with_same_current_source'] else 'PARENT_READMISSION_REQUIRES_CURRENT_GATE_RECHECK',
                'parent_candidate_id':ancestor,'physical_outcome_references':parent['outcomes'],**gate,
                'child_terminal_and_other_circuit_outcomes_not_inferred':True,'future_fresh_baseline9_required':True}
        proof={'inference_id':origin['inference_id'],'request_path':str(reqpath),'invocation_path':str(invpath),
            'parent_frozen_manifest':str(folder/'collection.json'),'parent_initial_state_id':stateid,
            'complete_frozen_base_source_byte_equal_actual_request':True,'actual_patch_applied_without_repair':True,
            'terminal_AST_equal_inventory':same_ast,'terminal_source_byte_equal_selected_initial':exact,
            'existing_parent_gate_evidence':prior,'raw_usage_path':str(invpath),'new_model_or_physical_calls':0}
        proofs.append(proof)
        if exact and selected is None:selected=proof
    if selected is None:raise ValueError('No exact real base+patch creates the chosen complete initial source')
    return {'program_id':row['program_id'],'status':'EXACT_REAL_BASE_PLUS_PATCH_BINDING',
        'selected_origin':selected,'all_real_equivalent_AST_origins':proofs,'new_training_labels':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preparation',type=Path,required=True);args=parser.parse_args()
    prep=read(args.preparation)
    if prep['status']!='DRAFT_NOT_FROZEN_NOT_DISPATCHABLE':raise ValueError('Only prospective unfrozen preparation can be bound')
    inventory={row['program_id']:row for row in map(json.loads,(ROOT/'results/derived/train_program_inventory.jsonl').read_text().splitlines())}
    original=next(row['complete_source'] for row in inventory.values() if not row['changed_modules_vs_original'])
    pool,gate=parent_pool();bindings={name:bind_program(inventory[name],original,pool,gate) for name in sorted({row['program_id'] for row in prep['contexts']})}
    initial=[]
    for context in prep['contexts']:
        row=inventory[context['program_id']];binding=bindings[row['program_id']]
        initial.append({'initial_state_id':'draft_'+context['circuit_id'].lower()+'_'+row['program_id']+'_natural_trajectory',
            'origin':'natural','parent_lineage':row['parent_lineage'],'editable_paths':['textbook_sharing/layout.py'],
            'base_source':{'textbook_sharing/layout.py':row['complete_source']['textbook_sharing/layout.py']},
            'target_circuit_id':context['circuit_id'],'status':'DRAFT_NOT_FROZEN_NOT_DISPATCHABLE',
            'source_binding_program_id':row['program_id'],'ancestry':binding['selected_origin'],
            'fresh_nine_point_baseline_and_exact_feedback_token_preflight_required':True,
            'target_task_id_must_be_bound_from_actual_frozen_registry_before_freeze':True})
    out=args.preparation.parent;report=out/'source_bindings.json'
    if report.exists():raise FileExistsError('Preserve prior source bindings; use a new preparation')
    report.write_text(json.dumps({'status':'BOUND_REAL_SOURCE_ANCESTRY_DRAFT_NOT_ADMITTED','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'programs':list(bindings.values()),'contexts':len(initial),'current_gate_parent_source_programs':sum(row['selected_origin']['existing_parent_gate_evidence']['status']=='EXACT_PARENT_SOURCE_WITH_CURRENT_GATE_READMISSION_EVIDENCE' for row in bindings.values()),
        'new_model_calls':0,'new_physical_calls':0,'new_usable_training_examples':0,
        'next_dispatch_requirements':'Complete fresh baseline9 for every new program/circuit context, exact feedback context fit, immutable collection/registry/interface freeze, unique resource-gated queue.'},indent=2)+'\n')
    (out/'initial_states_DRAFT.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in initial))
    print(json.dumps({'report':str(report),'programs':len(bindings),'contexts':len(initial),'current_gate_parent_source_programs':sum(row['selected_origin']['existing_parent_gate_evidence']['status']=='EXACT_PARENT_SOURCE_WITH_CURRENT_GATE_READMISSION_EVIDENCE' for row in bindings.values()),'new_usable_training_examples':0}))


if __name__=='__main__':main()
