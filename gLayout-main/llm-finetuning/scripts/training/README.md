# llm-finetuning/training

This folder contains two files, namely: 
1. `gpu_finetune.py`
2. `train.py`

------------------------------------------------------------------

## gpu_finetune.py

This script is to finetune the models, based on input data, which is receieved from the processing pipeline.
It automatically distributes training across all available GPUs, if multiple are available.
The user can use `--training_data_dir` to specify the directory to retrieve data from, and `--train_last_n_layers` to choose how many layers to train.
The above step is done to prevent catastrophic forgetting, and to maintin the model's general ability to code and understand syntax.
If, some transformer layers aren't frozen, the model tends to overfit on certain phrases/data, and provide repetitive outputs.

# train.py

Though it has overlapping functionality with `gpu_finetune.py` (since it is also training models), this is finetuning the models, AFTER inferring from the master model.
`train.py` 
Dataset format (JSON per line or list of JSON objects):
```
{
  "filename": "example.py",
  "analysis": [
    {
      "issue": "Brief description of issue #1",
      "explanation": {
        "problem": "What exactly is wrong?",
        "reason": "Why it's a problem",
        "fix": "How to fix it"
      }
    }
  ],
  "fixed_code": "<full corrected code>"
}
```

The script builds an input prompt from the first analysis item:
INPUT  =  "Filename: {filename}\nIssue: {issue}\nProblem: {problem}\nReason: {reason}\n### Fix:\n" \
OUTPUT =  "{fix}\n\n### Fixed Code:\n{fixed_code}"

It then fine-tunes the LLM. Conditionally finetuning the model, it learns to improve on certain metrics, and not make the same mistakes again and again.
