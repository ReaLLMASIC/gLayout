# Data

## Where things are

```
benchmarks/textbook_sharing/
  data/                        inputs (in git)
    cases.tar.xz               the case folders, packed (unpack with tar -xJf data/cases.tar.xz)
    cases/<C>/<pdk>/<size>/    after unpacking: one folder per request that passed the size derivation (639)
    nominal/<C>/<pdk>.json     nominal design point (sW = sL = 1) of every topology and PDK (54)
    frozen/fixed_order.json    the fixed mode order, frozen from the development sizes
    res_calibration.json       calibration of the resistor length formula (calibrate_res.py)
  results/                     outputs behind every reported number (in git)
    case_build.json            one record per request (648)
    count_ledger.json, .md     mutually exclusive counts (analysis/ledger.py)
    analysis/*.json            analysis tables (below)
    redesign_search/           bounded redesign search of the class-AB stage (redesign_search.py)
    run_records.tar.xz         run records: JSON and model text (17 353 files)
  runs/                        not in git: the unpacked run records, or new runs (TSB_RUNS)
  docs/                        this documentation; PARAMETER_SPACE.md and RESULTS.md are generated
```

The case folders and the run records are packed into two archives because they hold thousands of small files;
unpack both before running anything.  After `build_cases` has rewritten the case folders, pack them again with
`tar --sort=name --mtime="2026-10-12 00:00Z" --owner=0 --group=0 --numeric-owner -cJf data/cases.tar.xz data/cases`.

`TSB_RUNS` and `TSB_RESULTS` move the run and result folders (`textbook_sharing/paths.py`).  Records store paths
relative to these roots (`runs/...`, `data/...`), never machine paths.

## A case folder

`data/cases/C08/sky130/sW1_sL1/`:

| file | content |
|---|---|
| `case.json` | topology, PDK, size point (sW, sL), sizing per device (`w`, `l` in um, `nf`), supply, bias (replica generators: device and current), load, category, notes, and `derivation`: how each device was scaled from the nominal point (`w0`, `l0`, `nf0`, unit widths, ratios) |
| `specs.json` | the frozen specification (`min` / `max` / `abs_max` per metric) and `_frozen_from`: schematic values, floors and rule |
| `qualification.json` | schematic simulation result, measures, qualification decision with reasons, `signature` (identity of the derived netlist) and `testbench_rule` |
| `target.spice` | the DUT subcircuit for simulation |
| `target_lvs.spice` | the DUT subcircuit for LVS |
| `testbench.spice` | the testbench written by `testbench.py` |
| `manifest.json` | sha256 of every file above |

`testbench_rule` is the hash of `testbench.py`.  `build_cases.py` qualifies a case again when the rule changes, so an
edit of `testbench.py` (even a comment) means re-running `build_cases` and the post-layout simulations (`resim.py`).

`results/case_build.json` holds one record per request, including the 9 parameter-illegal ones that have no folder:
`stage` is `parameter_illegal`, `schematic_not_qualified` or `qualified`.

## Run records (`runs/`, from `results/run_records.tar.xz`)

```
grid/<C>/<pdk>/<size>/<mode>/result.json                  main grid: qualified case x named mode
grid/.../<mode>/verify/review/review_record.json           its visual-review record
selection/<task>/catalogue.json                            per-group candidate tables and the sampled catalogue
selection/<task>/estimates.json                            cost-rule estimate of every catalogue entry
selection/<task>/<candidate>/result.json                   every catalogue candidate, fully verified
models/<model_tag>/<task>/r<rep>/                          model sessions (docs/MODELS.md)
model_tasks/, model_examples/                              what the models were given, and the example runs
review/batch_<nnn>/manifest.json, outputs.json             review batches and the reviewer's raw verdicts
```

### `result.json` (one layout)

| field | content |
|---|---|
| `case_id`, `case_dir`, `mode`, `label` | which case and which named mode or candidate |
| `applied_plans` | per sharing group: `devices`, `plan` (the canonical `SharingPlan` with `plan_id` and `mode_label`), `plan_source` (`named`, `named_fallback_independent`, `explicit`) |
| `evidence` | per group, measured on the drawn rectangles: active islands, cross-device shared diffusion nodes (net, terminals), shared gate conductors |
| `assembly_stats` | `width`, `height`, `area_um2` of the bounding box; `row_dims` (per row: kind, width, height, tap extent, cells); `channel_heights`; `channel_strategy` (`shared` or `split`) and the area of both trials; `row_x_shift`; trunk, riser and via counts |
| `geometry_hash` | hash of the merged shapes on every layer, independent of the cell name (identical layouts share it) |
| `verify` | status of every verification stage (`drc`, `drc_magic`, `lvs`, `constraints`, `pex`, `physical`) |
| `postsim` | post-layout simulation: `status`, `measures`, per-specification results (`spec`) |
| `postsim_history` | earlier simulations of the same extracted netlist, kept when a testbench fix re-ran the simulation |
| `matching` | declared matching checks: ratio (pass/fail), orientation balance and centroid offset (reported) |
| `area_um2` | bounding-box area measured on the GDS |
| `primary_status`, `fail_reasons` | first failing stage and every failing stage |
| `timing_s` | wall time per stage |
| `review_id` | link to the visual-review record |

