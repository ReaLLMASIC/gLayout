#!/usr/bin/env python3
"""Independent 8117 ordinary-action service for actual frozen E4 methods only.

No teacher modes, engineering adapters, file operations or native model tools.
The existing 8114 service and byte-frozen collection programs are untouched.
"""
import argparse
from contextlib import nullcontext
from datetime import datetime,timezone
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.e4_methods import METHODS,REVISION,SEEDS,file_digest,frozen_serving_method
from src.local_model_adapter import decision_prompt
from src.model_adapter import ACTION_SCHEMA,check_utc_budget,remaining_utc_budget,validate_action

PORT=8117
INFERENCE_SEED=41
QUANTIZATION={'load_in_4bit':True,'bnb_4bit_quant_type':'nf4','bnb_4bit_use_double_quant':True,'compute_dtype':'bfloat16'}


def validate_methods(path):
    """Validate all real method references without importing torch or loading GPU."""
    artifact=json.loads(Path(path).read_text())
    if (set(artifact.get('variants',{}))!=set(('T0',)+METHODS) or artifact.get('training_seeds')!=list(SEEDS)
        or artifact.get('quantization')!=QUANTIZATION):
        raise ValueError('Formal service requires all five matched variants, three seeds, and fixed NF4/bf16')
    t0=artifact['variants']['T0']
    if (t0.get('actual_model_count')!=1 or t0.get('actual_training_seeds')!=[]
        or t0.get('matched_evaluation_seed_slots')!=list(SEEDS)):
        raise ValueError('T0 is one untrained backbone with three matched evaluation slots')
    for method in METHODS:
        if set(artifact['variants'][method].get('seeds',{}))!={str(s) for s in SEEDS}:
            raise ValueError('A formal trained variant lacks its actual three selected adapters')
    resolved={(method,seed):frozen_serving_method(path,method,seed) for method in ('T0',)+METHODS for seed in SEEDS}
    common=resolved['T0',SEEDS[0]]
    if any(value['student_interface']!=common['student_interface'] or value['backbone_snapshot']!=common['backbone_snapshot']
           for value in resolved.values()):raise ValueError('Variants do not share the frozen base/context interface')
    return artifact,resolved


def validate_request(body,definition):
    if not isinstance(body,dict) or set(body)!={'variant','training_seed','request'}:
        raise ValueError('Expected only variant, training_seed and ordinary request')
    if body['variant'] not in ('T0',)+METHODS or type(body['training_seed']) is not int or body['training_seed'] not in SEEDS:
        raise ValueError('Unknown frozen E4 variant or actual training seed')
    prompt=decision_prompt(body['request']);packet=body['request']['task_packet'];budget=packet['budget']
    if (budget.get('maximum_output_tokens')!=1024 or budget.get('maximum_context_tokens')!=definition['max_context_tokens']):
        raise ValueError('Packet must disclose the exact frozen context and1024ordinary output budget')
    if (not isinstance(packet['visible_sources'],dict) or not packet['visible_sources']
        or not all(isinstance(source,str) for source in packet['visible_sources'].values())
        or not set(packet['allowed_paths']).issubset(packet['visible_sources'])):
        raise ValueError('Supply every complete editable source in the ordinary visible packet')
    check_utc_budget(packet)
    return prompt


class AdapterBank:
    """One common prepared backbone and at most one resident formal adapter."""
    def __init__(self,model,methods_path,load_first_adapter,manifest_sha256):
        self.model=model;self.methods_path=Path(methods_path);self.load_first_adapter=load_first_adapter
        self.manifest_sha256=manifest_sha256
        self.peft=False;self.resident=None;self.resident_identity=None;self.failed=False

    def activate(self,variant,seed):
        if self.failed:raise RuntimeError('A failed adapter switch quarantined this service instance')
        try:
            if file_digest(self.methods_path)!=self.manifest_sha256:raise ValueError('The active methods manifest changed after service start')
            # Resident GPU weights stay fixed even if a disk file changes. Check
            # the large file again only before an actual load, not each decision.
            identity=self.resident_identity if variant!='T0' and self.resident==(variant,seed) else frozen_serving_method(self.methods_path,variant,seed)
            if variant!='T0' and self.resident!=(variant,seed):
                if self.peft:
                    self.model.delete_adapter('policy')
                    self.model.load_adapter(identity['adapter_path'],adapter_name='policy',is_trainable=False)
                else:
                    self.model=self.load_first_adapter(self.model,identity['adapter_path'],adapter_name='policy',is_trainable=False)
                    self.peft=True
                self.resident=(variant,seed)
                self.resident_identity=identity
            if self.peft and self.resident is not None:self.model.set_adapter('policy')
            self.model.eval()
            for parameter in self.model.parameters():parameter.requires_grad_(False)
            self.model.config.use_cache=True
        except Exception:
            self.failed=True;raise
        return identity

    def context(self,variant):
        return self.model.disable_adapter() if variant=='T0' and self.peft else nullcontext()


