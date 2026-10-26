
# Generator family evaluation protocol

This document describes the evaluation protocol. Amendments approved during execution are listed in [protocol_amendments.md](protocol_amendments.md); a frozen manifest and its bound source take precedence over this overview.

## Research question and scope

Evaluate whether one shared generator-source edit improves circuit-level post-extraction performance across a declared family while preserving previously passing configurations. The study treats code, parameter configurations, a fixed PDK version, and an immutable reference-netlist binding as separate objects. Existing provenance, repair, surrogate ranking, counterexample search, and optimization methods retain their attribution in the related-work section of the paper.

The working title is *The Code Behind the Layout: AI Agents for Analog Layout Generators*. The eventual manuscript targets an IEEE conference format with at most five pages through the conclusion, followed by references. Author metadata is unconfirmed; any initial review manuscript will be anonymous.

## Physical contract

For each legal configuration, freeze its reference netlist, intended devices and sizes, ports, design intent, testbench, metric directions, limits, objective, and physical corners before formal evaluation. A sizing configuration has its own reference-netlist binding. Editing the evaluator, specification, PDK deck, or reference netlist is outside the policy action space.

S0 requires successful execution and GDS output. S1 additionally requires DRC, LVS, device and size checks, port checks, and design-intent checks. S2 additionally requires actual resistance and capacitance extraction plus converged, electrically valid simulations meeting every declared specification at every required corner. Missing information is a failure to establish the tier. DRC/LVS cleanliness alone does not imply circuit performance.

The device check expands literal parallel multiplicity and compares a colored device/terminal graph against the independent configuration reference. It preserves each finger's model, W/L and nf, the external port identities, MOS gate/bulk roles and MIM plate roles; internal net names may change and MOS drain/source may swap. A global width sum or global device multiset cannot substitute for branch-specific correspondence. `src/device_intent.py` implements this additional check; Netgen remains independently required. The initial raw-record `checks.devices/ports/intent` flags inherited LVS cleanliness, so those flags alone are insufficient for formal admission. A retrospective audit passed all 135 completed S1 train records observed at 02:38 UTC; uncompleted records were not classified. `TrustedPhysicalStore` now independently audits the raw netlists, and pretraining data preparation must readmit original candidates with the current gate instead of trusting older derived T1–T4 files.

Coverage is the fraction of the full declared configuration domain satisfying S2. Regression is the fraction of configurations that originally satisfied S2 and fail S2 after editing; when the baseline passes none, regression is undefined. Preserve timeouts and failed attempts in denominators. Optimize one declared objective only after feasibility constraints are met. Use applicable mirror metrics for mirrors and OTA metrics for OTAs.

Actual SKY130 development flows use tt, ss and ff at 27°C and 1.8V: process-corner checks, not a full voltage/temperature signoff. Task-specific loads, biases, specifications and legal domains must be frozen separately. Geometry symmetry cannot establish mismatch yield. Finite samples establish empirical coverage of the declared domain, without formal guarantees over a continuous parameter space.

## Inventory and development pilot

The first remote action is read-only environment and project discovery. Locate existing project README/config files, tools, PDKs, extraction decks, private TRV implementation, and checkpoints through the relevant project paths. Preserve existing jobs. Do not infer an H100, installed PDK, or private source checkout from the reference document.

Run a device, current mirror, and electrically biased OTA through generation, DRC, reference-bound LVS, RC extraction, and SPICE. Save commands, tool versions, raw logs, GDS, extracted netlists, model includes, port order, units, and operating-point evidence. Verify extracted R and C explicitly. Separate infrastructure faults from candidate failures. A public tool failure demonstrated by a read-only gold smoke test pauses the affected batch; agent-generated bad code remains a trial failure.

Development tasks used to debug the harness stay outside formal results. Measure tool throughput and valid data yield before choosing budgets and sample counts. No synthetic oracle or imported paper number can replace a physical pilot.

## Data and evaluation isolation

`data/splits/registry.json` is the common assignment registry. Group by actual source ancestry and independent generator lineage; record topology families and shared primitive libraries. Parameter variants, copied code, and injected reversals do not create independent lineages. Check ancestry and normalized source similarity after sources exist. The software detects duplicate lineage assignments and mixed-compiler held-out topology contamination. Actual dependency/ancestry inspection is in docs/source_group_partition.md; full import/AST comparisons are in results/derived/research_source_comparison.json. The frozen E3 inventory has eight high-level-logic groups and a seven-group merge sensitivity. All24 source states generated, all references/domains qualified and each state has an actual feasible source witness. Initial editing-state checks returned23S2 and one complete LVS failure;14 states have actual non-injected shortfalls. Generation alone is not task admission.

