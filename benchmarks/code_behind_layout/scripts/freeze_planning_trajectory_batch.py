"""Prospectively freeze the fixed six-program/twelve-context16k planning batch."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.e4_methods import validate_context_calibration
from src.local_model_adapter import decision_prompt
from src.model_adapter import ACTION_SCHEMA,prompt_token_budget
from src.student_interface import CONTEXT_VERSION,interface_definition
from scripts.prepare_planning_trajectory_batch import ASSIGNMENTS,COLLECTIONS
from scripts.run_frozen_training_collection import load_definition


def read(path):return json.loads(Path(path).read_text())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def freeze(plan_path,calibration_path):
    plan=read(plan_path);folder=Path(plan_path).resolve().parent
    if (plan['status']!='DRAFT_FIXED_BATCH_NO_MODEL_OR_PHYSICAL_CALLS' or plan['programs']!=6
        or len(plan['contexts'])!=12 or plan['planned_proposals']!=96 or plan['model_calls'] or plan['physical_calls']
        or plan.get('sampling',{}).get('max_context_tokens')!=16384
        or plan.get('sampling',{}).get('max_new_tokens')!=1024
        or any(not c.get('context_preflight',{}).get('16384',{}).get('fits_with_full_output_reserve') for c in plan['contexts'])
        or {(c['program_id'],c['circuit_id']) for c in plan['contexts']}!={(p,c) for p,cs in ASSIGNMENTS.items() for c in cs}):
        raise ValueError('Only the approved fixed six-real-program/twelve-context batch may freeze')
    definition=interface_definition(CONTEXT_VERSION,16384);validate_context_calibration(calibration_path,definition)
    bases={};controls={}
    for circuit,name in COLLECTIONS.items():
        manifest,registry,_,files=load_definition(ROOT/'runtime/train_collections'/name/'collection.json')
        prior=manifest.get('gold_controls') or read(Path(manifest['output_root'])/'gold_controls.json')
        if len(prior)!=9:raise ValueError('Every new state needs all nine existing immutable original-source controls')
        bases[circuit]=(manifest,registry,files);controls[circuit]=prior
    from transformers import AutoTokenizer
    cache=read(ROOT/'configs/training/backbone_cache.json');tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
    outputs=[]
    for circuit in COLLECTIONS:
        selected=[c for c in plan['contexts'] if c['circuit_id']==circuit];base,registry,files=bases[circuit]
        identifier=circuit.lower()+'_planning_trajectories_context_v2';output=ROOT/'runtime/train_collections'/identifier
        output.mkdir();interface=output/'interface';(interface/'src').mkdir(parents=True)
        for name in ['model_adapter.py','local_model_adapter.py','policy_state.py','student_interface.py']:
            shutil.copyfile(ROOT/'src'/name,interface/'src'/name)
        (interface/'src/__init__.py').write_text('')
        shutil.copyfile(ROOT/'scripts/collect_planning_trajectories.py',interface/'collector.py')
        shutil.copyfile(ROOT/'scripts/corpus_gpt_planning_teacher_service.py',interface/'broker.py')
        save(interface/'action_schema.json',ACTION_SCHEMA)
        template=read(folder/Path(selected[0]['request_path']).name)['request']['task_packet']
        save(interface/'teacher_packet_template.json',{k:template[k] for k in ['goal','documents','contract']})
        states=[];flights=[]
        for context in selected:
            ancestry=context['ancestry'];origin_request=read(folder/ancestry['retained_request_relative_path']);origin_result=read(folder/ancestry['retained_invocation_relative_path'])
            if (origin_result['status']!='COMPLETED' or origin_result['response']['native_tools']!=[]
                or origin_result['response']['model']['source_role']!='isolated_GPT_formal_train_action_teacher'):
                raise ValueError('Initial source must retain its actual isolated model provenance')
            before={**{n:(Path(base['source_pack'])/n).read_text() for n in context['full_source']},**origin_request['request']['task_packet']['visible_sources']}
            from src.training import bind_candidate_edit
            bind_candidate_edit({'base_source':before,'candidate_source':context['full_source'],
                'candidate_patch':origin_result['response']['action']['patch']},list(context['full_source']))
            state={'initial_state_id':context['initial_state_id'],'task_id':registry['configurations'][0]['contract']['task_id'],
                'parent_lineage':context['source_lineage'],'origin':'natural','editable_paths':list(context['full_source']),
                'base_source':context['full_source'],'ancestry':{**ancestry,'program_id':context['program_id'],
                    'not_manually_injected_or_reverse_patched':True,'actual_child_physics_not_inferred_from_parent':True}}
            states.append(state);request=read(folder/Path(context['request_path']).name)
            request['request']['task_packet'].update(task_id=identifier+'__'+state['initial_state_id'])
            flight=prompt_token_budget(tokenizer,decision_prompt(request['request']),{'max_context_tokens':16384,'max_new_tokens':1024})
            if not flight['fits_with_full_output_reserve']:raise ValueError('The full predeclared source/API/contract does not fit16k')
            flights.append({'initial_state_id':state['initial_state_id'],**flight,'actual_new_baseline_feedback_included':False})
            save(output/(state['initial_state_id']+'_request_without_feedback.json'),request)
            evidence=output/'source_provenance'/context['program_id'];evidence.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(folder/ancestry['retained_request_relative_path'],evidence/'teacher_request.json')
            shutil.copyfile(folder/ancestry['retained_invocation_relative_path'],evidence/'teacher_invocation.json')
        save(output/'registry.json',registry);shutil.copyfile(base['label_rule_path'],output/'label_rule.json')
        (output/'initial_states.jsonl').write_text(''.join(json.dumps(s,ensure_ascii=False)+'\n' for s in states))
        shutil.copyfile(calibration_path,output/'gpu_context_calibration.json')
        save(output/'teacher_context_preflight.json',{'scope':'complete source/API/contract lower-bound only; actual fresh baseline feedback recounted before inference',
            'requests':flights,'new_model_calls':0,'new_physical_calls':0,'all_requests_fit':True})
        manifest={**base,'collection_id':identifier,'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
            'registry_path':str(output/'registry.json'),'label_rule_path':str(output/'label_rule.json'),
            'initial_states_path':str(output/'initial_states.jsonl'),'output_root':str(ROOT/'runs/train_collection'/identifier),
            'evidence_root':str(ROOT/'runs/train_collection'/identifier),'teacher_interface_path':str(interface),
            'teacher_interface_version':'ordinary_action_teacher_context_v2','frozen_collector_entrypoint':'interface/collector.py',
            'teacher_packet_template':str(interface/'teacher_packet_template.json'),'teacher_context_preflight':str(output/'teacher_context_preflight.json'),
            'context_calibration':str(output/'gpu_context_calibration.json'),
            'sampling':{**plan['sampling'],'backend':'isolated_gpt_cli','mode':'train_collection_action_gpt','trials':list(range(1,9)),'proposal_workers':2},
            'student_preselection':{'student_interface_version':CONTEXT_VERSION,'max_new_tokens':1024,'max_context_tokens':16384,'stage':'before_physics'},
            'physical':{**base['physical'],'workers':1},'gold_controls':controls[circuit],
            'batch_dispatch':{'batch_id':'planning_trajectories_context_v2','maximum_simultaneous_batch_collectors':2,'workers_per_collection':1},
            'budget':{**base['budget'],'initial_batch_initial_states':len(states)},'budget_tokenizer_revision':cache['revision'],
            'transport':{'remote_endpoint':'http://127.0.0.1:8116/context16384','local_upstream':'127.0.0.1:8118',
                'mechanism':'Existing reverse loopback and one explicitly added shared2 transport route; old8k brokers and body bytes unchanged'},
            'isolation':{'fresh_ephemeral_session_per_trial':True,'native_tools':False,'global_teacher_slots':2},
            'deduplication':{'method':'exact_ast_dump','include_attributes':False,'numeric_normalization':False,'all_generation_costs_retained':True},
            'source_program_counting':'Six actual programs across twelve tasks in one compiler lineage; this circuit subset is not twelve sources or96SFT states.',
            'admission':'Fresh baseline9 per state, full actual generation diagnostics, exact16k recount before eight new GPT proposals, strict1024ACTION preselection, all nine physical candidate points and current trusted re-admission. No old outcome relabelled.',
            'output_budget_scope':'Exact raw and canonical ordinary ACTION plus EOS <=1024; source/API/physical context not truncated; bad diffs never repaired.',
            'formal_training_runs':0,'main_benchmark_protocol_status':'draft'}
        manifest.pop('teacher_instruction_version',None);manifest.pop('teacher_public_api_document',None);manifest.pop('teacher_packet_version',None)
        save(output/'collection.json',manifest)
        names=sorted(str(p.relative_to(output)) for p in output.rglob('*') if p.is_file())
        save(output/'freeze_identity.json',{n:hashlib.sha256((output/n).read_bytes()).hexdigest() for n in names})
        load_definition(output/'collection.json')
        for path in sorted(output.rglob('*'),reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
        output.chmod(0o555);outputs.append({'circuit_id':circuit,'collection':str(output/'collection.json'),'states':len(states),'planned_proposals':len(states)*8})
    return {'status':'FROZEN_PROSPECTIVE_TRAIN_COLLECTIONS_NOT_DISPATCHED','programs':6,'contexts':12,'planned_proposals':96,
        'collections':outputs,'model_calls':0,'physical_calls':0,'usable_samples':0,'global_actual_teacher_slots':2,
        'maximum_simultaneous_new_physical_workers':2,'workers_per_collection':1,
        'requires_unique_queue_and_idle_transport_route_deployment':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--calibration',type=Path,required=True);a=p.parse_args()
    print(json.dumps(freeze(a.plan,a.calibration),indent=2))
