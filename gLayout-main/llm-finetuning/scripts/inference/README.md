# llm-finetuning/inference

This folder contains two files, namely:
1. `master_inference.py`
2. `run_base_inferences.py`

----------------------------------------------------------------------------

## master_inference.py:

This file does inference from the master model, passing input to the model as `{code, compile output}`, and the received output from the master model (gemini 2.5-pro in our case), is in the format:
```
{
       "filename ":  "example.py ",
       "analysis ": [
        {
           "issue 1":  "Brief description of issue #1 ",
           "explanation ": {
             "problem ":  "What exactly is wrong? (e.g., 'Uses = instead of == in condition') ",
             "reason ":  "Why it's a problem (e.g., 'Will cause always-true condition and logic error') ",
             "fix ":  "How to fix it (e.g., 'Use == instead of =') "
          }
        },
        {
           "issue 2":  "Brief description of issue #2 ",
           "explanation ": {
             "problem ":  "Explain the second problem here... ", n"
             "reason ":  "Why it causes a bug, bad output, or violates best practices... ",
             "fix ":  "Correction needed... "
          }
        }
      ],
       "fixed_code ":  "'''Insert the full corrected code as a string here. Use   n for line breaks and escape characters as needed.''' " n"
    }
```

This output, is then used as a labelled dataset, to finetune(SFT) our LLM.
For the proper functioning of this file, the api key must be passed as env variable GOOGLE_API_KEY, or passed via `--api_key`
Passing `finetuned` adds extra context, to aid generation and make better fixes.



### run_base_inference.py:

This file, is used to infer outputs from the base/finetuned models, where the input prompt is:
```
<s>[INST] <<SYS>>
You are PCELL-GPT, a Python-3 code generator.
Return ONLY a single python code block; do NOT add commentary, do not use placeholders.
Code **must** compile under `python -m py_compile`.
<</SYS>>
TASK: Implement a flipped voltage follower layout using gdsfactory/glayout utilities.
[/INST]
```
(Since this is an -instruct model, the ['/INST'] tags are necessary.)

Additionally, there is an "instructions" file, passed as context along with prompt.txt, which are manually written instructions on how to write code for a PCell. 
The instructions.txt file is available in the path: `sh glayout/llm-finetuning/scripts/utils/instruction.txt`
You will find the prompt.txt file in the same directory.
