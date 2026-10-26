# The Code Behind the Layout

Code and frozen configurations for *The Code Behind the Layout: AI Agents for Analog Layout Generators*. The study asks a single question: does one shared edit to a gLayout generator's source improve post-extraction performance across a declared family of parameter configurations, while every configuration that passed before still passes? Every candidate is checked on SKY130: GDS generation, DRC, LVS against an independent reference, RC extraction, and SPICE at the tt/ss/ff corners.

Two frontier models act as the editing policy: Claude Opus 5.5 and GPT-6.1. A local Qwen2.5-Coder-32B-Instruct model is fine-tuned under point and family supervision, with SFT and DPO.

## Experiments

| | Question | Entry points |
| --- | --- | --- |
| E1 | Which action level works: geometry (G0), primitives (G1) or generator source (G2)? | `scripts/run_e1_scope_suite.py`, `scripts/opus_cohort/run_e1_scope_suite_opus_v2.py` |
| E2 | Which cheap signal ranks candidates before full evaluation: area, a geometric rule, extracted RC, or the calibrated interval F3? | `scripts/e2_four_source.py` |
| E3 | Which test rule finds family regressions within a fixed budget: A anchor, R random, B boundary or C risk? | `scripts/run_e3_suite.py`, `scripts/opus_cohort/run_e3_suite_opus.py` |
| E4 | Point vs. family supervision, SFT vs. DPO (T1–T4, seeds 41/73/109) | `scripts/train_policy.py`, `scripts/run_e4_*.sh`, `scripts/e4_checkpoint_validation.py` |
| E5 | Physical CPU, GPU and token cost per verified configuration | `scripts/analyze_e5_costs.py` |

The protocol is in [docs/protocol.md](docs/protocol.md), [docs/e1_protocol.md](docs/e1_protocol.md) and [docs/e3_protocol.md](docs/e3_protocol.md). The amendments are in [docs/protocol_amendments.md](docs/protocol_amendments.md). The S0/S1/S2 measurement interface is in [docs/measurement_interface.md](docs/measurement_interface.md).

## Layout

- `src/` contains the libraries: measurement and S0/S1/S2 assessment, trusted physical store, policy adapters, student interface, training, checkpoint selection and analysis.
- `scripts/` contains the scripts for task preparation, collection, freezes, suite runners, training, analysis and figures.
- `scripts/opus_cohort/` runs the frozen E1/E3 suites with the Claude Opus 5.5 policy.
- `configs/` contains the study definition, model configs, task preparations, frozen experiment manifests (`configs/experiments/frozen/`), training configs and the E4 pool declaration.
- `data/splits/`, `data/manifests/` contain the source-grouped split registry and the collection manifests.
- `reproducibility/glayout_fixes.patch` contains the gLayout fixes used by the E1–E3 circuits.
- `runtime/` contains the two qualified flow modules that the E2/E3 code loads. The data bundle below also extracts here.
- `tests/` contains the unit tests.

## Data bundle

The frozen task packets and the E4 training set are distributed separately (`cbl-data-v1.tar.gz`, about 400 MB unpacked):

```sh
bash scripts/fetch_data.sh
```

It extracts the following into this directory:

- `runtime/protocol_freezes/`: the frozen E1, E2 and E3 manifests with their task packets, registries, model configs, qualification and baseline plans. This includes the private evaluator side (references, benches, hidden configurations).
- `runtime/e4_validation_preparation/`, `runtime/e4_validation_tasks/`: the E4 checkpoint-validation plan, budget and the nine-point validation task.
- `data/training/e4_textbook_v1/`: the E4 training set (see its README).

## Environment

- **Analysis and unit tests.** Python 3.12:

  ```sh
  python3 -m pip install -r requirements.txt
  python3 -m unittest discover -s tests -p 'test_*.py'
  ```

- **Physical flow.** Runs on Linux with Magic, Netgen, ngspice and SKY130A. Two gLayout trees are used:
  - For E1–E3: gLayout at upstream commit `5af536b` with `reproducibility/glayout_fixes.patch` applied.
  - For the E4 textbook collections: the `glayout.sharing` module and the `textbook_sharing` benchmark from ReaLLMASIC/gLayout#127.
- **Training.** Needs one 80 GB GPU with PyTorch, Transformers, PEFT and bitsandbytes, and the base model `Qwen/Qwen2.5-Coder-32B-Instruct` at revision `381fc969f78efac66bc87ff7ddeadb7e73c218a7`.

The scripts that drive the server from a workstation use these placeholders. Recorded paths in the manifests use the same ones.

| Placeholder | Meaning |
| --- | --- |
| `cbl-server` | SSH host alias of the evaluation and training server (`~/.ssh/config`) |
| `~/.ssh/cbl_server_key` | SSH identity for that host |
| `/srv/code-behind-layout` | Location of this directory on the server |
| `GPT_CLI`, `CLAUDE_CLI` | Command-line clients for the two frontier policies (`src/model_adapter.py`, `src/opus_cli_adapter.py`) |

## Reproducing

**E1 and E3.** Run the suite runners against the frozen manifests:

```sh
python3 scripts/run_e1_scope_suite.py --manifest runtime/protocol_freezes/E1_scope_v2_16k/manifest.json --output runs/E1_gpt
python3 scripts/opus_cohort/run_e1_scope_suite_opus_v2.py --manifest runtime/protocol_freezes/E1_scope_v2_16k_claude_v2/manifest.json --output runs/E1_opus
python3 scripts/run_e3_suite.py --part gpt --manifest runtime/protocol_freezes/E3_primary_v2/manifest.json --output runs/E3_gpt
python3 scripts/opus_cohort/run_e3_suite_opus.py --part gpt --manifest runtime/protocol_freezes/E3_primary_v2_claude/manifest.json --output runs/E3_opus
```

E3 parts are `gpt` (the manifest's frontier policy under rules A/R/B/C), `parameter`, `signals`, `fidelity` (F3, with `E3_F3_primary`), `local` and `instance`. Each runner checks its freeze's bound implementation files before dispatch and reserves a trial identity before launch. Failures are recorded, never retried in place.

**E2.**

```sh
python3 scripts/e2_four_source.py run --manifest runtime/protocol_freezes/E2_four_source_primary/manifest.json --output runs/E2 --method {full_oracle,fixed_area,adaptive_geometry,fixed_rc_product,f3_calibrated} [--pool-id <pool>]
```

**E4.**

```sh
python3 scripts/train_policy.py --manifest data/training/e4_textbook_v1/training_manifest.json --method T1 --seed 41 --output checkpoints/e4_textbook_v1/T1/seed-41 --validate-only
bash scripts/run_e4_sft_training.sh data/training/e4_textbook_v1
bash scripts/run_e4_validation_selection.sh data/training/e4_textbook_v1 runtime/e4_validation_preparation/e4_textbook_v1_validation_plan_v2.json T1 41 runs/e4_validation_v2
bash scripts/run_e4_dpo_training.sh data/training/e4_textbook_v1 runs/e4_validation_v2/e4_textbook_v1/T1
```

`--validate-only` checks admission, the split registry and the samples without a GPU. T3/T4 use `training_manifest_dpo.json`. Checkpoints are selected by mean task S2 fraction on the nine validation points, with ties going to the earliest update; training loss is never used for selection. `scripts/assemble_e4_methods_draft.py` and `scripts/freeze_e4_methods.py` freeze the selected models, and `scripts/serve_frozen_policy.py` serves them to the E3 local-model part.
