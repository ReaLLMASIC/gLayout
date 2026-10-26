"""Prepare new real-program train contexts while remote telemetry is blocked.

This never freezes or dispatches. Token counts cover complete source, public
API and frozen physical contract, with no baseline feedback yet. A fit here is
only a lower bound; a fresh nine-point baseline and exact feedback preflight
are mandatory before any future teacher request.
"""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.student_interface import student_request
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget
from transformers import AutoTokenizer


def broker_packet(folder,needle,filename):
    for path in sorted((ROOT/'runs/development'/folder/'sessions').glob('*/'+filename)):
        request=json.loads(path.read_text())['request']
        if needle in request['task_packet']['task_id']:
            return request['task_packet'],str(path.relative_to(ROOT))
    raise ValueError('The actual complete family packet is unavailable: '+needle)


def main():
    action='gpt_action_teacher_service/20261019T025406200999Z'
    source='gpt_teacher_service/20261019T014702128868Z'
    files={'C01':next((ROOT/'runtime/train_collections/c01_enumeration_action_v1').glob('*request.json')),
        'C02':ROOT/'runtime/train_collections/c02_action_v1/request_example.json',
        'C05':next((ROOT/'runtime/train_collections/c05_natural_action_teacher_v1').glob('*request.json'))}
    templates={key:(json.loads(path.read_text())['request']['task_packet'],str(path.relative_to(ROOT))) for key,path in files.items()}
    templates['C07']=broker_packet(action,'c07_action_v1','teacher_request.json')
    templates['C08']=broker_packet(source,'c08_minimal_gpt_teacher_v1','request.json')
    assembly_api=templates['C05'][0]['documents']['assembly_api']
    programs=[json.loads(line) for line in (ROOT/'results/derived/train_program_inventory.jsonl').read_text().splitlines() if line.strip()]
    # All newly observed terminal programs are included before examining their
    # physical outcomes. The previously frozen context matrix is unchanged.
    selected=[row for row in programs if row.get('actual_local_proposal_inference_ids') and not row['actual_candidate_ids']]
    if not selected:raise ValueError('No new genuine broker programs are available')
    tokenizer=AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer',local_files_only=True,trust_remote_code=False)
    out=ROOT/'runtime/collection_preparation'/('local_trajectory_drafts_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
    contexts=[]
    for program in selected:
        if program['changed_modules_vs_original']!=['textbook_sharing/layout.py']:
            raise ValueError('This concrete preparation preserves one whole changed layout module; broaden scope prospectively if needed')
        for circuit,(template,template_path) in templates.items():
            packet=copy.deepcopy(template)
            packet['task_id']='draft_'+circuit.lower()+'_'+program['program_id']+'_trajectory'
            packet['allowed_paths']=['textbook_sharing/layout.py']
            # Remove only documents describing the earlier enum edit window.
            # Physical contract and all nine public configuration objects stay
            # byte-for-byte equal under JSON serialization to their template.
            packet['documents'].pop('enumeration_api',None)
            packet['documents'].pop('frozen_layout_consumer',None)
            packet['documents']['frozen_api']='Only the complete visible layout.py may be edited. The unchanged enumeration module and other APIs are frozen. Complete public RowSpec/AssemblyError/assemble declarations are provided. Generation mode is independent.'
            packet['documents']['assembly_api']=copy.deepcopy(assembly_api)
            packet['budget']['maximum_output_tokens']=1024
            packet['budget']['maximum_context_tokens']=8192
            base={'textbook_sharing/layout.py':program['complete_source']['textbook_sharing/layout.py']}
            request=student_request({'base_source':base,'visible_contract':packet,'visible_feedback':[]})
            if json.dumps(request['task_packet']['contract'])!=json.dumps(template['contract']) or json.dumps(request['task_packet']['visible_configurations'])!=json.dumps(template['visible_configurations']):
                raise ValueError('The circuit-specific physical contract or sizing domain changed')
            flight=prompt_token_budget(tokenizer,decision_prompt(request),{'max_new_tokens':1024,'max_context_tokens':8192})
            name=circuit.lower()+'_'+program['program_id'];path=out/(name+'_request_without_feedback.json')
            path.write_text(json.dumps({'draft_only':True,'request':request},indent=2,ensure_ascii=False)+'\n')
            contexts.append({'circuit_id':circuit,'program_id':program['program_id'],'status':'DRAFT_NOT_FROZEN_NOT_DISPATCHABLE',
                'request_path':str(path),'parent_lineage':program['parent_lineage'],'ancestry':program['origins'],
                'template_path':template_path,'exact_complete_source_and_contract_token_preflight':flight,
                'fresh_baseline_feedback_available':False,'fit_is_only_a_lower_bound':True,
                'fresh_baseline_points_required':9,'fresh_teacher_proposals_after_freeze':8,
                'physical_outcome':'UNKNOWN; not assumed to be a circuit or generation failure',
                'new_calls_made':0,'usable_training_samples':0})
    record={'status':'DRAFT_NOT_FROZEN_NOT_DISPATCHABLE','programs':len(selected),'circuit_contexts':len(contexts),
        'minimum_contexts_fit':sum(row['exact_complete_source_and_contract_token_preflight']['fits_with_full_output_reserve'] for row in contexts),
        'source_lineages':1,'model_calls':0,'physical_calls':0,'new_usable_examples':0,
        'requirements_before_dispatch':'Fresh baseline9/current trusted gate; exact complete source/API/actual feedback preflight; new immutable collection freeze; unique shared2/resource-gated coordinator only.',
        'contexts':contexts}
    (out/'preparation.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({key:record[key] for key in ['status','programs','circuit_contexts','minimum_contexts_fit','new_usable_examples']}|{'preparation':str(out/'preparation.json')}))


if __name__=='__main__':main()
