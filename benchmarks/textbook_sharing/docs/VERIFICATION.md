# Verification

Every layout, whether an unshared reference, a named mode, a catalogue candidate or a model proposal, goes through the
same function (`textbook_sharing/run_case.py`, which calls `verify/pipeline.py`).  Only the drawn geometry is
judged: plan labels are never trusted, and the sharing that is reported is measured on the GDS.

## Stages

| stage | tool | passes when |
|---|---|---|
| build | `glayout.sharing.build_mos_group` and the row assembler | the plan is legal and the layout is assembled |
| DRC | the official KLayout deck shipped with each PDK (`sky130A.lydrc`; `gf180mcuD/.../drc/run_drc.py`; `sg13g2_maximal.lydrc`) | no violation; for IHP the chip-level density and filler rules (`AFil.*`, `GFil.*`, `M1-5Fil.*`, `M1-5.j/k`, `TM1/2.c/d`) are reported but not counted, since they do not apply to a cell of a few hundred square micrometres |
| magic DRC | magic | advisory only, never gates (on GF180 it flags the implant-area rules PP.8a/NP.8a on layouts the official deck accepts) |
| LVS | SKY130 and IHP: magic extraction and netgen with the PDK setup file; GF180: the official KLayout LVS deck (`run_lvs.py`, variant D), because magic and netgen mis-extract the GF180 substrate | the extracted netlist matches `target_lvs.spice` |
| sizing | own check of the extracted netlist (`verify/sizing.py`) | every target transistor's total width and length is found among extracted devices of the same model and connectivity; declared width ratios hold (`matching.py`) |
| extraction | magic `extract` with `extresist` (R and C, thresholds 0) | an R+C netlist with the DUT ports is written |
| post-layout simulation | ngspice, PDK models, the case testbench around the extracted netlist | every frozen specification of the case is met |
| physical checks | own geometry checks of the GDS (`verify/physical.py`) | channel regions equal the expected finger count, every port label sits on metal, no stray shape, no floating poly |
| visual review | blinded review of rendered images (`review/`) | effective verdict "pass" (see below) |

The status of a layout is the first failing stage in the order `rejected_plan`, `build_failed`, `drc_failed`,
`lvs_failed`, `constraints_failed`, `pex_failed`, `simulation_failed`, `spec_failed`, `physical_review_failed`;
otherwise `auto_passed`.  `NA` marks a named mode that shares nothing in any group of the circuit (no run is made).
Area always means the bounding box of the whole layout.

## Specifications: qualification before any layout

For each requested case the schematic (PDK device models, PDK resistor and MIM models) is simulated with the case
testbench (`build_cases.py`).  A case is qualified only if the schematic meets the category floors of its topology
(`nominal.py`, `qualify.py`); a case that misses a floor goes to the diagnostic set, and floors are never relaxed.
The specification of a qualified case is then frozen from the schematic and used for every layout of that case:

| metric | frozen specification |
|---|---|
| low-frequency gain (dB) | at least max(floor, schematic - 3 dB) |
| unity-gain frequency, -3 dB frequency | at least max(floor, 0.6 x schematic) |
| gain at the nominal point (V/V) | at least max(floor, schematic - 0.05) |
| output swing | at least max(floor, 0.8 x schematic) |
| phase margin | at least the floor |
| THD, quiescent current | at most the floor |
| compliance voltage | at most min(floor, schematic + 0.1 V) |
| mirror copy error | absolute value at most the floor |

Universal operating-point checks at qualification: the simulation runs and reports every floor metric; servo-based
testbenches settle within 2 % of VDD; a mirror's compliance voltage is found and its test point lies between it and VDD.

## Testbenches

`testbench.py` writes each testbench from the case (sizing, supply, bias, load); nothing is tuned by hand.
Bias voltages come from ideal replica generators built with the DUT's own device model and size (a current-source
gate is biased by a diode-connected replica carrying the branch current; a cascode gate by a W/4 replica).
Amplifiers without a defined output DC point use a disclosed DC servo (1e6 H / 1e6 F) that fixes the output operating
point without changing the AC response; pairs with current-source loads and the fully differential OTA use an ideal
common-mode feedback.  Everything the testbench adds is listed in each case (`overrides.test_auxiliaries`) and is
never part of the layout or its area.