def serve(args):
    from http.server import BaseHTTPRequestHandler,HTTPServer
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    metadata={'phase':'frozen_E4_policy_service','status':'VALIDATING_METHODS','pid':os.getpid(),
        'argv':[sys.executable]+sys.argv,'methods_manifest':str(args.methods.resolve()),'port':PORT,'bind':'127.0.0.1',
        'native_tools':[],'successful_requests':0,'failed_requests':0,'started_at_utc':datetime.now(timezone.utc).isoformat()}
    lifetime=time.monotonic();stopped=False
    def save():(out/'service.json').write_text(json.dumps(metadata,indent=2,allow_nan=False)+'\n')
    (out/'pid').write_text(str(os.getpid())+'\n');save()
    try:
        t=time.monotonic();artifact,resolved=validate_methods(args.methods)
        metadata.update(methods_manifest_sha256=file_digest(args.methods),adapter_binding_wall_seconds=time.monotonic()-t,
            student_interface=artifact['student_interface'],status='LOADING')
        affinity=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,affinity[:4])
        os.environ.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false',
                          HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        metadata['environment_overrides']={key:os.environ[key] for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS',
            'TOKENIZERS_PARALLELISM','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE']};save()
        import torch
        from peft import PeftModel,prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM,AutoTokenizer,BitsAndBytesConfig,StoppingCriteria,StoppingCriteriaList
        import xgrammar
        from xgrammar.contrib.hf import LogitsProcessor
        torch.set_num_threads(2);torch.set_num_interop_threads(2)
        if not torch.cuda.is_available() or torch.cuda.device_count()!=1:raise RuntimeError('One available GPU required; service does not stop other jobs')
        if torch.cuda.mem_get_info()[0]<65*1024**3:raise RuntimeError('GPU not available; coordinator must drain and safely pause its own8114first')
        torch.manual_seed(INFERENCE_SEED);torch.cuda.manual_seed_all(INFERENCE_SEED)
        snapshot=Path(artifact['backbone_snapshot'])
        if snapshot.name!=REVISION or not snapshot.is_dir():raise ValueError('Pinned actual32B backbone snapshot is absent')
        tokenizer=AutoTokenizer.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False)
        tokenizer.pad_token=tokenizer.eos_token
        torch.cuda.reset_peak_memory_stats();t=time.monotonic()
        model=AutoModelForCausalLM.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16),dtype=torch.bfloat16,device_map={'':0},attn_implementation='sdpa')
        model=prepare_model_for_kbit_training(model,use_gradient_checkpointing=False)
        bank=AdapterBank(model,args.methods,PeftModel.from_pretrained,metadata['methods_manifest_sha256'])
        bank.activate(args.initial_variant,args.training_seed)
        compiler=xgrammar.GrammarCompiler(xgrammar.TokenizerInfo.from_huggingface(tokenizer,vocab_size=bank.model.config.vocab_size),max_threads=2)
        compiled=compiler.compile_json_schema(ACTION_SCHEMA)
        torch.cuda.synchronize()
        settings={'quantization':'NF4','double_quantization':True,'compute_dtype':'bfloat16','attention_backend':'sdpa',
            'nonquantized_preparation':'prepare_model_for_kbit_training(use_gradient_checkpointing=False)',
            'nonquantized_inference_autocast':'bfloat16',
            'do_sample':False,'seed':INFERENCE_SEED,'max_new_tokens':1024,
            'maximum_context_tokens':artifact['student_interface']['max_context_tokens'],'use_cache':True,
            'visible_history_policy':artifact['student_interface'].get('history_policy'),
            'json_constraint':'xgrammar HF LogitsProcessor with shared ACTION_SCHEMA'}
        metadata.update(status='LOADED_NOT_LISTENING',settings=settings,
            base_model=artifact['backbone'],base_revision=REVISION,tokenizer_revision=REVISION,
            tokenizer_class=type(tokenizer).__name__,tokenizer_eos_token_id=tokenizer.eos_token_id,
            variants={'T0':{'actual_model_count':1,'actual_training_seeds':[],'matched_evaluation_seed_slots':list(SEEDS)},
                      **{m:{'actual_training_seeds':list(SEEDS)} for m in METHODS}},resident_adapter=bank.resident,
            versions={name:importlib.metadata.version(name) for name in ['torch','transformers','peft','bitsandbytes','xgrammar','safetensors']},
            load_and_grammar_wall_seconds=time.monotonic()-t,load_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            load_peak_reserved_bytes=torch.cuda.max_memory_reserved());save()
        def stop(signum,frame):
            nonlocal stopped
            stopped=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        class DeadlineStop(StoppingCriteria):
            def __init__(self,packet):self.packet=packet
            def __call__(self,input_ids,scores,**unused):
                remaining=remaining_utc_budget(self.packet)
                return remaining is not None and remaining<=0
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*unused):pass
            def respond(self,status,body):
                payload=json.dumps(body,allow_nan=False).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)))
                self.end_headers();self.wfile.write(payload)
            def do_GET(self):
                self.respond(200,{**metadata,'resident_wall_seconds_so_far':time.monotonic()-lifetime}) if self.path=='/health' else self.respond(404,{'error':'unknown endpoint'})
            def do_POST(self):
                nonlocal stopped
                if self.path!='/decision':self.respond(404,{'error':'unknown endpoint'});return
                inference_id=str(uuid.uuid4());work=out/'requests'/inference_id;work.mkdir(parents=True)
                record={'inference_id':inference_id,'status':'RUNNING','started_at_utc':datetime.now(timezone.utc).isoformat()}
                started=time.monotonic();before=resource.getrusage(resource.RUSAGE_SELF);usage=None;identity=None;gpu_started=False
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2*1024*1024:raise ValueError('Request exceeds ordinary packet transport limit')
                    body=json.loads(self.rfile.read(length));(work/'request.json').write_text(json.dumps(body,indent=2)+'\n')
                    prompt=validate_request(body,artifact['student_interface']);packet=body['request']['task_packet']
                    encoding=tokenizer.apply_chat_template([{'role':'user','content':prompt}],tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt')
                    input_tokens=int(encoding['input_ids'].shape[-1])
                    if input_tokens+1024>settings['maximum_context_tokens']:raise ValueError('Full source/history plus1024reserve exceeds frozen context; no truncation')
                    torch.cuda.reset_peak_memory_stats();gpu_started=True
                    activation=time.monotonic();selected=bank.activate(body['variant'],body['training_seed'])
                    activation_seconds=time.monotonic()-activation;metadata['resident_adapter']=bank.resident
                    identity={key:selected[key] for key in ['variant','training_seed','evaluation_seed_slot','source_role','base_revision']}
                    identity.update(base_model=artifact['backbone'],tokenizer_revision=REVISION,settings=settings,
                        student_interface_version=artifact['student_interface']['version'],
                        methods_manifest_sha256=metadata['methods_manifest_sha256'],
                        adapter_sha256=None if body['variant']=='T0' else artifact['variants'][body['variant']]['seeds'][str(body['training_seed'])]['adapter_sha256'])
                    check_utc_budget(packet);inputs={k:v.to('cuda:0') for k,v in encoding.items() if k in ('input_ids','attention_mask')}
                    torch.manual_seed(INFERENCE_SEED);torch.cuda.manual_seed_all(INFERENCE_SEED)
                    torch.cuda.synchronize();generation=time.monotonic()
                    begin=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True)
                    with bank.context(body['variant']),torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
                        begin.record();generated=bank.model.generate(**inputs,max_new_tokens=1024,do_sample=False,use_cache=True,
                            pad_token_id=tokenizer.pad_token_id,eos_token_id=tokenizer.eos_token_id,
                            logits_processor=[LogitsProcessor(compiled)],stopping_criteria=StoppingCriteriaList([DeadlineStop(packet)]));end.record()
                    torch.cuda.synchronize();tokens=generated[0,input_tokens:];text=tokenizer.decode(tokens,skip_special_tokens=True)
                    (work/'completion.txt').write_text(text);eos=bool(len(tokens) and int(tokens[-1])==tokenizer.eos_token_id)
                    after=resource.getrusage(resource.RUSAGE_SELF)
                    usage={'input_tokens':input_tokens,'output_tokens':len(tokens),'eos_terminated':eos,'max_new_tokens':1024,
                        'maximum_context_tokens':settings['maximum_context_tokens'],'adapter_activation_wall_seconds':activation_seconds,
                        'generation_wall_seconds':time.monotonic()-generation,'server_wall_seconds':time.monotonic()-started,
                        'cuda_stream_elapsed_seconds':begin.elapsed_time(end)/1000,'gpu_devices_allocated':1,
                        'server_user_cpu_seconds':after.ru_utime-before.ru_utime,'server_system_cpu_seconds':after.ru_stime-before.ru_stime,
                        'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),
                        'decoding_settings':{'do_sample':False,'seed':INFERENCE_SEED},'request_mode':'frozen_E4_ordinary_action','output_format':'structured_action'}
                    if not eos:raise ValueError('Constrained ACTION did not finish with EOS within1024tokens or the UTC budget')
                    check_utc_budget(packet);action=validate_action(json.loads(text),packet)
                    response={'inference_id':inference_id,'action':action,'usage':usage,'model':identity,'native_tools':[],
                        'model_identity':{key:identity[key] for key in ['variant','training_seed','evaluation_seed_slot','methods_manifest_sha256','adapter_sha256']}}
                    record.update(status='COMPLETED',response=response);metadata['successful_requests']+=1;self.respond(200,response)
                except Exception as error:
                    response={'inference_id':inference_id,'error':type(error).__name__+': '+str(error)}
                    if usage is not None:response.update(usage=usage,model=identity)
                    record.update(status='FAILED',response=response);metadata['failed_requests']+=1
                    if bank.failed:metadata.update(status='FAILED_ADAPTER_SWITCH',error=str(error));stopped=True
                    self.respond(422,response)
                finally:
                    record.update(ended_at_utc=datetime.now(timezone.utc).isoformat(),wall_seconds=time.monotonic()-started)
                    if gpu_started:record.update(peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved())
                    (work/'invocation.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n');save()
        server=HTTPServer(('127.0.0.1',PORT),Handler);server.timeout=.5
        metadata.update(status='READY',ready_at_utc=datetime.now(timezone.utc).isoformat());save()
        print(json.dumps({'status':'READY','pid':os.getpid(),'output':str(out),'port':PORT}),flush=True)
        while not stopped:server.handle_request()
        server.server_close()
        if metadata['status']=='READY':metadata.update(status='STOPPED',stopped_at_utc=datetime.now(timezone.utc).isoformat())
    except Exception as error:
        metadata.update(status='FAILED',error=type(error).__name__+': '+str(error));raise
    finally:
        metadata['service_wall_seconds_so_far']=time.monotonic()-lifetime;save()


