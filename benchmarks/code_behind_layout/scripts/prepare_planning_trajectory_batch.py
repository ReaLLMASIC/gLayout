"""Prepare a finite twelve-context real-program planning batch; issue no calls."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.candidate_executor import apply_source_patch
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget
from scripts.training_pilot_status import MODULES,program

# Five newly observed programs and the earliest actual C07 terminal program.
# Circuit assignments are fixed before examining any new physical outcome.
ASSIGNMENTS={'program_027':['C07','C05'],'program_038':['C05','C01'],'program_039':['C01','C02'],
             'program_040':['C01','C07'],'program_041':['C05','C02'],'program_042':['C05','C07']}
COLLECTIONS={'C01':'c01_planning_action_gpt_teacher_v1','C02':'c02_action_v1',
             'C05':'c05_natural_action_teacher_v1','C07':'c07_action_v1'}


def read(path):return json.loads(Path(path).read_text())


def main():
    from transformers import AutoTokenizer
    inventory={row['program_id']:row for row in map(json.loads,(ROOT/'results/derived/train_program_inventory.jsonl').read_text().splitlines())}
    original=next(row['complete_source'] for row in inventory.values() if not row['changed_modules_vs_original'])
    tokenizer=AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer',local_files_only=True,trust_remote_code=False)
    out=ROOT/'runtime/collection_preparation'/('planning_trajectory_batch_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
    templates={};registries={}
    for circuit,collection in COLLECTIONS.items():
        folder=ROOT/'runtime/train_collections'/collection;registries[circuit]=read(folder/'registry.json')
        if {p['parameters']['circuit']['circuit_id'] for p in registries[circuit]['configurations']}!={circuit} or len(registries[circuit]['configurations'])!=9:
            raise ValueError('Preserve the full applicable nine-point qualified circuit domain')
        candidates=list(folder.glob('*request.json'))+list(folder.glob('request_example.json'))
        request=read(candidates[0]);templates[circuit]=request['request']['task_packet']
    bindings={};contexts=[]
    for name,circuits in ASSIGNMENTS.items():
        row=inventory[name]
        if any(origin['kind']=='previously_frozen_initial_state' for origin in row['origins']):
            raise ValueError('This finite batch must not redispatch a previously frozen initial program')
        selected=None
        for origin in row['origins']:
            if origin['kind']!='actual_isolated_GPT_ACTION_proposal':continue
            request=read(origin['request_path']);invocation=read(origin['invocation_path']);response=invocation['response']
            packet=request['request']['task_packet'];base={**original,**packet['visible_sources']}
            if invocation['status']!='COMPLETED' or response['native_tools']!=[] or response['model']['source_role']!='isolated_GPT_formal_train_action_teacher':
                raise ValueError('Source origin lacks an actual isolated completed model proposal')
            with tempfile.TemporaryDirectory(prefix='iscas-new-planning-',dir='/private/tmp') as temp:
                for path,text in base.items():
                    target=Path(temp)/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
                apply_source_patch(temp,response['action']['patch'],packet['allowed_paths'])
                after={path:(Path(temp)/path).read_text() for path in MODULES}
            if after==row['complete_source']:
                selected={**origin,'base_source':base,'actual_patch':response['action']['patch'],
                    'complete_terminal_source_byte_equal_inventory':True,'raw_public_usage':response['usage']};break
        if selected is None:raise ValueError('No exact actual base plus original patch produces the selected initial source')
        evidence=out/'source_provenance'/name;evidence.mkdir(parents=True)
        shutil.copyfile(selected['request_path'],evidence/'teacher_request.json')
        shutil.copyfile(selected['invocation_path'],evidence/'teacher_invocation.json')
        selected['retained_request_relative_path']=str((evidence/'teacher_request.json').relative_to(out))
        selected['retained_invocation_relative_path']=str((evidence/'teacher_invocation.json').relative_to(out))
        bindings[name]=selected
        for circuit in circuits:
            packet=copy.deepcopy(templates[circuit]);physical=copy.deepcopy(packet['contract'])
            # Source-window prose is prospective. Preserve every actual
            # electrical field while matching this new two-module permission.
            packet['contract']['immutable']='Transistor graph, sizing, references, PDK, testbench and every library file outside the two complete editable modules are fixed.'
            packet['task_id']='draft_planning_'+circuit.lower()+'_'+name
            packet['visible_sources']=copy.deepcopy(row['complete_source']);packet['allowed_paths']=list(MODULES)
            packet['goal']='Produce one minimal executable ordinary ACTION patch for the complete layout and enumeration modules. Preserve circuit devices, sizing, ports, fixed physical contract and full APIs. Repair any actual code/API defect; among feasible solutions reduce area. Consider the real sharing-plan tradeoff between compact rows, separable groups and nf-dependent grouping across all nine visible configurations. Do not simply rewrite comments or choose one unconditional plan without inspecting its valid grouping assumptions.'
            packet['documents']['assembly_api']=copy.deepcopy(templates['C05']['documents']['assembly_api'])
            packet['documents']['enumeration_api']=copy.deepcopy(templates['C02']['documents']['enumeration_api'])
            packet['documents']['frozen_api']=copy.deepcopy(templates['C01']['documents']['frozen_api'])
            packet['documents']['planning_tradeoff_scope']='Both complete modules are editable; common PDK/PCell/routing/model/engine APIs remain frozen. Candidate diversity may arise from conservative repair, compact sharing or legal nf-dependent partitioning. These are proposal ideas, not asserted physical improvements or new scoring objectives.'
            packet['budget'].update(maximum_output_tokens=1024,maximum_context_tokens=16384)
            history=[{'observation':{'status':'SOURCE_PHYSICS_NOT_YET_MEASURED_FOR_THIS_NEW_PROGRAM_AND_CIRCUIT',
                'baseline_or_candidate_success_not_assumed':True,'next_collection_requires_actual_baseline9_and_exact_feedback_preflight':True}}]
            if {k:v for k,v in packet['contract'].items() if k!='immutable'}!={k:v for k,v in physical.items() if k!='immutable'}:
                raise ValueError('The teacher cannot change the applicable physical contract')
            request={'mode':'train_collection_action_gpt','trial_id':1,'request':{'task_packet':packet,'visible_history':history}}
            path=out/(circuit.lower()+'_'+name+'_request_DRAFT.json');path.write_text(json.dumps(request,indent=2,ensure_ascii=False)+'\n')
            flights={str(length):prompt_token_budget(tokenizer,decision_prompt(request['request']),{'max_context_tokens':length,'max_new_tokens':1024}) for length in (8192,16384)}
            contexts.append({'initial_state_id':'planning_'+circuit.lower()+'_'+name,'program_id':name,'circuit_id':circuit,
                'source_lineage':row['parent_lineage'],'request_path':str(path),'registry_path':str(ROOT/'runtime/train_collections'/COLLECTIONS[circuit]/'registry.json'),
                'full_source':copy.deepcopy(row['complete_source']),'ancestry':selected,'context_preflight':flights,
                'physical_outcomes':'UNKNOWN','new_usable_samples':0,'fresh_baseline_points_required':9,'fresh_proposals':8})
    record={'status':'DRAFT_FIXED_BATCH_NO_MODEL_OR_PHYSICAL_CALLS','programs':6,'initial_context_count':12,'source_lineages':1,
        'planned_proposals':96,'sampling':{'model':'gpt-6.1-sol','reasoning_effort':'high','seed':None,'fresh_ephemeral_sessions':True,
            'native_tools':False,'proposal_format':'ordinary_ACTION_JSON','max_new_tokens':1024,'max_context_tokens':16384,'timeout_seconds':240,'global_shared_slots':2},
        'physical_resource_plan':{'maximum_new_workers':2,'CPUs_per_worker':2,'generation_timeout_seconds':240,'evaluator_timeout_seconds':720,
            'maximum_baseline_points':108,'maximum_candidate_points':864,'actual_resource_gate':'busy+newCPUs<=24;RAM<=190GiB;diskfree>=4GiB'},
        'lower_bound_fits_8192':sum(c['context_preflight']['8192']['fits_with_full_output_reserve'] for c in contexts),
        'lower_bound_fits_16384':sum(c['context_preflight']['16384']['fits_with_full_output_reserve'] for c in contexts),
        'context_fit_includes_actual_new_baseline_feedback':False,
        'before_dispatch':['Fresh baseline9/current gate per new program/circuit; preserve failures and actual cost',
            'Recount with all actual feedback, full two-module source and unchanged contract; reject overflow, never truncate',
            'Prospectively freeze complete requests/interface/labels/references and common canonical student context',
            'Use independent16k teacher implementation and shared2 transport at a coordinated empty boundary; do not change old8k brokers or exceed2actualslots',
            'Unique remote queue owner only; local proposal dispatcher must not duplicate a frozen in-flight state'],
        'model_calls':0,'physical_calls':0,'new_usable_samples':0,
        '1000_target_status':'This batch can add at most12 useful task contexts if every one succeeds, not96 SFT examples; program/source ancestry and terminal duplicates remain separately counted.',
        'contexts':contexts}
    (out/'plan.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:record[k] for k in ['status','programs','initial_context_count','planned_proposals','lower_bound_fits_8192','lower_bound_fits_16384','model_calls','physical_calls']}|{'plan':str(out/'plan.json')}))


if __name__=='__main__':main()
