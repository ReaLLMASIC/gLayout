"""Development-only longest TRAIN request: two ordinary generations, no labels.

The coordinator must drain/stop its own8114 first. This program never signals a
service or starts an HTTP endpoint. A new output directory preserves every run.
"""
import argparse
from contextlib import nullcontext
from datetime import datetime,timezone
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.local_model_adapter import decision_prompt
from src.model_adapter import ACTION_SCHEMA,PACKET_FIELDS,prompt_token_budget,validate_action

REVISION='381fc969f78efac66bc87ff7ddeadb7e73c218a7'
SCOPE='development_ordinary_inference_memory_calibration_not_a_T0_trial_or_E4_model'


def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def ordinary_request(body):
    request=body['request']
    if set(request)!={'task_packet','visible_history'} or set(request['task_packet'])!=set(PACKET_FIELDS):
        raise ValueError('Keep the complete ordinary request and declared source/contract/history fields')
    budget=request['task_packet']['budget']
    if budget.get('maximum_context_tokens')!=16384 or budget.get('maximum_output_tokens')!=1024:
        raise ValueError('Only the unchanged16k/1024 ordinary TRAIN request is accepted')
    decision_prompt(request)
    return request


def run(args):
    from transformers import AutoTokenizer
    if args.output.exists():raise ValueError('Use a fresh engineering output directory')
    request=ordinary_request(json.loads(args.request.read_text()))
    if args.snapshot.name!=REVISION:raise ValueError('Use the pinned32B snapshot')
    adapter_config=json.loads((args.engineering_adapter/'adapter_config.json').read_text())
    if adapter_config.get('r')!=32 or adapter_config.get('base_model_name_or_path')!=str(args.snapshot):
        raise ValueError('The engineering adapter must be the retained rank32 adapter for this exact base')
    if not (args.engineering_adapter/'adapter_model.safetensors').is_file():raise ValueError('Actual engineering weights are absent')
    tokenizer=AutoTokenizer.from_pretrained(args.snapshot,local_files_only=True,trust_remote_code=False)
    tokenizer.pad_token=tokenizer.eos_token
    if tokenizer.eos_token_id!=151645:raise ValueError('Pinned tokenizer EOS differs')
    prompt=decision_prompt(request);flight=prompt_token_budget(tokenizer,prompt,{'max_context_tokens':16384,'max_new_tokens':1024})
    if not flight['fits_with_full_output_reserve']:raise ValueError('Full source/history does not fit; never truncate')
    args.output.mkdir(parents=True);shutil.copyfile(args.request,args.output/'original_request_body.json')
    shutil.copyfile(__file__,args.output/'calibration_source.py');save(args.output/'ordinary_request.json',request)
    record={'scope':SCOPE,'status':'PREFLIGHT_ONLY_NO_GPU' if args.preflight_only else 'RUNNING',
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'request_path':str(args.request.resolve()),
        'prompt_preflight':flight,'engineering_adapter':str(args.engineering_adapter.resolve()),'adapter_rank':32,
        'backbone_snapshot':str(args.snapshot),'actual_model_count':0,'maximum_generation_calls':2,
        'formal_training_runs':0,'training_examples':0,'new_physical_calls':0,'trials':[],
        'original_trial_not_reexecuted':'Only its complete public TRAIN request value is reused as an engineering workload. Original sampler mode/seed are ignored; greedy41 applies to both engineering arms. No trial matrix is resumed or rewritten.',
        'settings':{'NF4':True,'double_quantization':True,'bnb_compute_dtype':'bfloat16','attention_backend':'sdpa',
            'nonquantized_preparation':'prepare_model_for_kbit_training(use_gradient_checkpointing=False)',
            'nonquantized_inference_autocast':'bfloat16','use_cache':True,'do_sample':False,'seed':41,
            'max_new_tokens':1024,'maximum_context_tokens':16384,'per_generation_wall_seconds':240,
            'logits_to_keep':'Unspecified; installed generation automatically selects1 for supported Qwen forward'},
        'limitations':'The actual EOS length is reported. A short completion never establishes full1024-token generation capacity. Dispatch observer records real attention ops and dtypes with instrumentation overhead; these timings are not formal-policy throughput measurements. No action is applied or used as a label.'}
    save(args.output/'calibration.json',record)
    if args.preflight_only:return record
    import torch
    from torch.utils._python_dispatch import TorchDispatchMode
    from peft import PeftModel,prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM,BitsAndBytesConfig,StoppingCriteria,StoppingCriteriaList
    import xgrammar
    from xgrammar.contrib.hf import LogitsProcessor
    torch.set_num_threads(2);torch.set_num_interop_threads(2)
    try:
        if not torch.cuda.is_available() or torch.cuda.device_count()!=1:raise RuntimeError('One available GPU required')
        if torch.cuda.mem_get_info()[0]<65*1024**3:raise RuntimeError('GPU occupied; coordinator must drain its own8114. No service was signalled.')
        record['versions']={n:importlib.metadata.version(n) for n in ['torch','transformers','peft','bitsandbytes','xgrammar']}
        torch.manual_seed(41);torch.cuda.manual_seed_all(41);torch.cuda.reset_peak_memory_stats();began=time.monotonic()
        model=AutoModelForCausalLM.from_pretrained(args.snapshot,local_files_only=True,trust_remote_code=False,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16),dtype=torch.bfloat16,device_map={'':0},attn_implementation='sdpa')
        model=prepare_model_for_kbit_training(model,use_gradient_checkpointing=False)
        model=PeftModel.from_pretrained(model,args.engineering_adapter,adapter_name='engineering',is_trainable=False)
        model.eval();model.config.use_cache=True
        for p in model.parameters():p.requires_grad_(False)
        base=model.get_base_model();record.update(actual_model_count=1,load_wall_seconds=time.monotonic()-began,
            load_peak_allocated_bytes=torch.cuda.max_memory_allocated(),auto_logits_to_keep_supported=base._supports_logits_to_keep(),
            nonquantized_embedding_parameter_dtype=str(base.get_input_embeddings().weight.dtype),
            nonquantized_output_parameter_dtype=str(base.get_output_embeddings().weight.dtype))
        compiler=xgrammar.GrammarCompiler(xgrammar.TokenizerInfo.from_huggingface(tokenizer,vocab_size=model.config.vocab_size),max_threads=2)
        compiled=compiler.compile_json_schema(ACTION_SCHEMA)

        class AttentionObserver(TorchDispatchMode):
            def __init__(self):super().__init__();self.records=[];self.seen=set()
            def __torch_dispatch__(self,func,types,args=(),kwargs=None):
                name=str(func)
                if ('scaled_dot_product' in name or 'efficient_attention' in name or name.startswith('aten.bmm')) and len(self.records)<16:
                    tensors=[v for v in args if isinstance(v,torch.Tensor)]
                    phase='prefill' if tensors and tensors[0].ndim>=2 and tensors[0].shape[-2]>1 else 'decode'
                    key=(name,phase)
                    if key not in self.seen:
                        self.seen.add(key);self.records.append({'operator':name,'phase':phase,
                            'tensor_arguments':[{'dtype':str(v.dtype),'shape':list(v.shape),'device':str(v.device)} for v in tensors]})
                return func(*args,**(kwargs or {}))

        class WallStop(StoppingCriteria):
            def __init__(self,deadline):self.deadline=deadline
            def __call__(self,*unused,**kwargs):return time.monotonic()>=self.deadline

        def generation(variant):
            folder=args.output/variant;folder.mkdir();observer=AttentionObserver();entry={'variant':variant,
                'source_role':'base_model_engineering_capacity_probe' if variant=='T0_disabled' else 'engineering_adapter_capacity_probe_not_T1',
                'input_tokens':flight['prompt_tokens'],'actual_output_tokens':None,'status':'STARTING','attention_dispatch':observer.records}
            started=time.monotonic();before=resource.getrusage(resource.RUSAGE_SELF);begin=end=None;gpu_started=False
            try:
                encoded=tokenizer.apply_chat_template([{'role':'user','content':prompt}],tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt')
                inputs={k:v.to('cuda:0') for k,v in encoded.items() if k in ['input_ids','attention_mask']}
                torch.manual_seed(41);torch.cuda.manual_seed_all(41);torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
                begin=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True);gpu_started=True
                context=model.disable_adapter() if variant=='T0_disabled' else nullcontext()
                with context,torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16),observer:
                    begin.record();result=model.generate(**inputs,max_new_tokens=1024,do_sample=False,use_cache=True,
                        pad_token_id=tokenizer.pad_token_id,eos_token_id=tokenizer.eos_token_id,
                        logits_processor=[LogitsProcessor(compiled)],stopping_criteria=StoppingCriteriaList([WallStop(started+240)]));end.record()
                torch.cuda.synchronize();tokens=result[0,flight['prompt_tokens']:];text=tokenizer.decode(tokens,skip_special_tokens=True)
                (folder/'completion.txt').write_text(text);entry.update(actual_output_tokens=len(tokens),eos_terminated=bool(len(tokens) and int(tokens[-1])==tokenizer.eos_token_id),
                    cuda_stream_elapsed_seconds=begin.elapsed_time(end)/1000)
                if not entry['eos_terminated'] or time.monotonic()-started>240:raise ValueError('Incomplete or late ordinary ACTION')
                action=validate_action(json.loads(text),request['task_packet']);save(folder/'action_not_applied.json',action)
                entry['status']='COMPLETED_ORDINARY_ACTION_NOT_APPLIED'
            except Exception as exc:
                entry.update(status='GPU_OOM_UNKNOWN_NOT_POLICY_FAILURE' if isinstance(exc,torch.cuda.OutOfMemoryError) else 'ENGINEERING_FAILURE',
                    error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
                entry.setdefault('cuda_stream_elapsed_seconds',None)
            finally:
                after=resource.getrusage(resource.RUSAGE_SELF);entry.update(wall_seconds=time.monotonic()-started,
                    user_CPU_seconds=after.ru_utime-before.ru_utime,system_CPU_seconds=after.ru_stime-before.ru_stime,
                    peak_allocated_bytes=torch.cuda.max_memory_allocated() if gpu_started else None,
                    peak_reserved_bytes=torch.cuda.max_memory_reserved() if gpu_started else None,ended_at_utc=datetime.now(timezone.utc).isoformat())
                save(folder/'invocation.json',entry)
            return entry

        for variant in ['T0_disabled','engineering_adapter']:
            trial=generation(variant);record['trials'].append(trial);save(args.output/'calibration.json',record)
            if trial['status']=='GPU_OOM_UNKNOWN_NOT_POLICY_FAILURE':break
        record['status']='COMPLETED_TWO_ORDINARY_ENGINEERING_GENERATIONS' if len(record['trials'])==2 and all(v['status']=='COMPLETED_ORDINARY_ACTION_NOT_APPLIED' for v in record['trials']) else 'ENGINEERING_CAPACITY_NOT_ESTABLISHED'
    except Exception as exc:record.update(status='ENGINEERING_LOAD_OR_RUNTIME_FAILURE',error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    finally:record['ended_at_utc']=datetime.now(timezone.utc).isoformat();save(args.output/'calibration.json',record)
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['request','snapshot','engineering-adapter','output']:parser.add_argument('--'+name,type=Path,required=True)
    modes=parser.add_mutually_exclusive_group(required=True);modes.add_argument('--preflight-only',action='store_true');modes.add_argument('--execute',action='store_true')
    print(json.dumps(run(parser.parse_args()),indent=2,allow_nan=False))
