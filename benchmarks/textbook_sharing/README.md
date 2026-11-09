# Explicit diffusion and gate sharing in gLayout: a three-PDK textbook benchmark

Base gLayout builds every transistor on its own: fingers of one transistor share diffusion, but two transistors never
share a diffusion node or a gate strap.  Analog layouts share both all the time: a differential pair and its tail
share one node, the transistors of a current mirror share their source and their gate.  This work adds such sharing to
gLayout as an explicit, checkable **sharing plan** (`src/glayout/sharing/`) and measures what it gains and what it
costs on 18 textbook circuits in SKY130, GF180MCU and IHP SG13G2, with the official DRC decks, LVS, R+C extraction
and post-layout simulation against frozen specifications.

## In one example

The five-transistor OTA in SKY130 (C08, nominal size) has two sharing groups: M1-M3 (NMOS) and M4, M5 (PMOS).  Its
unshared layout is 256.0 um^2.  Sharing the tail node net23 across M1-M3 narrows the NMOS row, which sets the width.
Sharing VDD in the PMOS group narrows a row that does not set the width, so the area stays the same.  One gate strap
for M4 and M5 lowers the PMOS row.  Turning that strap toward the middle routing channel, which carries its net anyway,
removes the top channel: 196.1 um^2, 23.4 % smaller, with the gain (31.9 dB) and unity-gain frequency (32.2 MHz)
unchanged.  The fixed mode "share both
kinds wherever possible" gives 246.0 um^2.  So *where* a plan shares matters as much as *how much*: the side a strap
faces decides whether a routing channel is needed.  Step by step, with the plans and the measured numbers:
[docs/RESULTS.md](docs/RESULTS.md#running-example).

## What this pull request adds

| path | content |
|---|---|
| `src/glayout/sharing/` | the gLayout extension: `SharingPlan`, `validate_plan`, `build_mos_group`, geometry evidence, plan enumeration ([API guide](../../src/glayout/sharing/README.md)) |
| `benchmarks/textbook_sharing/textbook_sharing/` | the benchmark: circuits, cases, row assembly, verification, plan-selection study, model sessions, analyses |
| `benchmarks/textbook_sharing/data/` | frozen inputs: 639 case folders (packed in `cases.tar.xz`), nominal design points, the frozen mode order |
| `benchmarks/textbook_sharing/results/` | the tables behind every number, and the run records (`run_records.tar.xz`) |
| `benchmarks/textbook_sharing/docs/` | design, parameter space, verification, data dictionary, model protocol, results |
| `benchmarks/textbook_sharing/tests/`, `scripts/` | tests; environment, container wrapper, full run, clean reproduction |

Existing gLayout code is not changed; the top-level README gets a short pointer to this folder.

## Documentation

| document | read it for |
|---|---|
| [docs/DESIGN.md](docs/DESIGN.md) | how a plan is checked and drawn, the enumeration and named modes, the row assembler, where area goes, the cost rule, the selection study |
| [docs/PARAMETER_SPACE.md](docs/PARAMETER_SPACE.md) | the three levels (process, size, plan), per-topology plan counts and outcomes, the count ledger, the task sets |
| [docs/VERIFICATION.md](docs/VERIFICATION.md) | every check a layout passes, specification freezing, testbenches, changes made during the study, the visual review |
| [docs/DATA.md](docs/DATA.md) | every file and field, plan labels, what is not in the repository and how to regenerate it |
| [docs/MODELS.md](docs/MODELS.md) | the language-model protocol, isolation audit, the two references, what the interface comparison measures |
| [docs/RESULTS.md](docs/RESULTS.md) | all results, each with its source table (generated) |

## Quick start

Requirements: Linux x86-64 with Docker.  The EDA tools and the three PDKs come from one pinned image
(`hpretl/iic-osic-tools@sha256:7ef29be7...`, about 5 GB; full digest in `scripts/run_in_container.sh`).  The Python
environment (Python 3.11.17 and the packages of `requirements-lock.txt`) takes about 1 GB.  All commands run from
`benchmarks/textbook_sharing/`.

```bash
scripts/setup_env.sh                       # Python environment in .env/ (micromamba, pinned versions)
tar -xJf data/cases.tar.xz                 # the case folders, into data/cases/
tar -xJf results/run_records.tar.xz        # the run records, into runs/
scripts/run_in_container.sh "python -m pytest -q tests"
```

Recompute every table and the generated documents from the run records, then compare with the committed ones:

```bash
scripts/run_in_container.sh "python -m textbook_sharing.analysis.all"
git status --short results docs            # expected: no change
```

Rebuild and verify one recorded layout from scratch (geometry, DRC, LVS, extraction, post-layout simulation), here
the best OTA plan of the example:

```bash
scripts/run_in_container.sh "python -m textbook_sharing.run_case data/cases/C08/sky130/sW1_sL1 runs/check/best \
  --from-record runs/selection/C08_sky130_sW1_sL1/c15f7f08c7b4/result.json"
```

Rebuild the geometry of every recorded layout and compare it with the records (about 40 minutes with 20 processes:
most layouts take under a second, but some large telescopic-OTA plans take minutes to assemble):

```bash
scripts/run_in_container.sh "python -m textbook_sharing.analysis.geometry_check --jobs 16 --out runs/geometry_check.json"
```

Reproduce a few cases in a fresh export of the committed tree (`git archive HEAD`), with nothing copied from the
records: `scripts/reproduce_clean.sh`.  The whole benchmark, in the order of the protocol: `JOBS=16 scripts/run_all.sh`
(days of CPU time; the model sessions are separate, see [docs/MODELS.md](docs/MODELS.md)).

## Using the sharing plan directly

```python
from glayout.pdk.sky130_mapped import sky130_mapped_pdk as pdk
from glayout.sharing import DeviceSpec, SharingPlan, FingerRef, GateGroup, build_mos_group

m4 = DeviceSpec("M4", "pfet", d="net22", g="net22", s="VDD", b="VDD", width_total=2.0, length=0.3, nf=4)
m5 = DeviceSpec("M5", "pfet", d="VOUT1", g="net22", s="VDD", b="VDD", width_total=2.0, length=0.3, nf=4)
plan = SharingPlan(finger_order=[FingerRef("M4", k) for k in range(4)] + [FingerRef("M5", k) for k in range(4)],
                   orientations=["SD", "DS"] * 4, diffusion_joins=[True] * 7,
                   gate_groups=[GateGroup(tuple(range(8)), "top", "right")])
res = build_mos_group(pdk, [m4, m5], plan=plan, name="pmos_mirror")   # res.component is a gLayout component
```

More in the [API guide](../../src/glayout/sharing/README.md).

## Main findings

Numbers and sources: [docs/RESULTS.md](docs/RESULTS.md).

* 648 requests (18 topologies x 3 PDKs x 12 sizes) give 547 formal entries in 17 topologies; 13 topologies admit
  sharing across transistors.
* Sharing both diffusion and gates makes 279 of 321 verified layouts smaller (mean -5.5 %, up to -18.4 %).  Of the 21
  area increases over all modes, 19 come from routing and row assembly (extra tracks, or width to keep the metal-2
  stubs of two rows apart) and 2 from a shared cell whose top-strap pads sit past the row ends.
* A plan-level cost rule, frozen on two development sizes, predicts the sign of the area change for 91 % of the pairs
  at the ten held-out sizes and finds a plan within 1.3 % of the best of a 64-plan catalogue with one verification.
* Language models given the interface reach layouts beyond that catalogue in 16 of 28 tasks; with an interface
  limited to base gLayout, 41 of 42 sessions end at the unshared area.

## Limits

One row-based assembler (another router could move the losses); bounding-box area; one size grid and no Monte Carlo;
the class-AB stage stays diagnostic; magic DRC is advisory; base gLayout in the interface comparison is emulated by one
restricted call; the catalogue samples an enumeration that misses plans the models found; selection candidates outside
the reported set were not reviewed visually.