Reserve configuration holdouts and complete topology holdouts. The main24-task E3 matrix covers eight high-level groups with the ancestry sensitivity above, four topology families and two held-out topology families. Each task binds one anchor, eight visible development configurations and sixteen hidden configurations. At least half have actual natural failures or performance shortfalls. The two main research OTAs have their original complete three-corner electrical benches. Refer to the frozen manifest for exact task identities, configuration strata, budgets and qualification evidence.

Formal E1/E2/E3 evaluation lineages and outcomes cannot become E4 training data or selector calibration. Keep hidden data outside the model filesystem or behind an actual tool gateway. Prompt instructions alone do not constitute a sandbox. After methods freeze, run hidden evaluation once without feeding results back to the tested policy. Log explicit rerun reasons and preserve the original trial.

## Experimental comparisons

| Experiment | Controlled comparison | Required evidence |
| --- | --- | --- |
| E1 | Same GPT and task at geometry G0, PCell G1, and generator G2 levels | S0/S1/S2 and resource curves; reuse and composition strata; target 24 tasks × 3 methods × 5 fresh trials; a six-task second-framework check if a real physical flow exists |
| E2 | Geometry/RC proxies, actual PEX/SPICE, fixed and adaptive promotion | Target 4 OTA lineages × 3 sizings × 64 distinct candidates; correlations and reversal rates; finite-pool regret; six real online tasks; full failure accounting |
| E3 | Anchor A, random regression R, boundary regression B, contract-guided C | Target 24 tasks × 4 methods × 5 trials; freeze one patch before hidden testing; equal verification resources for R/B/C; instance baseline I and parameter baseline P on at least 8 common tasks |
| E4 | Base T0, Point-SFT T1, Family-SFT T2, Point-DPO T3, Family-DPO T4 | Real tool-approved targets; matched samples/tokens/updates; at least 3 actual training seeds per T1–T4; T3/T4 start from corresponding identical T1; selection uses validation tasks |
| E5 | Shared editing and instance-specific work at comparable measured quality | Event-derived data generation, failed jobs, training, search, verification, inference, queue and wall/resource costs; empirical reuse sequence and fallback costs |

Mandatory explanatory comparisons separate test-configuration selection, fidelity promotion, data selection, preference learning, and parameter optimization. Split natural/injected failures, correctness/performance tasks, and in-domain/OOD results. Retain a case of successful family transfer, an anchor repair causing regression, and a case where parameters suffice or framework actions limit solutions. Select cases with frozen rules.

## Models and training

Engineering and tested policy roles remain distinct. Formal GPT trials require fresh sessions with explicit task packets and structured actions. Record the actual visible model identity, settings, date, allowed APIs, feedback, tool events, and public usage metadata. Do not infer hidden reasoning or billable tokens. Development collaboration and isolated GPT calibration sessions are labelled separately and excluded from formal results and training.

Qwen2.5-Coder-32B-Instruct revision `381fc969f78efac66bc87ff7ddeadb7e73c218a7` (Apache-2.0) is the local base model. The prospective common context for E1, E3 and E4 is 16,384 tokens with 1,024 output tokens; full source and feedback are not truncated. T1/T2 share candidate sources and compute budgets; T3/T4 share their starting T1 checkpoint and matched DPO budgets.

## Statistics and costs

Use task-paired comparisons, lineage-cluster bootstrap 95% intervals, and per-family distributions. Keep training-seed variation separate from task/lineage variation. Configurations and repeated inference trials do not increase the count of independent circuits. Predeclare C vs R/B and T4 vs T3, T2 vs T1 as primary comparisons. Treat other comparisons as explanatory.

Report budgeted success curves or restricted means including timeout and failure outcomes. Cost units are wall time, CPU resource time, GPU hours, verification counts, and visible text scope. Dollar costs require observed billable usage and verified prices; subscription limits and visible tokens do not establish a bill. Estimate break-even only for comparable quality with positive observed savings, including deployment verification and fallback.

## Freeze and execution gates

Freeze only after a functioning physical flow, feasible tasks, source-grouped splits, an isolated model interface, calibrated budgets and validated measurement adapters are available. Snapshot the protocol, split assignments, configs, committed source, model revisions and analysis scripts before formal testing. E1scope is bound to revision63d3318; E3main/F3 to5856568. E3 uses matched 16k/1,024-token, 8 full/8 patch/24 decision/4 hour searches. Shared hidden release precedes independent instance deployment.

Standalone scripts implement the frozen E1/E3 suites, physical collection, data admission, training, task materialization, analysis and figures. Fixed identities are reserved before launch; no automatic replacement trial is permitted.
