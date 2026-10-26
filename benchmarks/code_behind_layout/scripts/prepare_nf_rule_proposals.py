"""Draft all eight existing rules on both NF domains; zero model/physical calls."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.corpus_rule_proposer import RULE_IDS,BORROWED_FROM,propose
from src.train_span_proposer import compile_proposal,source_identity
from src.student_interface import student_request,canonical_action,encode_policy_action,PolicyBudgetError,CONTEXT_VERSION
from src.train_nf_span_bundle import with_readonly_entrypoint

EXPECTED=['diffusion_plan','gate_plan','combined_plan','reverse_device_order','gate_order',
          'reverse_port_track_order','reverse_devices_combined','reverse_ports_combined']


def read(p):return json.loads(Path(p).read_text())
def save(p,v):Path(p).write_text(json.dumps(v,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def prepare(setup,output,tokenizer_path,entrypoint_path):
    from transformers import AutoTokenizer
    if RULE_IDS!=EXPECTED:raise ValueError('Review changed rule syntax/options; never silently add a targeted NF option')
    setup=Path(setup).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    tokenizer=AutoTokenizer.from_pretrained(str(tokenizer_path),local_files_only=True,trust_remote_code=False)
    if tokenizer.eos_token_id!=151645:raise ValueError('Pinned Qwen EOS differs')
    shutil.copyfile(ROOT/'scripts/corpus_rule_proposer.py',output/'original_eight_rule_proposer.py')
    entrypoint=Path(entrypoint_path).read_bytes();(output/'actual_readonly_generator.py').write_bytes(entrypoint)
    records=[];terminal_ASTs=set();initial_ASTs=set()
    for cid in ['C02','C07']:
        source=setup/cid;state=read(source/'initial_state.json');collection=read(source/'collection.json')
        registry=read(source/'registry.json');base=state['base_source'];initial_ASTs.add(source_identity(base))
        if set(base)!={'textbook_sharing/layout.py','glayout/sharing/enumeration.py'}:raise ValueError('Keep both complete source modules')
        actual=source/'ordinary_request.json';request=read(actual if actual.exists() else source/'preview_ordinary_request.json')
        if request['task_packet']['visible_sources']!=base:raise ValueError('The rule source must match the whole immutable NF initial state')
        request=with_readonly_entrypoint(request,entrypoint.decode('utf-8'))
        folder=output/cid;folder.mkdir()
        for name,value in [('initial_state',state),('collection',collection),('registry',registry),('ordinary_context',request)]:save(folder/(name+'.json'),value)
        packet=request['task_packet'];visible={k:v for k,v in packet.items() if k!='visible_sources'}
        student=student_request({'base_source':base,'visible_contract':visible,'visible_feedback':request['visible_history']},CONTEXT_VERSION,16384)
        save(folder/'student_request.json',student)
        seen=set()
        for trial,rule in enumerate(EXPECTED,1):
            work=folder/rule;work.mkdir();wall=time.monotonic();cpu=time.process_time()
            row={'circuit_id':cid,'initial_state_id':state['initial_state_id'],'trial_id':trial,'rule_id':rule,
                'producer':'original_frozen_eight_rule_proposer','model':None,'seed':None,'status':'DRAFT_NOT_PHYSICALLY_EVALUATED'}
            try:
                text=propose(base['textbook_sharing/layout.py'],rule)
                (work/'proposed_layout.py').write_text(text)
                compiled=compile_proposal(base,{'edits':[{'path':'textbook_sharing/layout.py','old':base['textbook_sharing/layout.py'],'new':text}]})
                save(work/'compiled.json',compiled);identity=source_identity(compiled['candidate_source'])
                row.update(semantic_duplicate_within_domain=identity in seen,semantic_noop=identity==source_identity(base))
                seen.add(identity);terminal_ASTs.add(identity)
                action=canonical_action(compiled['patch'],student);(work/'ordinary_action.json').write_text(action+'\n')
                encoded=encode_policy_action(tokenizer,student,compiled['patch'],16384,1024)
                row['student_budget']={'fits':True,'prompt_tokens':encoded.prompt_tokens,'completion_tokens_including_EOS':encoded.completion_tokens,
                    'total_tokens':len(encoded.input_ids),'max_new_tokens':1024,'max_context_tokens':16384}
            except PolicyBudgetError as exc:row.update(status='DRAFT_STUDENT_BUDGET_REJECTED',student_budget={'fits':False,**exc.details})
            except (ValueError,KeyError,TypeError) as exc:row.update(status='DRAFT_RULE_PRECONDITION_OR_COMPILER_REJECTED',error=type(exc).__name__+': '+str(exc))
            row.update(generation_wall_seconds=time.monotonic()-wall,generation_CPU_seconds=time.process_time()-cpu,
                model_inferences=0,new_physical_calls=0,artifact_directory=str(work))
            save(work/'proposal.json',row);records.append(row)
    metadata={'status':'DRAFT_ALL_ORIGINAL_EIGHT_RULES_TWO_NF_DOMAINS_NO_MODEL_OR_PHYSICS',
        'prepared_at_utc':datetime.now(timezone.utc).isoformat(),'setup':str(setup),'records':records,'rule_ids':EXPECTED,
        'rule_source_snapshot':'original_eight_rule_proposer.py','borrowed_from':BORROWED_FROM,
        'existing_space':'diffusion_only/gate_only/combined; reverse device order; gate/net order; reverse port tracks; reverse-device+combined; reverse-port+combined. No new NF-targeted option.',
        'planned_proposals':16,'existing_NF_physical_contexts':2,'additional_task_contexts_beyond_NF_span':0,
        'initial_program_ASTs_in_batch':len(initial_ASTs),'new_initial_program_ASTs':0,'source_lineages_added':0,
        'unique_candidate_program_ASTs_across_domains':len(terminal_ASTs),'candidate_program_count_is_not_useful_context_count':True,
        'new_model_calls':0,'new_physical_calls':0,'admitted_training_examples':0,'formal_training_runs':0,
        'feedback_scope':'Complete development preview only unless actual fresh formal materialization was supplied. Actual formal18 proof/recount and a separate frozen acceptance are prerequisites to any future physics.',
        'pools':'Independent prospective rule pool, never automatically merged with GPT span16 or old rule labels; any later joint-pool freeze must disclose matching and exact-AST dedup.',
        'hypothesis':'At anchor nf8/8 combined sharing may compact the layout, whereas asymmetric rows/groups may introduce discrete legality/routing/RC/area effects. Every existing rule and all nine predeclared points remain; no preference or feasibility is prelabelled.',
        'null_result':'All16 may remain feasible with same-direction preferences or identical objectives; report zero Point/Family conflicts honestly.',
        'constraints':'Keep original nine N(z), terminal graphs, source capsule, PDK, bench, specifications, label tolerances and baseline meaning unchanged. No inverse fault injection or copied gold repair.'}
    metadata['readonly_entrypoint_document']={'file':'actual_readonly_generator.py','taken_from':str(Path(entrypoint_path).resolve()),
        'teacher_and_student_same_complete_bytes':True,'editable_paths_unchanged':True,
        'prospective_input_change':'Same faithful complete read-only entrypoint intended for the NF span teacher; no additional rule-specific source hint. Old span16 lacks this added document and is not a controlled producer-only comparison.'}
    save(output/'preparation.json',metadata)
    return {k:v for k,v in metadata.items() if k!='records'}|{'student_fit':sum(r.get('student_budget',{}).get('fits',False) for r in records),
        'semantic_noops':sum(r.get('semantic_noop',False) for r in records),'rule_or_compile_rejections':sum('error' in r for r in records),
        'per_domain_candidate_program_ASTs':{cid:sum(r['circuit_id']==cid and not r.get('semantic_duplicate_within_domain',True) for r in records) for cid in ['C02','C07']}}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['setup','output','tokenizer','entrypoint']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.setup,a.output,a.tokenizer,a.entrypoint),indent=2,allow_nan=False))