def rpc(path,body=None):
    data=None if body is None else json.dumps(body).encode()
    request=urllib.request.Request('http://127.0.0.1:%d%s'%(PORT,path),data=data,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=600) as response:sys.stdout.write(response.read().decode()+'\n')
    except urllib.error.HTTPError as error:
        sys.stdout.write(error.read().decode()+'\n');raise SystemExit(2)


def main():
    parser=argparse.ArgumentParser(description=__doc__);modes=parser.add_mutually_exclusive_group(required=True)
    for name in ['serve','request','health','validate-only']:modes.add_argument('--'+name,action='store_true')
    parser.add_argument('--methods',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--initial-variant',choices=('T0',)+METHODS,default='T0');parser.add_argument('--training-seed',type=int,choices=SEEDS,default=41)
    args=parser.parse_args()
    if args.serve or args.validate_only:
        if args.methods is None:parser.error('--methods requires a real readonly FROZEN_E4_METHODS file')
        if args.validate_only:
            artifact,_=validate_methods(args.methods)
            print(json.dumps({'status':'CONFIGURATION_VALIDATED_NO_GPU_LOAD','formal_training_runs':artifact['formal_training_runs'],
                'port':PORT,'student_interface':artifact['student_interface'],'READY':False}));return
        if args.output is None:parser.error('--serve requires a fresh --output directory')
        serve(args)
    elif args.health:rpc('/health')
    else:rpc('/decision',json.loads(sys.stdin.read()))


if __name__=='__main__':main()
