import os
import gc
import torch
import argparse

from datetime import datetime
from datasets import load_from_disk
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
)


MODEL_MAPPINGS = {
    "7b": "codellama/CodeLlama-7b-Instruct-hf",
    "13b": "codellama/CodeLlama-13b-Instruct-hf", 
    "7b-ft": "./models/7b_finetuned",  
    "13b-ft": "./models/13b_finetuned",  

}

def resolve_model_path(model_input: str) -> str:
    if model_input in MODEL_MAPPINGS:
        resolved = MODEL_MAPPINGS[model_input]
        print(f"Resolved model '{model_input}' → '{resolved}'")
        return resolved
    else:
        print(f"Using direct model path: '{model_input}'")
        return model_input


# muting wandb outputs
os.environ.setdefault("WANDB_SILENT", "true")
os.environ.setdefault("WANDB_CONSOLE", "off")

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True,max_split_size_mb:256"


def force_empty_gpu_cache():
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.reset_accumulated_memory_stats()


def ensure_trainable(model):
    for p in model.parameters():
        p.requires_grad = True



def freeze_lower_layers(model, train_last_n: int = 0):
    # freezing last n layers in the model, to prevent complete loss of it's ability to code in general
    if train_last_n <= 0:
        print(" Training all layers (train_last_n_layers <= 0)")
        return
    total_layers = len(model.model.layers)
    train_from = max(0, total_layers - train_last_n)
    print(f" Freezing first {train_from} / {total_layers} layers.")
    for idx, layer in enumerate(model.model.layers):
        req_grad = idx >= train_from
        for p in layer.parameters():
            p.requires_grad = req_grad



def main(
    model: str = "13b",
    training_data_dir: str = None,
    output_dir: str = "./final_model", 
    checkpoint_dir: str = "./checkpoints",
    num_train_epochs: int = 3, 
    resume_from_checkpoint: str | None = None, 
    train_last_n_layers: int = 0
) -> None:
    model_path = resolve_model_path(model)
    print(f" Fine-tuning model: {model} → {model_path}")
    
    if training_data_dir is None:
        model_suffix = model.replace("/", "_").replace(":", "_")
        training_data_dir = f"training_data_{model_suffix}"
    
    print(f" Using training data from: {training_data_dir}")
    
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available – need GPUs!")

    n_gpu = torch.cuda.device_count()
    print(f" Detected {n_gpu} CUDA device(s)")
    for idx in range(n_gpu):
        props = torch.cuda.get_device_properties(idx)
        print(f"  GPU {idx}: {torch.cuda.get_device_name(idx)} ({props.total_memory/1024**3:.1f} GB)")

    if not os.path.exists(training_data_dir):
        raise FileNotFoundError(f"Training data directory not found: {training_data_dir}\nRun: python process_data.py --model {model}")
    
    dataset = load_from_disk(training_data_dir)
    split = int(0.9 * len(dataset))
    train_ds, eval_ds = torch.utils.data.random_split(dataset, [split, len(dataset) - split])

    force_empty_gpu_cache()

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    tokenizer.pad_token = tokenizer.pad_token or tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="auto",   # hf accelerate spreads layers across the visible GPUs
        low_cpu_mem_usage=True,
        use_cache=False,
    )

    ensure_trainable(model)
    model.gradient_checkpointing_enable()
    if hasattr(model.config, "use_cache"):
        model.config.use_cache = False

    per_gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
    if per_gpu_mem >= 80:
        batch_size = 2
        grad_accum = 32  # effective 64 tokens per update
    elif per_gpu_mem >= 40:
        batch_size = 1
        grad_accum = 64  # effective 64 tokens per update
    else:
        batch_size = 1
        grad_accum = 128

    print(f" Training settings → batch {batch_size} × accum {grad_accum}")

    # Create output directories if they don't exist
    os.makedirs(checkpoint_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    args = TrainingArguments(
        output_dir=checkpoint_dir,
        overwrite_output_dir=True,
        num_train_epochs=num_train_epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=grad_accum,
        learning_rate=3e-5,
        weight_decay=0.1,
        warmup_ratio=0.1,
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="steps",
        eval_steps=500,
        bf16=True,
        gradient_checkpointing=True,
        optim="adafactor",
        ddp_find_unused_parameters=False,
        run_name=f"finetune_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        report_to="wandb",
        save_total_limit=2,
    )

    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        tokenizer=tokenizer,
        data_collator=collator,
    )

    force_empty_gpu_cache()
    freeze_lower_layers(model, train_last_n_layers)
    trainer.train(resume_from_checkpoint=resume_from_checkpoint) if resume_from_checkpoint else trainer.train()

    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f" Model saved to {output_dir}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Fine-tune language models with customizable parameters")
    p.add_argument("--model", type=str, default="13b", 
                   help="Model name or path to fine-tune (default: 13b)")
    p.add_argument("--training_data_dir", type=str, default=None,
                   help="Directory containing training data (default: auto-determined)")
    p.add_argument("--output_dir", type=str, default="./final_model",
                   help="Directory to save the final fine-tuned model (default: ./final_model)")
    p.add_argument("--checkpoint_dir", type=str, default="./checkpoints",
                   help="Directory to save training checkpoints (default: ./checkpoints)")
    p.add_argument("--num_train_epochs", type=int, default=3,
                   help="Number of training epochs (default: 3)")
    p.add_argument("--resume_from_checkpoint", type=str, default=None,
                   help="Path to checkpoint to resume training from")
    p.add_argument("--train_last_n_layers", type=int, default=3,
                   help="Number of last layers to train (0 = train all layers, default: 3)")
    
    parsed = p.parse_args()
    main(
        model=parsed.model,
        training_data_dir=parsed.training_data_dir,
        output_dir=parsed.output_dir, 
        checkpoint_dir=parsed.checkpoint_dir,
        num_train_epochs=parsed.num_train_epochs,
        resume_from_checkpoint=parsed.resume_from_checkpoint,
        train_last_n_layers=parsed.train_last_n_layers
    ) 