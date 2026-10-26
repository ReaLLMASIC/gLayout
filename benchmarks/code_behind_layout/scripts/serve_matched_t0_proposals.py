"""Separate16k T0 proposal-only service on8119; never alter or stop8114."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time
import uuid

# The frozen entrypoint lives under runtime/.../interface. Its coordinator
# launches it from this project's root, exactly like the frozen collector.
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from src.e4_methods import REVISION,validate_context_calibration
from src.local_model_adapter import decision_prompt
from src.model_adapter import ACTION_SCHEMA,validate_action
from src.student_interface import CONTEXT_VERSION,interface_definition

MODE='matched_train_action_t0'
SEEDS=(101,241,379,503,617,743,857,971)


def read(path):return json.loads(Path(path).read_text())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def load_plan(path):
    path=Path(path).resolve();plan=read(path)
    if (plan.get('status')!='frozen' or plan.get('role')!='matched_T0_proposals_only'
        or plan.get('mode')!=MODE or plan.get('sampling')!={'temperature':.7,'top_p':.95,'seeds':list(SEEDS)}
        or plan.get('max_context_tokens')!=16384 or plan.get('max_new_tokens')!=1024
        or plan.get('timeout_seconds')!=240 or len(plan.get('contexts',[]))!=12
        or len({c['initial_state_id'] for c in plan['contexts']})!=12):
        raise ValueError('Use the independently frozen matched12context/eight-seed16k T0 proposal plan')
    identity=read(path.parent/'freeze_identity.json')
    for name,digest in identity.items():
        target=(path.parent/name).resolve();target.relative_to(path.parent)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Frozen T0 proposal artifact changed: '+name)
    if 'proposal_plan.json' not in identity or 'interface/service.py' not in identity:
        raise ValueError('The exact plan and dedicated service must be frozen')
    if Path(__file__).read_bytes()!=(path.parent/'interface/service.py').read_bytes():
        raise ValueError('Launch the exact independently frozen T0 proposal service')
    for name in ('model_adapter.py','local_model_adapter.py','policy_state.py'):
        if (ROOT/'src'/name).read_bytes()!=(path.parent/'interface/src'/name).read_bytes():
            raise ValueError('The frozen ordinary proposal prompt interface changed: '+name)
    validate_context_calibration(plan['context_calibration'],interface_definition(CONTEXT_VERSION,16384))
    return plan


def validate_request(body,plan):
    if (not isinstance(body,dict) or set(body)!={'variant','mode','sampling','request'}
        or body['variant']!='T0' or body['mode']!=MODE):
        raise ValueError('This endpoint accepts only matched T0 ordinary-ACTION proposals')
    sampling=body['sampling']
    if (not isinstance(sampling,dict) or set(sampling)!={'temperature','top_p','seed'}
        or sampling['temperature']!=.7 or sampling['top_p']!=.95
        or type(sampling['seed']) is not int or sampling['seed'] not in SEEDS):
        raise ValueError('Use one of the eight frozen real seeds and matched sampling settings')
    prompt=decision_prompt(body['request']);packet=body['request']['task_packet']
    matches=[c for c in plan['contexts'] if c['task_id']==packet['task_id']]
    if len(matches)!=1 or packet['visible_sources']!=matches[0]['base_source']:
        raise ValueError('The proposal is outside the twelve exact predeclared source contexts')
    matched={'task_packet':read(matches[0]['materialized_task_packet']),
             'visible_history':read(matches[0]['materialized_visible_history'])}
    if body['request']!=matched:raise ValueError('T0 must receive the exact materialized GPT packet and actual baseline history')
    if (packet['budget'].get('maximum_context_tokens')!=16384 or packet['budget'].get('maximum_output_tokens')!=1024
        or set(packet['allowed_paths'])!=set(matches[0]['base_source'])):
        raise ValueError('The complete ordinary source window or explicit16k/1024budget differs')
    return prompt,{'do_sample':True,**sampling}


def serve(args):
    from http.server import BaseHTTPRequestHandler,HTTPServer
    plan=load_plan(args.plan)
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    metadata={'status':'LOADING','phase':'matched_train_proposals_only','pid':os.getpid(),
        'argv':[sys.executable]+sys.argv,'port':8119,'bind':'127.0.0.1','source_role':'base_model_formal_train_action_proposals',
        'plan':str(args.plan.resolve()),'mode':MODE,'variant':'T0','native_tools':[],
        'max_context_tokens':16384,'max_new_tokens':1024,'timeout_seconds':240,
        'actual_model_count':1,'formal_trained_models':0,'training_examples':0,
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'successful_requests':0,'failed_requests':0}
    save(out/'service.json',metadata);stopped=False;lifetime=time.monotonic()
    try:
        os.environ.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        affinity=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,affinity[:4])
        metadata['environment_overrides']={k:os.environ[k] for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','TOKENIZERS_PARALLELISM','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE')}
        import torch
        from peft import prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM,AutoTokenizer,BitsAndBytesConfig,StoppingCriteria,StoppingCriteriaList
        import xgrammar
        from xgrammar.contrib.hf import LogitsProcessor
        torch.set_num_threads(2);torch.set_num_interop_threads(2)
        if not torch.cuda.is_available() or torch.cuda.device_count()!=1:raise RuntimeError('One available GPU required')
        if torch.cuda.mem_get_info()[0]<65*1024**3:raise RuntimeError('GPU occupied; coordinator must safely drain/pause its own8114 first')
        cache=read(ROOT/'configs/training/backbone_cache.json');snapshot=Path(cache['snapshot'])
        if cache['revision']!=REVISION or snapshot.name!=REVISION:raise ValueError('Use the actual pinned32B snapshot')
        tokenizer=AutoTokenizer.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False);tokenizer.pad_token=tokenizer.eos_token
        torch.manual_seed(41);torch.cuda.manual_seed_all(41);torch.cuda.reset_peak_memory_stats();began=time.monotonic()
        model=AutoModelForCausalLM.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16),
            dtype=torch.bfloat16,device_map={'':0},attn_implementation='sdpa')
        model=prepare_model_for_kbit_training(model,use_gradient_checkpointing=False);model.eval();model.config.use_cache=True
        for parameter in model.parameters():parameter.requires_grad_(False)
        compiler=xgrammar.GrammarCompiler(xgrammar.TokenizerInfo.from_huggingface(tokenizer,vocab_size=model.config.vocab_size),max_threads=2)
        compiled=compiler.compile_json_schema(ACTION_SCHEMA);torch.cuda.synchronize()
        metadata.update(status='LOADED_NOT_LISTENING',base_model=cache['repo_id'],base_revision=REVISION,tokenizer_revision=REVISION,
            load_seconds=time.monotonic()-began,load_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            settings={'quantization':'NF4','double_quantization':True,'compute_dtype':'bfloat16','attention_backend':'sdpa',
                'nonquantized_preparation':'prepare_model_for_kbit_training(use_gradient_checkpointing=False)',
                'max_new_tokens':1024,'maximum_context_tokens':16384,'use_cache':True,'json_constraint':'xgrammar shared ACTION_SCHEMA'},
            versions={name:importlib.metadata.version(name) for name in ('torch','transformers','peft','bitsandbytes','xgrammar')})
        save(out/'service.json',metadata)
        def stop(*unused):
            nonlocal stopped
            stopped=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        class WallStop(StoppingCriteria):
            def __init__(self,deadline):self.deadline=deadline
            def __call__(self,*unused,**kwargs):return time.monotonic()>=self.deadline
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*unused):pass
            def respond(self,status,value):
                payload=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers()
                try:self.wfile.write(payload)
                except (BrokenPipeError,ConnectionResetError):pass
            def do_GET(self):
                if self.path!='/health':self.respond(404,{'error':'unknown endpoint'});return
                self.respond(200,metadata)
            def do_POST(self):
                if self.path!='/decision':self.respond(404,{'error':'unknown endpoint'});return
                identifier=str(uuid.uuid4());work=out/'requests'/identifier;work.mkdir(parents=True)
                t=time.monotonic();before=resource.getrusage(resource.RUSAGE_SELF);usage={};response={};status=422
                record={'inference_id':identifier,'started_at_utc':datetime.now(timezone.utc).isoformat()}
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2*1024**2:raise ValueError('Unexpected request size')
                    body=json.loads(self.rfile.read(length));save(work/'request.json',body)
                    prompt,sampling=validate_request(body,plan)
                    encoding=tokenizer.apply_chat_template([{'role':'user','content':prompt}],tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt')
                    inputs={k:v.to('cuda:0') for k,v in encoding.items() if k in ('input_ids','attention_mask')};count=inputs['input_ids'].shape[-1]
                    if count+1024>16384:raise ValueError('Complete context does not fit16k; no truncation or generation')
                    torch.manual_seed(sampling['seed']);torch.cuda.manual_seed_all(sampling['seed']);torch.cuda.reset_peak_memory_stats();torch.cuda.synchronize()
                    start=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True);generation=time.monotonic()
                    with torch.inference_mode():
                        start.record();result=model.generate(**inputs,max_new_tokens=1024,**{k:v for k,v in sampling.items() if k!='seed'},
                            use_cache=True,pad_token_id=tokenizer.pad_token_id,eos_token_id=tokenizer.eos_token_id,
                            logits_processor=[LogitsProcessor(compiled)],stopping_criteria=StoppingCriteriaList([WallStop(t+240)]));end.record()
                    torch.cuda.synchronize();tokens=result[0,count:];text=tokenizer.decode(tokens,skip_special_tokens=True);(work/'completion.txt').write_text(text)
                    after=resource.getrusage(resource.RUSAGE_SELF);eos=bool(len(tokens) and int(tokens[-1])==tokenizer.eos_token_id)
                    usage={'input_tokens':int(count),'output_tokens':len(tokens),'eos_terminated':eos,'decoding_settings':sampling,
                        'request_mode':MODE,'output_format':'ordinary_action_json','max_new_tokens':1024,'maximum_context_tokens':16384,
                        'generation_wall_seconds':time.monotonic()-generation,'cuda_stream_elapsed_seconds':start.elapsed_time(end)/1000,
                        'server_wall_seconds':time.monotonic()-t,'server_user_cpu_seconds':after.ru_utime-before.ru_utime,
                        'server_system_cpu_seconds':after.ru_stime-before.ru_stime,'peak_allocated_bytes':torch.cuda.max_memory_allocated(),
                        'peak_reserved_bytes':torch.cuda.max_memory_reserved(),'gpu_devices_allocated':1}
                    if not eos or time.monotonic()-t>240:raise ValueError('Incomplete or late ACTION; exact raw output and actual cost retained, never applied')
                    action=validate_action(json.loads(text),body['request']['task_packet']);status=200
                    response.update(action=action,raw_action_text=text);metadata['successful_requests']+=1
                except Exception as exc:
                    response['error']=type(exc).__name__+': '+str(exc);metadata['failed_requests']+=1
                finally:
                    response.update(inference_id=identifier,usage=usage,native_tools=[],model={'variant':'T0','base_model':cache['repo_id'],
                        'base_revision':REVISION,'tokenizer_revision':REVISION,'source_role':metadata['source_role'],'adapter':None,
                        'settings':{**metadata['settings'],**(sampling if 'sampling' in locals() else {})}})
                    record.update(status='COMPLETED' if status==200 else 'FAILED',response=response,ended_at_utc=datetime.now(timezone.utc).isoformat(),wall_seconds=time.monotonic()-t)
                    save(work/'invocation.json',record);save(out/'service.json',metadata);self.respond(status,response)
        server=HTTPServer(('127.0.0.1',8119),Handler);server.timeout=.5
        metadata.update(status='READY',ready_at_utc=datetime.now(timezone.utc).isoformat());save(out/'service.json',metadata);print(json.dumps(metadata),flush=True)
        while not stopped:server.handle_request()
        server.server_close();metadata.update(status='STOPPED',stopped_at_utc=datetime.now(timezone.utc).isoformat())
    except Exception as exc:metadata.update(status='FAILED',error=type(exc).__name__+': '+str(exc));raise
    finally:metadata['service_wall_seconds']=time.monotonic()-lifetime;save(out/'service.json',metadata)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path);p.add_argument('--validate-only',action='store_true');a=p.parse_args()
    if a.validate_only:
        plan=load_plan(a.plan);print(json.dumps({'status':'FROZEN_PLAN_VALIDATED_NO_GPU_LOAD','contexts':len(plan['contexts']),'new_calls':0}))
    else:
        if a.output is None:p.error('A new output directory is required to serve')
        serve(a)
