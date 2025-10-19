# llm-finetuning/runnables

This folder contains two files, namely:
1. `compile_outputs.py`
2. `generate_and_compile.py`

----------------------------------------------------------------------------------

## compile_outputs.py

This file compiles the files generated from inference, from the `run_base_inferences.py` file. The files then create output logs, which are saved with the same names as the generated PCell python files. 
For example, `AND.py` is compiled, and the terminal output after compilation (error/success/other) is saved in `AND.log`, or `AND.txt`.

The files are compiled using py_compile.

## generate_and_compile.py

Similar to the `compile_outputs.py` file, this file also compiles the generated files from the model, it has the added functionality of inferring from the model as well. 
It does this by referring the flags passed to this file to `run_inferences.py`, so that two steps can be combined into one for the convenience of the user.