### Plan labels (`mode_label`)

* `independent`: every transistor on its own (fingers of one transistor share diffusion, one strap per transistor);
* `axes:<arrangement>,<orientation>,<diffusion>,<gate>,<strap_start>,<contact_end>`: a plan from the six-axis
  enumeration; a named mode adds its name in front (`combined:axes:...`);
* `llm:SharingPlan`, `llm:axis_plan`, `llm:fet_row`: a plan written by a model in one of the interface forms.

### `review_record.json`

`review_id`; `gds_sha256`, `target_sha256`, `pdk`; `static_checks` (the automatic geometry checks); `visual`: reviewer
type and id, at least three observations with coordinates, issue locations, `verdict` (`pass`, `suspicious`,
`fail`, or `review_pending`), the reviewed image hash and batch, and `reused_from` when the verdict was given to an
identical layout; `visual_resolution` (outcome, note, evidence, by) for flagged verdicts settled by objective checks;
`composite`: the reviewed images and their hashes.

## Result tables (`results/analysis/`)

| file | made by | content |
|---|---|---|
| `benchmark_table.json` | `analysis.benchmark_table` | per topology: devices, groups, plan counts, request outcomes, applicable modes, study membership |
| `cost_decomposition.json` | `analysis.cost_decomposition` | every main-grid pair (mode vs unshared): W, H, area terms, classes; summaries by mode, topology, PDK; `increase_mechanisms` |
| `cost_validation_dev.json`, `_dev_no_channel.json`, `_heldout.json` | `analysis.cost_validation` | cost-rule predictions vs measured area per pair, sign accuracy, error types |
| `selection_summary.json` | `analysis.selection` | per task and method: best area after n verifications, gap, time; balanced means and bootstrap intervals |
| `timing_controlled.json` | `selection.timing` | geometry build times measured one candidate at a time |
| `llm_summary.json` | `analysis.models` | per model session: proposals, legality, statuses, best area after k proposals, usage |
| `llm_interface.json` | `analysis.interface` | sharing vs base interface on the 14 tasks; capability bound |
| `scope_audit.json` | `analysis.scope` | task sets; same-task comparison against both references; interface comparison |
| `agent_session_audit.json` | `llm.agent_sessions audit` (machine paths removed) | tool-call audit of the agent sessions, launch texts, token usage |
| `running_example.json` | `analysis.example` | the five OTA layouts of the running example |
| `arrangement_bandwidth_C16.json` | `analysis.arrangement_bandwidth` | bandwidth by finger arrangement in the resistor-loaded pair |
| `pvt.json` | `analysis.pvt` | corner simulations of reference, combined and best layouts |
| `pex_sensitivity_C10_gf180.json` | `analysis.pex_sensitivity` | R+C vs C-only extraction of the fully differential OTA before its testbench fix |
| `resim_after_testbench_fix.json` | `resim` | status changes when the post-layout simulations were repeated with the final testbenches |
| `review_coverage.json` | `analysis.review_coverage` | effective visual verdicts of every reported set |
| `review_gate_pad_check.json`, `review_connectivity_check.json` | `review.check_gate_pads`, `review.check_connectivity` | the objective checks cited as evidence when flagged visual verdicts were resolved |
| `testbench_equivalence.json` | one-off check when this package was assembled | the decks in `data/cases`, written by this repository's `testbench.py`, equal the decks of the recorded runs apart from comment lines |
| `repro_clean_<time>.json` | `scripts/reproduce_clean.sh` | clean-checkout rebuild of a few cases vs the records |
| `geometry_check.json` | `analysis.geometry_check` | every recorded layout rebuilt (geometry only) with this code: hash and bounding-box comparison |
| `geometry_check_diagnosis.json` | one-off check when this package was assembled | for the layouts whose hash differs: per-layer comparison with the recorded GDS files and a full re-verification with this code |

## Not in the repository, and how to get it back

| item | how to regenerate |
|---|---|
| GDS files, extracted netlists, tool logs and reports | `python -m textbook_sharing.run_case <case_dir> <out> --from-record <result.json>` rebuilds and verifies one recorded layout; `analysis.geometry_check` rebuilds the geometry of all of them |
| rendered review images | `review/composite.py` on a review record (needs the GDS) |
| corner-simulation runs | `python -m textbook_sharing.analysis.pvt` |
| the prompts of the Codex calls | each is the concatenation described in `docs/MODELS.md` |
| Codex event logs and agent transcripts | not kept; their audits are in `session_done.json` and `results/analysis/agent_session_audit.json` |
