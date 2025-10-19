from __future__ import annotations

import argparse
import json
import logging
import os
import gc
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

import torch
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    DataCollatorForLanguageModeling,
)


# muting wandb messages
os.environ.setdefault("WANDB_SILENT", "true")
os.environ.setdefault("WANDB_CONSOLE", "off")
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True,max_split_size_mb:256"

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supervised fine-tune a causal LM on code-fix dataset")

    parser.add_argument("--train_file", type=str, required=True, help="Path to training data (.jsonl or .json)")
    parser.add_argument("--eval_file", type=str, default=None, help="Optional evaluation data path")
    parser.add_argument("--output_dir", type=str, required=True, help="Directory to store checkpoints")

    parser.add_argument(
        "--model_paths",
        type=str,
        nargs="+",
        required=True,
        help="One or more local directories or model identifiers to fine-tune sequentially (e.g. ./7b/final_model ./13b/final_model)",
    )
    parser.add_argument("--max_length", type=int, default=1024, help="Max sequence length")

    # options for freezing layers
    parser.add_argument("--freeze_n_layers", type=int, default=0, help="Freeze first N transformer layers (old approach)")
    parser.add_argument("--train_last_n_layers", type=int, default=0, help="Train only the last N layers (recommended approach)")
    parser.add_argument("--full_weight_training", action="store_true", default=True, help="Ensure all weights are trainable (default: True)")

    # hyper-params (enhanced for full weight training)
    parser.add_argument("--per_device_train_batch_size", type=int, default=None, help="Auto-set based on GPU memory if not specified")
    parser.add_argument("--per_device_eval_batch_size", type=int, default=1)
    parser.add_argument("--learning_rate", type=float, default=3e-5, help="Learning rate for full weight training")
    parser.add_argument("--num_train_epochs", type=int, default=3)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=None, help="Auto-set based on GPU memory if not specified")
    parser.add_argument("--logging_steps", type=int, default=10)
    parser.add_argument("--save_total_limit", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--weight_decay", type=float, default=0.01)
    parser.add_argument("--warmup_ratio", type=float, default=0.1)
    parser.add_argument("--max_grad_norm", type=float, default=1.0)

    # other options
    parser.add_argument("--resume_from_checkpoint", type=str, default=None, help="Resume training from checkpoint")
    parser.add_argument("--use_wandb", action="store_true", help="Enable Weights & Biases logging")

    return parser.parse_args()


class CodeFixDataset(Dataset):

    def __init__(self, data: List[Dict[str, Any]], tokenizer, max_length: int = 1024):
        self.samples = data
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        sample = self.samples[idx]

        analysis_list = sample.get("analysis", [])
        if len(analysis_list) == 0:
            analysis_item = {
                "issue": "No specific issue identified",
                "explanation": {
                    "problem": "Code review completed",
                    "reason": "General code improvement",
                    "fix": "Code has been optimized"
                }
            }
        else:
            analysis_item = analysis_list[0]
        
        issue = analysis_item.get("issue", "")
        explanation = analysis_item.get("explanation", {})

        prompt = (
            f"Filename: {sample.get('filename', '')}\n"
            f"Issue: {issue}\n"
            f"Problem: {explanation.get('problem', '')}\n"
            f"Reason: {explanation.get('reason', '')}\n"
            f"### Fix:\n"
        )
        target = (
            f"{explanation.get('fix', '')}\n\n"
            f"### Fixed Code:\n{sample.get('fixed_code', '')}"
        )

        full_text = prompt + target + (self.tokenizer.eos_token or "</s>")

        tokenized = self.tokenizer(
            full_text,
            truncation=True,
            max_length=self.max_length,
            padding="max_length",
            return_tensors="pt",
        )
        input_ids = tokenized.input_ids.squeeze(0)
        attention_mask = tokenized.attention_mask.squeeze(0)

        #mask labels so loss is only computed on target tokens
        labels = input_ids.clone()
        prompt_len = len(self.tokenizer(prompt).input_ids)
        labels[:prompt_len] = -100  # ignore prompt tokens

        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": labels,
        }


