# How to Run the Transmission Gate Dataset Generation

Working in progress...

AL: Sep 29 2025

Migrated from Arnav's fork of OpenFASOC with my own modifications...
- A lot of effort is needed to make it compatible with latest new gLayout repo
- Not tested yet

```bash
./run_dataset_multiprocess.py params_txgate_100_params/txgate_parameters.json --n_cores 110 --output_dir tg_dataset_1000_lhs
```