## Changes made during the study

All were found on the development sizes or in the first evaluations, applied to every case, and the earlier results
are kept in the records (`postsim_history`):

1. Current sources of the mirrors without a VDD port (C01, C02, C03, C13, C14) were tied to an undefined node; they
   now use their own supply.
2. The fully differential OTA (C10) had no differential DC servo.  With R+C extraction its two outputs settled
   0.66 V apart and the gain fell below the specification, while a capacitance-only extraction of the same layout gave
   equal outputs (`results/analysis/pex_sensitivity_C10_gf180.json`): wire resistance created a small offset that the
   open-loop gain amplified.  It now has the same servo as the single-ended OTAs, and the input offset is reported.
3. An ideal current source can force a non-physical DC solution; every current-driven node now gets a `.nodeset`
   starting value (a starting value, not a constraint).
4. After these testbench fixes every case was qualified again with the final testbenches, and existing layouts only
   repeated the post-layout simulation on the same extracted netlist (`resim.py`;
   `results/analysis/resim_after_testbench_fix.json`): no passing layout failed, 2 failing layouts passed.
5. Assembly: when every gate strap of a PMOS group is on top, two same-net implant regions could end up closer than
   the GF180 rule NP.2 allows; the assembler now fills such gaps with an implant bridge.  The rule was added during the
   selection study, after GF180 candidates failed DRC on it, and those were evaluated again.  SKY130 candidates
   evaluated before the rule had passed every check and were kept; they differ from a rebuild with this code only by
   the bridge, and their re-verification is reported in [RESULTS.md](RESULTS.md) (geometry check).
6. GF180 extraction: magic does not terminate when `port makeall` is combined with `extresist`; the ports are taken
   from the labels instead.

## Visual review

The automatic checks cannot see everything (a label on the wrong shape, a stub that ends in empty space), so rendered
layouts are also reviewed (protocol: `textbook_sharing/review/reviewer_guide.md`):

* the reviewer receives only images named by a review id: three panels (all layers, front end, back end) with
  coordinates in micrometres and scale bars, plus magnified tiles for wide layouts; no plan, mode, method, area or
  tool result;
* each unique geometry (cell-name-independent hash, per PDK) is reviewed once, and the verdict is reused for every
  record of the same geometry;
* every verdict needs at least three concrete observations with coordinates; "suspicious" and "fail" verdicts are
  never overwritten.  They are resolved by objective checks (official DRC and LVS results, floating conductors in the
  extraction, gate pads reaching via1, metal-2 reaching via2: `review/check_connectivity.py`, `check_gate_pads.py`,
  `resolve_auto.py`), and the method and evidence are stored in the record's `visual_resolution`;
* the reviewer was a vision model (recorded in `visual.reviewer_id`), not a person.

Coverage: every main-grid layout, every reported layout (the best passing proposal of every model session, the best
passing plan and the named-mode plans of every selection task) and every PVT layout; catalogue candidates outside the
reported set were not reviewed.  Counts: `results/analysis/review_coverage.json` and [RESULTS.md](RESULTS.md).

## Robustness and extraction checks (outside the formal results)

* Corners: five conditions (TT 27 C, SS 27 C, FF 27 C, SS 85 C at 0.9 VDD, FF -40 C at 1.1 VDD) on the extracted
  netlists of the reference, the named mode "combined" and the best catalogue plan at the nominal size of the selection
  topologies, against the nominal frozen specifications (`analysis/pvt.py`).  No Monte Carlo, so nothing is claimed
  about mismatch.
* Extraction sensitivity: a capacitance-only re-extraction with the same testbench (`analysis/pex_sensitivity.py`).
* Clean reproduction: `scripts/reproduce_clean.sh` exports the committed tree into an empty folder, rebuilds and
  verifies a few cases there and compares geometry hash, area, status and every stage with the records.