def load_json_data(path: str | Path) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    data: List[Dict[str, Any]] = []
    if path.suffix in {".jsonl", ".json"}:
        with path.open() as f:
            if path.suffix == ".jsonl":
                current_json = ""
                in_json_block = False
                
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    if line.startswith("```json"):
                        in_json_block = True
                        current_json = ""
                        continue
                    elif line.startswith("```") and in_json_block:
                        if current_json.strip():
                            try:
                                parsed = json.loads(current_json.strip())
                                data.append(parsed)
                            except json.JSONDecodeError as e:
                                LOGGER.warning(f"Failed to parse JSON block: {e}")
                        in_json_block = False
                        current_json = ""
                        continue
                    elif in_json_block:
                        current_json += line + "\n"
                    elif line.startswith("{"):
                        try:
                            data.append(json.loads(line))
                        except json.JSONDecodeError as e:
                            LOGGER.warning(f"Failed to parse JSON line: {e}")
                
                if in_json_block and current_json.strip():
                    try:
                        parsed = json.loads(current_json.strip())
                        data.append(parsed)
                    except json.JSONDecodeError as e:
                        LOGGER.warning(f"Failed to parse final JSON block: {e}")
            else:
                parsed = json.load(f)
                if isinstance(parsed, list):
                    data.extend(parsed)
                else:
                    data.append(parsed)
    else:
        raise ValueError("Unsupported file type; expected .json or .jsonl")

    LOGGER.info("Loaded %d samples from %s", len(data), path)
    return data


def force_empty_gpu_cache():
    LOGGER.info("Force clearing GPU cache...")
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.reset_accumulated_memory_stats()
        allocated = torch.cuda.memory_allocated() / (1024**3)
        cached = torch.cuda.memory_reserved() / (1024**3)
        LOGGER.info(f"After clearing - Allocated: {allocated:.1f}GB, Cached: {cached:.1f}GB")


def ensure_full_weight_training(model):
    LOGGER.info(" Ensuring all model parameters are trainable for full weight training")
    trainable_params = 0
    total_params = 0
    
    for param in model.parameters():
        param.requires_grad = True
        total_params += param.numel()
        if param.requires_grad:
            trainable_params += param.numel()
    
    LOGGER.info(f" Trainable parameters: {trainable_params:,} / {total_params:,} ({100 * trainable_params / total_params:.1f}%)")


'''
def freeze_lower_layers(model, train_last_n: int = 0):
    if train_last_n <= 0:
        LOGGER.info(" Training all layers (train_last_n_layers <= 0)")
        return

    layers = None
    if hasattr(model, 'model') and hasattr(model.model, 'layers'):
        layers = model.model.layers  
    elif hasattr(model, 'transformer') and hasattr(model.transformer, 'h'):
        layers = model.transformer.h  
    elif hasattr(model, 'encoder') and hasattr(model.encoder, 'block'):
        layers = model.encoder.block 
    
    if layers is None:
        LOGGER.warning("Could not locate transformer layers for freezing")
        return

    total_layers = len(layers)
    train_from = max(0, total_layers - train_last_n)
    LOGGER.info(f" Freezing first {train_from} / {total_layers} layers -> training last {train_last_n} layers")
    
    for idx, layer in enumerate(layers):
        req_grad = idx >= train_from
        for param in layer.parameters():
            param.requires_grad = req_grad

'''
def freeze_layers_old_approach(model, n_layers: int, train_embeddings: bool = False):
    if n_layers <= 0:
        return

    # try general structures
    transformer_layers_paths = [
        ("model.layers", "Llama/OPT style"),
        ("transformer.h", "GPT-style"),
        ("encoder.block", "T5/EncoderDecoder style"),
    ]

    for attr_path, style in transformer_layers_paths:
        obj = model
        for attr in attr_path.split('.'):
            if hasattr(obj, attr):
                obj = getattr(obj, attr)
            else:
                obj = None
                break
        if obj is not None and isinstance(obj, (list, torch.nn.ModuleList)):
            LOGGER.info(f" Freezing first {n_layers} layers at path {attr_path} ({style})")
            for layer in obj[:n_layers]:
                for param in layer.parameters():
                    param.requires_grad = False
            break
    else:
        LOGGER.warning("Could not locate transformer layers to freeze; skipping")

    if not train_embeddings:
        embedding_paths = ["embed_tokens", "wte", "shared"]
        for ep in embedding_paths:
            if hasattr(model, ep):
                emb = getattr(model, ep)
                for p in emb.parameters():
                    p.requires_grad = False
                LOGGER.info(f" Froze embedding layer: {ep}")
                break


