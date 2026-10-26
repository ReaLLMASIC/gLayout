#!/usr/bin/env python3
"""Development-only actual 32B QLoRA kernel, memory and fixed-reference smoke.

The artificial context below is an algorithm workload, never training evidence.
This program cannot emit formal datasets or selected experiment checkpoints.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.training import (encode_patch,tensor_batch,completion_log_probabilities,dpo_backward,
    reference_log_probabilities,select_policy_adapter,set_seed,capture_rng,restore_rng)

p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--snapshot",type=Path,required=True)
p.add_argument("--output",type=Path,required=True)
p.add_argument("--resume-development-sft",type=Path)
p.add_argument("--sequence-length",type=int,choices=[8192,12288,16384],default=8192)
a=p.parse_args()
if a.output.exists():p.error("Preserve earlier calibration output; use a fresh directory")
a.output.mkdir(parents=True)
(a.output/'calibration_source.py').write_text(Path(__file__).read_text())
(a.output/'training_source.py').write_text((Path(__file__).resolve().parents[1]/'src/training.py').read_text())
affinity=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,affinity[:4])
start=time.monotonic()
record={"scope":"development_gpu_algorithm_calibration_not_E4", "formal_training_examples":0,
    "formal_training_runs":0,"status":"RUNNING","started_at_utc":datetime.now(timezone.utc).isoformat(),
    "snapshot":str(a.snapshot),"allocated_sequence_tokens":a.sequence_length,"cpu_affinity":sorted(os.sched_getaffinity(0)),"stages":[]}
def save():
    (a.output/"calibration.json").write_text(json.dumps(record,indent=2)+"\n")
save()
try:
    import torch
    torch.set_num_threads(2);torch.set_num_interop_threads(2)
    from peft import LoraConfig,PeftModel,get_peft_model,prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM,AutoTokenizer,BitsAndBytesConfig
    if not torch.cuda.is_available() or torch.cuda.device_count()!=1:raise RuntimeError("One available GPU required")
    if torch.cuda.mem_get_info()[0]<65*1024**3:raise RuntimeError("GPU is occupied; service pause belongs to coordinator")
    set_seed(41)
    cfg=json.loads((Path(__file__).resolve().parents[1]/"configs/training/pilot.json").read_text())
    record["recipe"]=cfg
    tokenizer=AutoTokenizer.from_pretrained(str(a.snapshot),local_files_only=True,trust_remote_code=False)
    tokenizer.pad_token=tokenizer.eos_token
    torch.cuda.reset_peak_memory_stats();t=time.monotonic()
    model=AutoModelForCausalLM.from_pretrained(str(a.snapshot),local_files_only=True,trust_remote_code=False,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16),
        dtype=torch.bfloat16,device_map={"":0},attn_implementation="sdpa")
    model.config.use_cache=False
    model=prepare_model_for_kbit_training(model,use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant":False})
    lc=cfg["lora"]
    if a.resume_development_sft:
        model=PeftModel.from_pretrained(model,a.resume_development_sft/"adapter"/"policy",
            adapter_name="policy",is_trainable=True)
    else:
        model=get_peft_model(model,LoraConfig(r=lc["r"],lora_alpha=lc["alpha"],lora_dropout=lc["dropout"],
            target_modules=lc["target_modules"],task_type="CAUSAL_LM"),adapter_name="policy")
    model.train()
    params=[v for v in model.parameters() if v.requires_grad]
    optimizer=torch.optim.AdamW(params,lr=cfg["sft"]["learning_rate"])
    if a.resume_development_sft:
        saved=torch.load(a.resume_development_sft/"training_state.pt",map_location="cpu",weights_only=False)
        if saved["scope"]!=record["scope"]:raise ValueError("Not an engineering calibration checkpoint")
        optimizer.load_state_dict(saved["optimizer"]);restore_rng(saved["rng"])
        record["resumed_actual_adapter_optimizer_rng"]=str(a.resume_development_sft)
        del saved
    record["trainable_parameters"]=sum(v.numel() for v in params)
    record["stages"].append({"name":"load_32B_NF4_r32","wall_seconds":time.monotonic()-t,
        "allocated_bytes":torch.cuda.memory_allocated(),"reserved_bytes":torch.cuda.memory_reserved()});save()
    patch="--- a/generator.py\n+++ b/generator.py\n@@ -1 +1 @@\n-width = 0.1\n+width = 0.2\n"
    chosen=None
    context_target=7600 if a.sequence_length==8192 else a.sequence_length-160
    for length,target in ([] if a.resume_development_sft else [(512,320),(a.sequence_length,context_target)]):
        context="Development algorithm workload. Source follows.\n"
        # Exercise a nearly full real context instead of timing mostly padding.
        row="# preserved transistor terminal, source routing and declared circuit dimensions\n"
        while len(tokenizer(context,add_special_tokens=False)["input_ids"])<target:context+=row
        chosen=encode_patch(tokenizer,context,patch,length)
        batch=tensor_batch(chosen,tokenizer.pad_token_id,length,"cuda")
        optimizer.zero_grad(set_to_none=True);torch.cuda.reset_peak_memory_stats();t=time.monotonic()
        with torch.autocast("cuda",dtype=torch.bfloat16):
            output=model(input_ids=batch["input_ids"],attention_mask=batch["attention_mask"])
            values,_=completion_log_probabilities(output.logits,batch["labels"])
            loss=-values.sum()/chosen.completion_tokens
        if not bool(torch.isfinite(loss)):raise RuntimeError("Nonfinite SFT loss")
        loss.backward();norm=torch.nn.utils.clip_grad_norm_(params,1.0);optimizer.step();torch.cuda.synchronize()
        record["stages"].append({"name":"SFT_optimizer_update","allocated_sequence_tokens":length,
            "prompt_tokens":chosen.prompt_tokens,"completion_tokens":chosen.completion_tokens,
            "loss":float(loss.detach()),"gradient_norm":float(norm),"wall_seconds":time.monotonic()-t,
            "peak_allocated_bytes":torch.cuda.max_memory_allocated(),"peak_reserved_bytes":torch.cuda.max_memory_reserved()})
        del output,values,loss,batch;optimizer.zero_grad(set_to_none=True);save()
    if a.resume_development_sft:
        checkpoint=a.resume_development_sft
        context="Development algorithm workload. Source follows.\n"
        row="# preserved transistor terminal, source routing and declared circuit dimensions\n"
        while len(tokenizer(context,add_special_tokens=False)["input_ids"])<context_target:context+=row
        chosen=encode_patch(tokenizer,context,patch,a.sequence_length)
    else:
        checkpoint=a.output/"development_SFT_checkpoint"
        model.save_pretrained(checkpoint/"adapter",selected_adapters=["policy"])
        tokenizer.save_pretrained(checkpoint/"tokenizer")
        torch.save({"optimizer":optimizer.state_dict(),"rng":capture_rng(),"scope":record["scope"]},checkpoint/"training_state.pt")
        (checkpoint/"complete.json").write_text(json.dumps({"optimizer_boundary":True,"formal":False})+"\n")
    if a.sequence_length>=12288:
        # Verify a real disk round-trip, including a changed adapter element,
        # optimizer state and the next CPU/CUDA RNG values. No formal example.
        from peft.utils.save_and_load import load_peft_weights,set_peft_model_state_dict
        from peft import get_peft_model_state_dict
        t=time.monotonic();saved=torch.load(checkpoint/"training_state.pt",map_location="cpu",weights_only=False)
        weights=load_peft_weights(checkpoint/"adapter"/"policy",device="cpu")
        with torch.no_grad():params[0].view(-1)[0].add_(1)
        optimizer.param_groups[0]['lr']*=2
        set_peft_model_state_dict(model,weights,adapter_name="policy")
        optimizer.load_state_dict(saved['optimizer']);restore_rng(saved['rng'])
        expected_cpu=torch.rand(4);expected_cuda=torch.rand(4,device="cuda").cpu()
        restore_rng(saved['rng'])
        rng_ok=torch.equal(expected_cpu,torch.rand(4)) and torch.equal(expected_cuda,torch.rand(4,device="cuda").cpu())
        restored=get_peft_model_state_dict(model,adapter_name="policy")
        adapter_ok=set(restored)==set(weights) and all(torch.equal(restored[name].cpu(),value) for name,value in weights.items())
        optimizer_ok=len(optimizer.state)==len(saved['optimizer']['state']) and optimizer.param_groups[0]['lr']==saved['optimizer']['param_groups'][0]['lr']
        state_pairs=zip(optimizer.state.values(),saved['optimizer']['state'].values())
        optimizer_ok=optimizer_ok and all(set(current)==set(old) and all(torch.equal(current[k].cpu(),v) if torch.is_tensor(v) else current[k]==v for k,v in old.items()) for current,old in state_pairs)
        restore_rng(saved['rng'])
        stage={"name":"actual_saved_adapter_optimizer_RNG_disk_restore","wall_seconds":time.monotonic()-t,"adapter_bitwise_equal":adapter_ok,"optimizer_state_bitwise_equal":optimizer_ok,"next_CPU_and_CUDA_RNG_equal":rng_ok,"checkpoint":str(checkpoint)}
        record['stages'].append(stage);save()
        if not(adapter_ok and optimizer_ok and rng_ok):raise RuntimeError("Engineering checkpoint disk restore changed state")
        del saved,weights,restored
    # A distinct reference is loaded from the actual just-saved SFT adapter.
    model.load_adapter(checkpoint/"adapter"/"policy",adapter_name="reference",is_trainable=False)
    for module in model.modules():
        if isinstance(module,torch.nn.Dropout):module.p=0
    select_policy_adapter(model)
    # PEFT load_adapter(is_trainable=False) calls eval() on the entire model.
    # Restore training so gradient checkpointing applies to policy forwards.
    model.train()
    record["dpo_model_training"]=model.training
    record["dpo_gradient_checkpointing"]=model.is_gradient_checkpointing
    save()
    rejected=encode_patch(tokenizer,context,patch.replace("+width = 0.2","+width = 0.15"),a.sequence_length)
    batches=[tensor_batch(item,tokenizer.pad_token_id,a.sequence_length,"cuda") for item in (chosen,rejected)]
    torch.cuda.reset_peak_memory_stats();t=time.monotonic()
    refs=[reference_log_probabilities(model,b) for b in batches]
    optimizer.zero_grad(set_to_none=True)
    loss=dpo_backward(model,batches[0],batches[1],.1,autocast_dtype=torch.bfloat16)
    if not bool(torch.isfinite(loss)):raise RuntimeError("Nonfinite DPO loss")
    norm=torch.nn.utils.clip_grad_norm_(params,1.0)
    optimizer.step();torch.cuda.synchronize()
    stage={"name":"DPO_"+str(a.sequence_length)+"_pair_optimizer_update","allocated_sequence_tokens":a.sequence_length,"prompt_tokens":chosen.prompt_tokens,"completion_tokens":[chosen.completion_tokens,rejected.completion_tokens],"loss":float(loss.detach()),"gradient_norm":float(norm),
        "wall_seconds":time.monotonic()-t,"peak_allocated_bytes":torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes":torch.cuda.max_memory_reserved(),"policy_forwards":4,"reference_forwards_in_timed_stage":4,
        "DPO_backward_reference_forwards":2,"pre_update_reference_check_forwards":2,"post_update_reference_check_forwards":2,
        "implementation":"exact_chain_rule_sequential_recomputed_policy_graphs"}
    del loss;optimizer.zero_grad(set_to_none=True)
    reference_check_start=time.monotonic()
    after=[reference_log_probabilities(model,b) for b in batches]
    torch.cuda.synchronize();stage['post_update_reference_check_wall_seconds']=time.monotonic()-reference_check_start
    stage["frozen_reference_bitwise_unchanged"]=all(torch.equal(x,y) for x,y in zip(refs,after))
    if not stage["frozen_reference_bitwise_unchanged"]:raise RuntimeError("DPO reference changed after policy update")
    record["stages"].append(stage)
    record["status"]="COMPLETED"
except BaseException as error:
    record.update(status="FAILED",error_type=type(error).__name__,error=str(error))
    raise
finally:
    usage=resource.getrusage(resource.RUSAGE_SELF)
    record.update(wall_seconds=time.monotonic()-start,process_cpu_seconds=usage.ru_utime+usage.ru_stime,
        max_rss_KiB=usage.ru_maxrss,ended_at_utc=datetime.now(timezone.utc).isoformat())
    save()
