#!/usr/bin/env python3
"""Fixed local-only 32B NF4 policy inference; no model tool/file/exec interface."""
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.local_model_adapter import SOURCE_PROPOSAL_SCHEMA,decision_prompt,source_proposal_prompt,validate_source_proposal
from src.model_adapter import ACTION_SCHEMA,check_utc_budget,validate_action


def rpc(path,body=None):
    url="http://127.0.0.1:8114"+path
    data=json.dumps(body).encode() if body is not None else None
    request=urllib.request.Request(url,data=data,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(request,timeout=600) as response:
            sys.stdout.write(response.read().decode()+"\n")
    except urllib.error.HTTPError as exc:
        sys.stdout.write(exc.read().decode()+"\n");raise SystemExit(2)


def serve(args):
    from http.server import BaseHTTPRequestHandler,HTTPServer
    affinity=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,affinity[:4])
    os.environ["OMP_NUM_THREADS"]="2";os.environ["OPENBLAS_NUM_THREADS"]="2"
    os.environ["TOKENIZERS_PARALLELISM"]="false";os.environ["HF_HUB_OFFLINE"]="1"
    os.environ["TRANSFORMERS_OFFLINE"]="1"
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    metadata={"phase":"development_local_policy_calibration","pid":os.getpid(),"argv":[sys.executable]+sys.argv,
        "bind":"127.0.0.1","port":8114,"status":"LOADING","started_at_utc":datetime.now(timezone.utc).isoformat(),
        "native_tools":[],"formal_trials":0,"training_examples":0,"cpu_affinity":sorted(os.sched_getaffinity(0))}
    (out/"pid").write_text(str(os.getpid())+"\n")
    def save(): (out/"service.json").write_text(json.dumps(metadata,indent=2)+"\n")
    save();lifetime=time.monotonic()
    try:
        import torch
        from peft import PeftModel,prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM,AutoTokenizer,BitsAndBytesConfig
        import xgrammar
        from xgrammar.contrib.hf import LogitsProcessor
        torch.set_num_threads(2);torch.set_num_interop_threads(2)
        torch.manual_seed(args.seed);torch.cuda.manual_seed_all(args.seed)
        cache=json.loads((ROOT/"configs/training/backbone_cache.json").read_text())
        snapshot=Path(cache["snapshot"])
        if snapshot.name!=cache["revision"] or not snapshot.is_dir():raise ValueError("Pinned 32B snapshot is absent")
        if not torch.cuda.is_available() or torch.cuda.device_count()!=1:raise RuntimeError("Exactly one visible GPU required")
        tokenizer=AutoTokenizer.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False)
        tokenizer.pad_token=tokenizer.eos_token
        torch.cuda.reset_peak_memory_stats();started=time.monotonic()
        model=AutoModelForCausalLM.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16),
            dtype=torch.bfloat16,device_map={"":0},attn_implementation="sdpa")
        # Match the base/norm preparation used by actual training; apply this to
        # both disabled-adapter T0 and adapter variants, with no gradient graphs.
        model=prepare_model_for_kbit_training(model,use_gradient_checkpointing=False)
        adapter=args.development_adapter.resolve()
        config=json.loads((adapter/"adapter_config.json").read_text())
        if config["base_model_name_or_path"]!=str(snapshot):raise ValueError("Adapter belongs to another base model")
        model=PeftModel.from_pretrained(model,adapter,adapter_name="development",is_trainable=False)
        model.eval();model.config.use_cache=True
        for parameter in model.parameters():parameter.requires_grad_(False)
        torch.cuda.synchronize()
        info=xgrammar.TokenizerInfo.from_huggingface(tokenizer,vocab_size=model.config.vocab_size)
        compiler=xgrammar.GrammarCompiler(info,max_threads=2)
        compiled=compiler.compile_json_schema(ACTION_SCHEMA)
        source_compiled=compiler.compile_json_schema(SOURCE_PROPOSAL_SCHEMA)
        variants={"T0":{"source_role":"base_model_development_trial","adapter":None},
            "development_SFT_calibration":{"source_role":"two_update_engineering_calibration_not_T1","adapter":str(adapter)}}
        settings={"quantization":"NF4","double_quantization":True,"compute_dtype":"bfloat16",
            "nonquantized_preparation":"prepare_model_for_kbit_training(use_gradient_checkpointing=False)",
            "attention_backend":"sdpa","do_sample":False,"seed":args.seed,
            "max_new_tokens":args.max_new_tokens,"maximum_context_tokens":8192,"use_cache":True,
            "json_constraint":"xgrammar HF LogitsProcessor with shared ACTION_SCHEMA"}
        metadata["development_corpus_sampling_enabled"]=args.allow_corpus_sampling
        metadata["train_collection_sampling_enabled"]=args.allow_train_collection_sampling
        metadata["train_collection_source_enabled"]=args.allow_train_collection_sampling
        metadata["teacher_source_settings"]={"mode":"train_collection_source","variant":"T0",
            "output_format":"complete_module_source","max_new_tokens":3072,"maximum_context_tokens":8192,
            "schema":SOURCE_PROPOSAL_SCHEMA,"matched_policy_action_settings_changed":False}
        metadata.update(status="READY",ready_at_utc=datetime.now(timezone.utc).isoformat(),
            base_model=cache["repo_id"],base_revision=cache["revision"],tokenizer_revision=cache["revision"],
            tokenizer_class=type(tokenizer).__name__,tokenizer_eos_token_id=tokenizer.eos_token_id,
            variants=variants,settings=settings,
            versions={name:importlib.metadata.version(name) for name in ["torch","transformers","peft","bitsandbytes","xgrammar","safetensors"]},
            load_and_grammar_wall_seconds=time.monotonic()-started,
            allocated_bytes=torch.cuda.memory_allocated(),reserved_bytes=torch.cuda.memory_reserved(),
            load_peak_allocated_bytes=torch.cuda.max_memory_allocated(),load_peak_reserved_bytes=torch.cuda.max_memory_reserved(),
            successful_requests=0,failed_requests=0)
        save()
        stopped=False
        def stop(signum,frame):
            nonlocal stopped
            stopped=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*unused):pass
            def respond(self,status,body):
                payload=json.dumps(body).encode();self.send_response(status)
                self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(payload)))
                self.end_headers();self.wfile.write(payload)
            def do_GET(self):
                if self.path!="/health":self.respond(404,{"error":"unknown endpoint"});return
                self.respond(200,{**metadata,"resident_wall_seconds_so_far":time.monotonic()-lifetime})
            def do_POST(self):
                if self.path!="/decision":self.respond(404,{"error":"unknown endpoint"});return
                inference_id=str(uuid.uuid4());work=out/"requests"/inference_id;work.mkdir(parents=True)
                record={"inference_id":inference_id,"started_at_utc":datetime.now(timezone.utc).isoformat(),"status":"RUNNING"}
                t=time.monotonic();before=resource.getrusage(resource.RUSAGE_SELF)
                try:
                    length=int(self.headers.get("Content-Length","0"))
                    if not 0<length<=2*1024*1024:raise ValueError("Decision request exceeds the fixed packet limit")
                    body=json.loads(self.rfile.read(length))
                    corpus=set(body)=={"variant","request","mode","sampling"} and body.get("mode") in ("development_corpus","train_collection","train_collection_source")
                    source_mode=corpus and body["mode"]=="train_collection_source"
                    if (set(body)!={"variant","request"} and not corpus) or body["variant"] not in variants:raise ValueError("Unknown fixed model variant or request fields")
                    sampling={"do_sample":False,"seed":args.seed}
                    if corpus:
                        if body["mode"]=="development_corpus" and not args.allow_corpus_sampling:raise ValueError("Development corpus sampling is disabled by service configuration")
                        if body["mode"] in ("train_collection","train_collection_source") and (not args.allow_train_collection_sampling or body["variant"]!="T0"):
                            raise ValueError("Formal train collection needs an explicitly enabled T0 service")
                        values=body["sampling"]
                        if set(values)!={"temperature","top_p","seed"} or not isinstance(values["seed"],int) or isinstance(values["seed"],bool) or not 0<=values["seed"]<2**31:
                            raise ValueError("Corpus sampling requires an explicit integer seed and temperature/top_p")
                        if not isinstance(values["temperature"],(int,float)) or not 0<values["temperature"]<=2 or not isinstance(values["top_p"],(int,float)) or not 0<values["top_p"]<=1:
                            raise ValueError("Invalid corpus temperature or top_p")
                        sampling={"do_sample":True,**values}
                    (work/"request.json").write_text(json.dumps(body,indent=2)+"\n")
                    check_utc_budget(body["request"]["task_packet"])
                    prompt=source_proposal_prompt(body["request"]) if source_mode else decision_prompt(body["request"])
                    max_new_tokens=3072 if source_mode else args.max_new_tokens
                    encoding=tokenizer.apply_chat_template([{"role":"user","content":prompt}],tokenize=True,
                        add_generation_prompt=True,return_dict=True,return_tensors="pt")
                    inputs={k:v.to("cuda:0") for k,v in encoding.items() if k in ["input_ids","attention_mask"]}
                    input_tokens=inputs["input_ids"].shape[-1]
                    if input_tokens+max_new_tokens>8192:raise ValueError("Context budget exceeded; automatic truncation is forbidden")
                    torch.manual_seed(sampling["seed"]);torch.cuda.manual_seed_all(sampling["seed"])
                    model.set_adapter("development");model.eval()
                    context=model.disable_adapter() if body["variant"]=="T0" else nullcontext()
                    torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats();generation_start=time.monotonic()
                    begin=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True)
                    with context,torch.inference_mode():
                        begin.record()
                        generation_settings={k:v for k,v in sampling.items() if k!="seed"}
                        generated=model.generate(**inputs,max_new_tokens=max_new_tokens,**generation_settings,
                            use_cache=True,pad_token_id=tokenizer.pad_token_id,eos_token_id=tokenizer.eos_token_id,
                            logits_processor=[LogitsProcessor(source_compiled if source_mode else compiled)])
                        end.record()
                    torch.cuda.synchronize()
                    tokens=generated[0,input_tokens:];text=tokenizer.decode(tokens,skip_special_tokens=True)
                    (work/"completion.txt").write_text(text)
                    eos=bool(len(tokens) and int(tokens[-1])==tokenizer.eos_token_id)
                    after=resource.getrusage(resource.RUSAGE_SELF)
                    usage={"input_tokens":int(input_tokens),"output_tokens":len(tokens),
                        "generation_wall_seconds":time.monotonic()-generation_start,
                        "server_wall_seconds":time.monotonic()-t,"cuda_stream_elapsed_seconds":begin.elapsed_time(end)/1000,
                        "server_user_cpu_seconds":after.ru_utime-before.ru_utime,"server_system_cpu_seconds":after.ru_stime-before.ru_stime,
                        "peak_allocated_bytes":torch.cuda.max_memory_allocated(),"peak_reserved_bytes":torch.cuda.max_memory_reserved(),
                        "eos_terminated":eos,"gpu_devices_allocated":1,"decoding_settings":sampling,
                        "request_mode":body["mode"] if corpus else "matched_policy_decision",
                        "output_format":"complete_module_source" if source_mode else "structured_action",
                        "max_new_tokens":max_new_tokens,"maximum_context_tokens":8192}
                    identity={"variant":body["variant"],"base_model":cache["repo_id"],"base_revision":cache["revision"],
                        "tokenizer_revision":cache["revision"],**variants[body["variant"]],"settings":{**settings,**sampling,"max_new_tokens":max_new_tokens}}
                    if corpus and body["mode"]=="train_collection":identity["source_role"]="base_model_formal_train_collection"
                    if source_mode:
                        identity["source_role"]="base_model_formal_train_collection_source"
                        identity["settings"].update(output_format="complete_module_source",json_constraint="xgrammar HF LogitsProcessor with SOURCE_PROPOSAL_SCHEMA")
                    if not eos:raise ValueError("Generation did not terminate with a completed constrained JSON decision")
                    check_utc_budget(body["request"]["task_packet"])
                    if source_mode:
                        response={"inference_id":inference_id,"proposal":validate_source_proposal(json.loads(text)),"usage":usage,"model":identity,"native_tools":[]}
                    else:
                        response={"inference_id":inference_id,"action":validate_action(json.loads(text),body["request"]["task_packet"]),"usage":usage,"model":identity,"native_tools":[]}
                    record.update(status="COMPLETED",response=response);metadata["successful_requests"]+=1
                    self.respond(200,response)
                except Exception as exc:
                    response={"inference_id":inference_id,"error":type(exc).__name__+": "+str(exc)}
                    if "usage" in locals():response.update(usage=usage,model=identity)
                    record.update(status="FAILED",response=response);metadata["failed_requests"]+=1
                    self.respond(422,response)
                finally:
                    record["ended_at_utc"]=datetime.now(timezone.utc).isoformat();record["wall_seconds"]=time.monotonic()-t
                    (work/"invocation.json").write_text(json.dumps(record,indent=2)+"\n");save()
        server=HTTPServer(("127.0.0.1",8114),Handler);server.timeout=.5
        print(json.dumps({"status":"READY","pid":os.getpid(),"output":str(out)}),flush=True)
        while not stopped:server.handle_request()
        server.server_close();metadata.update(status="STOPPED",stopped_at_utc=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        metadata.update(status="FAILED",error=type(exc).__name__+": "+str(exc));raise
    finally:
        metadata["service_wall_seconds_so_far"]=time.monotonic()-lifetime;save()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    modes=p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--serve",action="store_true");modes.add_argument("--request",action="store_true");modes.add_argument("--health",action="store_true")
    p.add_argument("--output",type=Path);p.add_argument("--development-adapter",type=Path)
    p.add_argument("--max-new-tokens",type=int,default=1024);p.add_argument("--seed",type=int,default=41)
    p.add_argument("--allow-corpus-sampling",action="store_true",help="Enable separately labelled development-corpus sampling; ordinary policy requests stay greedy")
    p.add_argument("--allow-train-collection-sampling",action="store_true",help="Enable explicitly frozen collector T0 requests under mode=train_collection")
    args=p.parse_args()
    if args.serve:
        if args.output is None or args.development_adapter is None:p.error("--serve requires output and the explicit development adapter")
        serve(args)
    elif args.health:rpc("/health")
    else:rpc("/decision",json.loads(sys.stdin.read()))


if __name__=="__main__":main()
