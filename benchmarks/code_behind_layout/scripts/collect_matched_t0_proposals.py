"""Issue only the frozen96 matched T0 requests; no physical runs or training."""
import argparse
import ast
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from src.candidate_executor import apply_source_patch
from src.model_adapter import prompt_token_budget,validate_action
from src.local_model_adapter import decision_prompt


def read(path):return json.loads(Path(path).read_text())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def identity(source):
    result=[]
    for name,text in sorted(source.items()):
        try:key=('AST',ast.dump(ast.parse(text),include_attributes=False))
        except (SyntaxError,ValueError):key=('unparsed_exact_text',text)
        result.append((name,key))
    return tuple(result)


def run(args):
    service=args.plan.resolve().parent/'interface/service.py'
    spec=importlib.util.spec_from_file_location('_matched_T0_frozen_service',service);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    plan=module.load_plan(args.plan)
    if Path(__file__).read_bytes()!=(args.plan.parent/'interface/sampler.py').read_bytes():raise ValueError('Use the exact frozen matched T0 sampler')
    if args.validate_only:return {'status':'FROZEN_PLAN_VALIDATED_NO_REQUESTS','contexts':12,'planned_proposals':96,'new_calls':0}
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(read(ROOT/'configs/training/backbone_cache.json')['snapshot'],local_files_only=True,trust_remote_code=False)
    output=Path(plan['output_root']);output.mkdir(parents=True,exist_ok=False)
    save(output/'proposal_plan.json',plan);deadline=time.monotonic()+plan['maximum_dispatch_hours']*3600
    attempts=[];pending=list(plan['contexts']);seen={c['initial_state_id']:{identity(c['base_source']):'initial_source'} for c in pending}
    matrix=[{'initial_state_id':c['initial_state_id'],'seed':seed,'status':'NOT_RUN'} for c in pending for seed in plan['sampling']['seeds']]
    save(output/'matrix.json',matrix)
    while pending and time.monotonic()<deadline:
        ready=[c for c in pending if Path(c['materialized_task_packet']).is_file() and Path(c['materialized_visible_history']).is_file()]
        if not ready:time.sleep(5);continue
        context=ready[0];pending.remove(context);work=output/context['initial_state_id'];work.mkdir()
        request={'task_packet':read(context['materialized_task_packet']),'visible_history':read(context['materialized_visible_history'])}
        save(work/'matched_request.json',request)
        flight=prompt_token_budget(tokenizer,decision_prompt(request),{'max_context_tokens':16384,'max_new_tokens':1024});save(work/'context_size.json',flight)
        for seed in plan['sampling']['seeds']:
            row=next(r for r in matrix if r['initial_state_id']==context['initial_state_id'] and r['seed']==seed)
            if not flight['fits_with_full_output_reserve']:
                row.update(status='CONTEXT_OVERFLOW_NO_REQUEST',model_calls=0);continue
            if time.monotonic()>=deadline:break
            candidate=work/('seed_'+str(seed));candidate.mkdir()
            body={'variant':'T0','mode':plan['mode'],'sampling':{'temperature':.7,'top_p':.95,'seed':seed},'request':request}
            module.validate_request(body,plan);save(candidate/'request.json',body)
            began=time.monotonic();record={'initial_state_id':context['initial_state_id'],'seed':seed,'started_at_utc':datetime.now(timezone.utc).isoformat(),
                'model_calls_attempted':1,'physical_calls':0,'training_examples':0,'error':None}
            try:
                rpc=urllib.request.Request(plan['endpoint'],data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                try:
                    with urllib.request.urlopen(rpc,timeout=250) as response:raw=response.read().decode();http=response.status
                except urllib.error.HTTPError as exc:raw=exc.read().decode();http=exc.code
                (candidate/'response.json').write_text(raw+'\n');response=json.loads(raw);record.update(http_status=http,usage=response.get('usage'),model=response.get('model'),inference_id=response.get('inference_id'))
                if http!=200 or response.get('error'):raise ValueError(response.get('error') or 'Non-successful model response')
                if (response.get('native_tools')!=[] or response['model'].get('source_role')!='base_model_formal_train_action_proposals'
                    or response['model'].get('base_revision')!=module.REVISION or response['model'].get('adapter') is not None
                    or response['usage'].get('decoding_settings')!={'do_sample':True,'temperature':.7,'top_p':.95,'seed':seed}
                    or response['usage'].get('maximum_context_tokens')!=16384 or not response['usage'].get('eos_terminated')):
                    raise ValueError('Actual T0 identity, tool isolation, seed or full-context generation differs')
                if time.monotonic()-began>240:raise ValueError('Late proposal retained with actual usage; never applied')
                raw_action=response['raw_action_text'];action=validate_action(response['action'],request['task_packet'])
                if json.loads(raw_action)!=action or len(tokenizer(raw_action,add_special_tokens=False)['input_ids'])+1>1024:
                    raise ValueError('Exact raw ACTION differs or exceeds1024tokens including EOS')
                with tempfile.TemporaryDirectory(prefix='iscas-matched-t0-') as temporary:
                    for name,text in context['base_source'].items():
                        path=Path(temporary)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
                    apply_source_patch(temporary,action['patch'],list(context['base_source']))
                    source={name:(Path(temporary)/name).read_text() for name in context['base_source']}
                save(candidate/'candidate_source.json',source);key=identity(source)
                if key in seen[context['initial_state_id']]:record.update(status='SEMANTIC_DUPLICATE_PROPOSAL_ONLY',duplicate_of=seen[context['initial_state_id']][key])
                else:
                    seen[context['initial_state_id']][key]=seed
                    record.update(status='EXECUTABLE_PATCH_PROPOSAL_ONLY_PHYSICS_NOT_ESTABLISHED')
            except Exception as exc:
                record.update(status='PROPOSAL_OR_PATCH_FAILED_RAW_RETAINED',error=type(exc).__name__+': '+str(exc),patch_stderr=getattr(exc,'stderr',None))
            record.update(ended_at_utc=datetime.now(timezone.utc).isoformat(),wall_seconds=time.monotonic()-began)
            save(candidate/'attempt.json',record);attempts.append(record);row.update(status=record['status'],attempt_path=str(candidate/'attempt.json'))
            save(output/'attempts.json',attempts);save(output/'matrix.json',matrix)
    completion={'status':'COMPLETED_PROPOSAL_MATRIX' if all(r['status']!='NOT_RUN' for r in matrix) else 'DISPATCH_WINDOW_ENDED_WITH_NOT_RUN',
        'planned_proposals':96,'returned_attempts':len(attempts),'remaining_not_run':sum(r['status']=='NOT_RUN' for r in matrix),
        'distinct_task_contexts':12,'source_programs':6,'source_lineages':1,'new_physical_calls':0,'new_training_examples':0,
        'formal_trained_models':0,'same_contexts_as_GPT_not_additional_contexts':True,'ended_at_utc':datetime.now(timezone.utc).isoformat()}
    save(output/'matrix.json',matrix);save(output/'completion.json',completion)
    return completion


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True)
    g=p.add_mutually_exclusive_group(required=True);g.add_argument('--validate-only',action='store_true');g.add_argument('--execute',action='store_true');a=p.parse_args()
    print(json.dumps(run(a),indent=2))
