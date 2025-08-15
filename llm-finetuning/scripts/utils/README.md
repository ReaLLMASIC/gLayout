# llm-finetuning/utils

This folder contains two files, namely:
1. `convert_training_data.py`
2. `metrics_output.py`

------------------------------------------------------------------

## convert_training_data.py

This file is to convert the individual JSONs received from the master model, saved in single files, to combine them into one single `.json/.jsonl` file, so that training can be done efficiently.
It creates a clean jsonl, since there are some files which have json issues, such as non-terminating/incomplete files, or other errors.


## metrics_output.py

This script generates plots and metrics for the entire run, calculating custom metrics based on pre-defined scores.

1. Compilation checks (python -m py_compile) \
Represents syntactical correctness, since the score is boolean. (0 for failure, 1 for compilation)
2. Code length \
Counts the number of non-empty lines in the code, returns an integer
3. Relevance Score \
Matches code against PATTERNS dict regexes (e.g., imports of gdsfactory/glayout, function named flipped_voltage_follower, transistor instantiation, routing calls, port additions, netlist creation). \
Metric: (number of patterns matched) ÷ total patterns × 5  (returns a normalized score).
4. Complexity Score \
Control_structures: count of `if`, `for`, `while`, `try`, `with`. \
Functions: count of `def`. \
Classes: count of `class`.
5. Composite Score \
It is a weighted combination of the compilation rate (weight 0.4), and the relevance score normalized to 0–1 (weight 0.6). \
Outputs a float (0–1).
6. Also outputs correlation matrix, and a bunch of graphs.