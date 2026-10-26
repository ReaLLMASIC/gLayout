#!/usr/bin/env python3
"""Train T1/T2 SFT or T3/T4 DPO from a frozen, physically admitted manifest.

This entry point deliberately cannot start with the present draft registry/data.
Checkpoint selection is a later physical validation operation, never token loss.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import resource
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.training import (capture_rng, completion_log_probabilities, dpo_backward,
                          epoch_order, frozen_train_registry, reference_log_probabilities,
                          restore_rng, sample_identity, select_policy_adapter, set_seed, tensor_batch,
                          validate_training_manifest)
from src.student_interface import (MAX_NEW_TOKENS,encode_policy_action,interface_definition,
                                  validate_mapped_record)


def read_json(path):
    return json.loads(Path(path).read_text())


def read_samples(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def file_identity(path):
    # Required resume identity: do not apply saved optimizer/RNG state to different data.
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_matched_data(manifest, root):
    groups = {}
    for method in ("T1", "T2", "T3", "T4"):
        method_row = manifest.get("methods", {}).get(method, {})
        if method_row.get("samples"):
            groups[method] = read_samples(root / method_row["samples"])
    for left, right in (("T1", "T2"), ("T3", "T4")):
        if left not in groups or right not in groups or len(groups[left]) != len(groups[right]):
            raise ValueError("Matched methods need equal nonempty sample counts")
        a, b = groups[left], groups[right]
        if not a:
            raise ValueError("Empty training comparison")
        for first, second in zip(a, b):
            x,y=validate_mapped_record(first),validate_mapped_record(second)
            if (x["initial_state_id"], x["parent_lineage"], x["context"]) != (y["initial_state_id"], y["parent_lineage"], y["context"]):
                raise ValueError("Matched supervision methods must share sources, prompts and ordering")
            if first['student_request']!=second['student_request']:raise ValueError('Matched methods must use precisely the same ordinary policy request')
            if left == "T3" and (x["pair_id"] != y["pair_id"] or sorted([x["chosen"], x["rejected"]]) != sorted([y["chosen"], y["rejected"]])):
                raise ValueError("DPO methods must label the same candidate pairs")
    return groups


def prepare(args):
    manifest_path = args.manifest.resolve()
    manifest = read_json(manifest_path)
    method = validate_training_manifest(manifest, args.method, args.seed)
    config_path = (manifest_path.parent / manifest["training_config"]).resolve()
    config = read_json(config_path)
    if config.get("status") != "frozen" or config.get("formal_data_ready") is not True:
        raise ValueError("Training configuration/data readiness is not frozen")
    if (config.get("microbatch") != 1 or config.get("padding") not in ("fixed_max_length", "actual_sequence_length")
            or config.get("truncation") != "reject_oversize_no_automatic_truncation"
            or config.get("quantization", {}).get("compute_dtype") != "bfloat16"
            or config.get("quantization", {}).get("load_in_4bit") is not True
            or config.get("gradient_checkpointing") is not True):
        raise ValueError("Frozen recipe differs from the implemented single-GPU QLoRA path")
    if args.seed not in config.get("seeds", []):
        raise ValueError("Requested seed differs from the frozen recipe")
    registry_path = (manifest_path.parent / manifest["split_registry"]).resolve()
    registry = read_json(registry_path)
    assignments = frozen_train_registry(registry)
    groups = validate_matched_data(manifest, manifest_path.parent)
    interface=manifest.get('student_interface',{})
    definition=interface_definition(interface.get('version'),interface.get('max_context_tokens'),interface.get('max_new_tokens'))
    if (any(interface.get(key)!=value for key,value in definition.items()) or
        config['max_sequence_length']!=definition['max_context_tokens'] or
        interface.get('usable_samples_by_method')!={key:len(rows) for key,rows in groups.items()}):
        raise ValueError('Training manifest must freeze the implemented student interface, budgets and actual usable sample counts')
    selection=read_json(manifest_path.parent/interface['selection_report'])
    if (any(selection.get(key)!=interface.get(key) for key in ['max_context_tokens','max_new_tokens','usable_samples_by_method']) or
        selection.get('student_interface_version')!=definition['version'] or
        selection.get('history_policy')!=definition.get('history_policy')):
        raise ValueError('Frozen usable counts/budgets differ from the prospective paired student preflight')
    calibration_path=None
    if definition.get('history_policy'):
        from src.e4_methods import validate_context_calibration
        calibration_path=(manifest_path.parent/manifest['context_calibration']).resolve()
        validate_context_calibration(calibration_path,definition)
    for group in groups.values():
        for record in group:
            if (record['student_interface_version']!=definition['version'] or
                (definition.get('history_policy') and record['student_request']['task_packet']['budget'].get('maximum_context_tokens')!=definition['max_context_tokens'])):
                raise ValueError('Prepared record differs from the frozen interface/context version')
            row=record['raw_sample']
            if assignments.get(row["parent_lineage"], {}).get("split") != "train":
                raise ValueError("A nontrain lineage entered the prepared dataset")
            if row.get("source_role") != "formal_train" or not row.get("trusted_evidence_ids"):
                raise ValueError("Sample has not passed physical train-only admission")
    evidence = read_json(manifest_path.parent / manifest["trusted_evidence_manifest"])
    if evidence.get("status") != "admitted" or evidence.get("role") != "formal_train":
        raise ValueError("Trusted evidence admission is absent")
    accepted = set(evidence.get("admitted_sample_ids", []))
    if any(record['raw_sample']["sample_id"] not in accepted for rows in groups.values() for record in rows):
        raise ValueError("Sample ID is absent from independent physical admission")
    if evidence.get("registry_sha256") != file_identity(registry_path):
        raise ValueError("Split registry changed after physical admission")
    if any(evidence.get("sample_sha256", {}).get(record['raw_sample']["sample_id"]) != sample_identity(record['raw_sample'])
           for rows in groups.values() for record in rows):
        raise ValueError("Sample source/context/edit/label changed after physical admission")
    if args.resume and not (args.resume / "complete.json").is_file():
        raise ValueError("Resume checkpoint lacks its completed optimizer-boundary marker")
    identities = {"manifest": file_identity(manifest_path), "config": file_identity(config_path),
                  "registry": file_identity(registry_path),
                  "student_selection":file_identity(manifest_path.parent/interface['selection_report']),
                  "datasets": {key: file_identity(manifest_path.parent / value["samples"])
                               for key, value in manifest["methods"].items() if value.get("samples")}}
    if calibration_path is not None:identities['context_calibration']=file_identity(calibration_path)
    return manifest, config, method, groups[args.method], identities


def run(args):
    manifest, config, method, rows, identities = prepare(args)
    if args.validate_only:
        print(json.dumps({"status": "ADMITTED", "method": args.method, "seed": args.seed,
                          "samples": len(rows), "identities": identities}))
        return
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("This frozen recipe requires one explicitly available CUDA device")
    if torch.cuda.mem_get_info()[0] < 65 * 1024 ** 3:
        raise RuntimeError("GPU is not available for the 32B training recipe; do not interrupt other jobs here")
    args._gpu_start = time.monotonic()
    start = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "run.json").exists() and args.resume is None:
        raise ValueError("Existing run requires an explicit checkpoint resume")
    set_seed(args.seed)
    snapshot = Path(manifest["backbone_snapshot"])
    if snapshot.name != config["revision"] or not snapshot.is_dir():
        raise ValueError("Backbone snapshot does not match the frozen revision")
    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True, trust_remote_code=False)
    tokenizer.pad_token = tokenizer.eos_token
    length = config["max_sequence_length"]
    dpo = args.method in ("T3", "T4")
    # At microbatch 1 the attention mask already excludes padding, so padding every sample to the frozen 16k window only
    # costs time; "actual_sequence_length" pads to the longest sequence of the item (one sample, or the chosen/rejected pair).
    def pad_length(items):
        return length if config["padding"] == "fixed_max_length" else max(len(item.input_ids) for item in items)
    encoded = []
    for record in rows:
        row=record['raw_sample'];request=record['student_request']
        if dpo:
            value=tuple(encode_policy_action(tokenizer,request,row[name],length,MAX_NEW_TOKENS) for name in ('chosen','rejected'))
            names=('chosen','rejected')
        else:
            value=encode_policy_action(tokenizer,request,row['patch'],length,MAX_NEW_TOKENS);names=('patch',)
        actual={name:{'prompt_tokens':item.prompt_tokens,'completion_tokens_including_EOS':item.completion_tokens,'total_tokens':len(item.input_ids)}
                for name,item in zip(names,value if dpo else (value,))}
        if actual!=record['token_counts']:raise ValueError('Actual ordinary-action tokenization differs from the frozen paired preflight; do not drop examples during training')
        encoded.append(value)
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type=config["quantization"]["bnb_4bit_quant_type"],
                               bnb_4bit_use_double_quant=config["quantization"]["bnb_4bit_use_double_quant"],
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(str(snapshot), local_files_only=True, trust_remote_code=False,
            quantization_config=quant, dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                           gradient_checkpointing_kwargs={"use_reentrant": False})
    lora = config["lora"]
    for target in lora["target_modules"]:
        if not any(name.endswith("." + target) for name, _ in model.named_modules()):
            raise ValueError("LoRA target absent from actual backbone: " + target)
    starting = method.get("starting_t1_checkpoints", {}).get(str(args.seed))
    if dpo:
        if not Path(starting).is_dir():
            raise ValueError("Selected same-seed T1 checkpoint is absent")
        policy_path = str(args.resume / "adapter" / "policy") if args.resume else starting
        model = PeftModel.from_pretrained(model, policy_path, adapter_name="policy", is_trainable=True)
        model.load_adapter(starting, adapter_name="reference", is_trainable=False)
        for module in model.modules():
            if isinstance(module, torch.nn.Dropout):
                module.p = 0.0
        select_policy_adapter(model)
    elif args.resume:
        model = PeftModel.from_pretrained(model, str(args.resume / "adapter" / "policy"), adapter_name="policy", is_trainable=True)
    else:
        model = get_peft_model(model, LoraConfig(r=lora["r"], lora_alpha=lora["alpha"],
                 lora_dropout=lora["dropout"], target_modules=lora["target_modules"], task_type="CAUSAL_LM"), adapter_name="policy")
    model.train()
    trainable = [value for value in model.parameters() if value.requires_grad]
    recipe = config["dpo" if dpo else "sft"]
    accumulation = config["gradient_accumulation"]
    updates_per_epoch = math.ceil(len(rows) / accumulation)
    total_updates = recipe["epochs"] * updates_per_epoch
    optimizer = torch.optim.AdamW(trainable, lr=recipe["learning_rate"], weight_decay=config["weight_decay"])
    warmup = max(1, math.ceil(total_updates * config["warmup_fraction"]))
    def factor(step):
        if step < warmup:
            return (step + 1) / warmup
        progress = min(1.0, (step - warmup) / max(1, total_updates - warmup))
        return 0.5 * (1.0 + math.cos(math.pi * progress))
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, factor)
    next_epoch, next_cursor, updates = 0, 0, 0
    resumed_seconds, resumed_tokens = 0.0, 0
    if args.resume:
        saved = torch.load(args.resume / "training_state.pt", map_location="cpu", weights_only=False)
        if saved["identities"] != identities or saved["method"] != args.method or saved["seed"] != args.seed:
            raise ValueError("Checkpoint/data/config/seed identity mismatch")
        optimizer.load_state_dict(saved["optimizer"])
        scheduler.load_state_dict(saved["scheduler"])
        next_epoch, next_cursor, updates = saved["next_epoch"], saved["next_cursor"], saved["updates"]
        resumed_seconds, resumed_tokens = saved["wall_seconds"], saved["completion_tokens"]
        restore_rng(saved["rng"])
    completion_tokens = resumed_tokens
    torch.cuda.reset_peak_memory_stats()
    versions = {name: importlib.metadata.version(name) for name in ("torch", "transformers", "peft", "bitsandbytes", "accelerate")}
    run_record = {"method": args.method, "seed": args.seed, "status": "RUNNING",
                  "started_at_utc": datetime.now(timezone.utc).isoformat(), "identities": identities,
                  "versions": versions, "reference_checkpoint": starting, "samples": len(rows),
                  "student_interface":manifest['student_interface'],
                  "allocated_sequence_tokens_per_epoch": len(rows) * length * (2 if dpo else 1),
                  "completion_tokens_per_epoch": sum(sum(x.completion_tokens for x in item) if dpo else item.completion_tokens for item in encoded),
                  "dpo_forward_schedule": {"policy": 4, "reference": 2, "simultaneous_policy_graphs": 1} if dpo else None,
                  "selection_status": "not_selected_requires_external_physical_validation"}
    (args.output / "run.json").write_text(json.dumps(run_record, indent=2) + "\n")
    def checkpoint(epoch, cursor):
        destination = args.output / ("checkpoint-%07d" % updates)
        destination.mkdir(exist_ok=True)
        (destination / "complete.json").unlink(missing_ok=True)
        model.save_pretrained(destination / "adapter", selected_adapters=["policy"])
        tokenizer.save_pretrained(destination / "tokenizer")
        metadata = destination / "metadata"
        metadata.mkdir(exist_ok=True)
        (metadata / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (metadata / "training_config.json").write_text(json.dumps(config, indent=2) + "\n")
        (metadata / "run.json").write_text(json.dumps(run_record, indent=2) + "\n")
        if (args.output / "metrics.jsonl").exists():
            shutil.copyfile(args.output / "metrics.jsonl", metadata / "metrics.jsonl")
        if (args.output / "attempts").exists():
            shutil.copytree(args.output / "attempts", metadata / "prior_attempts", dirs_exist_ok=True)
        state = {"identities": identities, "method": args.method, "seed": args.seed,
                 "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(), "rng": capture_rng(),
                 "next_epoch": epoch, "next_cursor": cursor, "updates": updates,
                 "wall_seconds": resumed_seconds + time.monotonic() - start, "completion_tokens": completion_tokens}
        torch.save(state, destination / "training_state.pt")
        (destination / "complete.json").write_text(json.dumps({"optimizer_boundary": True, "updates": updates,
                    "reference_checkpoint": starting, "selected": False}) + "\n")
        (args.output / "latest_checkpoint.txt").write_text(str(destination.resolve()) + "\n")
    for epoch in range(next_epoch, recipe["epochs"]):
        order = epoch_order(len(rows), args.seed, epoch)
        cursor = next_cursor if epoch == next_epoch else 0
        while cursor < len(order):
            group = order[cursor:cursor + accumulation]
            optimizer.zero_grad(set_to_none=True)
            token_denominator = sum(encoded[index].completion_tokens for index in group) if not dpo else None
            group_loss = 0.0
            for index in group:
                if dpo:
                    chosen, rejected = encoded[index]
                    pair_length = pad_length((chosen, rejected))
                    batches = [tensor_batch(item, tokenizer.pad_token_id, pair_length, "cuda") for item in (chosen, rejected)]
                    loss = dpo_backward(model, batches[0], batches[1], recipe["beta"],
                                        normalizer=len(group), autocast_dtype=torch.bfloat16)
                    completion_tokens += chosen.completion_tokens + rejected.completion_tokens
                else:
                    item = encoded[index]
                    batch = tensor_batch(item, tokenizer.pad_token_id, pad_length((item,)), "cuda")
                    with torch.autocast("cuda", dtype=torch.bfloat16):
                        output = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])
                        values, _ = completion_log_probabilities(output.logits, batch["labels"])
                        loss = -values.sum() / token_denominator
                    completion_tokens += item.completion_tokens
                if not bool(torch.isfinite(loss)):
                    raise RuntimeError("Nonfinite training loss")
                group_loss += float(loss.detach())
                if not dpo:
                    loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, config["max_gradient_norm"])
            optimizer.step()
            scheduler.step()
            updates += 1
            cursor += len(group)
            with (args.output / "metrics.jsonl").open("a") as log:
                log.write(json.dumps({"epoch": epoch, "updates": updates, "next_cursor": cursor,
                    "loss": group_loss, "learning_rate": scheduler.get_last_lr()[0],
                    "wall_seconds": resumed_seconds + time.monotonic() - start,
                    "completion_tokens": completion_tokens, "max_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
                    "max_cuda_reserved_bytes": torch.cuda.max_memory_reserved()}) + "\n")
            if updates % config["checkpoint_interval_updates"] == 0 or cursor == len(order):
                checkpoint(epoch + 1 if cursor == len(order) else epoch, 0 if cursor == len(order) else cursor)
        next_cursor = 0
    elapsed = resumed_seconds + time.monotonic() - start
    run_record.update(status="TRAINING_COMPLETED_NOT_SELECTED", updates=updates, wall_seconds=elapsed,
                      gpu_hours_allocated=elapsed / 3600, completion_tokens=completion_tokens,
                      peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                      peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved())
    (args.output / "run.json").write_text(json.dumps(run_record, indent=2) + "\n")
    print(json.dumps({"status": run_record["status"], "output": str(args.output), "updates": updates}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--method", choices=["T1", "T2", "T3", "T4"], required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    begin = time.monotonic()
    success = False
    try:
        run(args)
        success = True
    finally:
        if not args.validate_only:
            args.output.mkdir(parents=True, exist_ok=True)
            attempts = args.output / "attempts"
            attempts.mkdir(exist_ok=True)
            usage = resource.getrusage(resource.RUSAGE_SELF)
            gpu_seconds = time.monotonic() - args._gpu_start if hasattr(args, "_gpu_start") else 0
            record = {"started_at_utc": started.isoformat(), "ended_at_utc": datetime.now(timezone.utc).isoformat(),
                      "status": "COMPLETED" if success else "FAILED", "method": args.method, "seed": args.seed,
                      "wall_seconds": time.monotonic() - begin, "cpu_user_seconds": usage.ru_utime,
                      "cpu_system_seconds": usage.ru_stime, "gpu_allocated_seconds": gpu_seconds,
                      "gpu_hours_allocated": gpu_seconds / 3600, "resume": str(args.resume) if args.resume else None}
            (attempts / (started.strftime("%Y%m%dT%H%M%S%fZ") + ".json")).write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