def get_optimal_batch_settings(model_size_gb: float = None):
    if not torch.cuda.is_available():
        return 2, 1
    
    gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    LOGGER.info(f"Detected GPU memory: {gpu_mem:.1f}GB")
    
    if model_size_gb is None:
        if "7b" in str(model_size_gb).lower():
            model_size_gb = 13  
        elif "13b" in str(model_size_gb).lower():
            model_size_gb = 26  
        else:
            model_size_gb = 15 
    
    if gpu_mem >= 80:  
        if model_size_gb <= 15:  
            return 2, 32
        else: 
            return 1, 64
    elif gpu_mem >= 40: 
        if model_size_gb <= 15:
            return 1, 64
        else:
            return 1, 128
    elif gpu_mem >= 24:  
        return 1, 128
    else:
        return 1, 256


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    if not torch.cuda.is_available():
        LOGGER.warning("CUDA not available. Training will be very slow on CPU.")
    else:
        gpu_count = torch.cuda.device_count()
        LOGGER.info(f"Detected {gpu_count} GPU(s)")
        for i in range(gpu_count):
            prop = torch.cuda.get_device_properties(i)
            LOGGER.info(f"GPU {i}: {torch.cuda.get_device_name(i)} ({prop.total_memory/1024**3:.1f}GB)")
    
    force_empty_gpu_cache()

    # prepare datasets (load once, reuse across models)
    train_data = load_json_data(args.train_file)

    eval_data = None
    if args.eval_file:
        eval_data = load_json_data(args.eval_file)

    for model_path in args.model_paths:
        LOGGER.info(f"\n=========== Fine-tuning model {model_path} ===========")

        #(re)load tokenizer & model for each iteration to avoid weight leakage
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        #load model with optimizations
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            low_cpu_mem_usage=True,
            use_cache=False,
        )

        #ensure full weight training
        if args.full_weight_training:
            ensure_full_weight_training(model)

        #apply layer freezing
        # if args.train_last_n_layers > 0:
        #     freeze_lower_layers(model, args.train_last_n_layers)
        elif args.freeze_n_layers > 0:
            freeze_layers_old_approach(model, args.freeze_n_layers, train_embeddings=args.train_embeddings)

        model.gradient_checkpointing_enable()
        if hasattr(model.config, "use_cache"):
            model.config.use_cache = False

        batch_size = args.per_device_train_batch_size
        grad_accum = args.gradient_accumulation_steps
        
        if batch_size is None or grad_accum is None:
            auto_batch, auto_grad = get_optimal_batch_settings()
            if batch_size is None:
                batch_size = auto_batch
            if grad_accum is None:
                grad_accum = auto_grad
            LOGGER.info(f"Auto-selected: batch_size={batch_size}, gradient_accumulation_steps={grad_accum}")

        train_ds = CodeFixDataset(train_data, tokenizer, max_length=args.max_length)
        eval_ds = (
            CodeFixDataset(eval_data, tokenizer, max_length=args.max_length) if eval_data else None
        )

        data_collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)

        #sub-directory inside output_dir for each model (use folder name)
        model_slug = Path(model_path).name.replace("/", "_")
        out_dir = Path(args.output_dir) / model_slug
        out_dir.mkdir(parents=True, exist_ok=True)

        #enhanced training arguments for full weight training
        training_args = TrainingArguments(
            output_dir=str(out_dir),
            overwrite_output_dir=True,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=args.per_device_eval_batch_size,
            learning_rate=args.learning_rate,
            num_train_epochs=args.num_train_epochs,
            gradient_accumulation_steps=grad_accum,
            weight_decay=args.weight_decay,
            warmup_ratio=args.warmup_ratio,
            max_grad_norm=args.max_grad_norm,
            eval_strategy="steps" if eval_ds is not None else "no",
            eval_steps=500 if eval_ds is not None else None,
            logging_steps=args.logging_steps,
            save_strategy="epoch",
            save_total_limit=args.save_total_limit,
            seed=args.seed,
            bf16=torch.cuda.is_available(),  #use bfloat16 if GPU available
            gradient_checkpointing=True,
            dataloader_pin_memory=False,
            remove_unused_columns=False,
            ddp_find_unused_parameters=False,
            optim="adafactor",  #used because memory efficient
            report_to="wandb" if args.use_wandb else "none",
            run_name=f"sft_{model_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}" if args.use_wandb else None,
        )

        try:
            trainer = Trainer(
                model=model,
                processing_class=tokenizer,
                args=training_args,
                train_dataset=train_ds,
                eval_dataset=eval_ds,
                data_collator=data_collator,
            )
        except TypeError:
            trainer = Trainer(
                model=model,
                tokenizer=tokenizer,
                args=training_args,
                train_dataset=train_ds,
                eval_dataset=eval_ds,
                data_collator=data_collator,
            )

        force_empty_gpu_cache()
        
        if args.resume_from_checkpoint:
            trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
        else:
            trainer.train()
        
        trainer.save_model()
        tokenizer.save_pretrained(str(out_dir))
        LOGGER.info(f"Finished fine-tuning {model_path}. Saved to {out_dir}")

        del model
        del trainer
        force_empty_gpu_cache()


if __name__ == "__main__":
    main() 