# Design

## 1. What base gLayout cannot express

Base gLayout builds transistors one at a time.  A multi-finger FET shares source/drain diffusion between neighbouring
fingers of the same transistor, and the placement helpers interdigitate or common-centroid several transistors in one
row, but two transistors never share a diffusion node and never share a gate conductor.  Textbook layouts do both: a
differential pair shares its tail node, the transistors of a mirror share their source and their gate.  As long as
such sharing is not an explicit object, a generator cannot enumerate the options, a checker cannot reject a wrong one
before anything is drawn, and a model cannot be asked for one.

## 2. The sharing plan (`src/glayout/sharing/`)

A **group** is a set of transistors that can sit in one active row: same polarity, body net, length and unit finger
width (`DeviceSpec`: the SPICE transistor with its four nets, total width, length and finger count).  A
**`SharingPlan`** of a group fixes the physical organisation of its unit fingers and nothing else:

| field | meaning |
|---|---|
| `finger_order` | every unit finger `(device, k)` exactly once, left to right |
| `orientations` | per position `"SD"` (source left) or `"DS"` |
| `diffusion_joins` | n-1 booleans: fingers i and i+1 share one diffusion node and contact column |
| `gate_groups` | a partition of the positions into poly straps; each strap has a `side` (`bottom` or `top` of the active) and a `pad_end` (`left` or `right`) |

A plan cannot remove a device or change a width, length or body connection; the netlist is fixed by the case.

**Checked before drawing** (`validate_plan`, structured errors in an `EligibilityReport`):

* the group: one polarity, unique ids, equal length, unit width and body net, no SPICE multiplier, unit width at
  least the contactable minimum, length at least the PDK minimum;
* the plan's shape: every finger exactly once, one orientation per finger, n-1 joins;
* electrical sense: a join is legal only if the facing terminals carry the same net (`join_net_mismatch`), a strap
  ties fingers of one gate net only (`gate_group_net_mismatch`), the straps partition the fingers;
* routability: two bottom straps may not overlap, and a top strap reaches from its fingers to its pad end, so two top
  straps may not overlap in reach (`gate_strap_interleave_unroutable`).

`build_mos_group` raises `SharingPlanRejected` for an illegal plan; it never falls back silently to another plan.

**Construction** (`build_mos_group`): the cell is drawn column by column from the plan, not by merging finished
devices.  A diffusion node between two fingers is drawn once and shared only when the plan joins them; islands are
separated by the active spacing.  The gates of one strap are tied by a poly strap outside the channel: a bottom strap
has its contact pad below the strap band, a top strap has its pad past the end of the active area with a metal-1
riser to the pin row.  Every pin is a metal-2 pad on the cell's top edge (diffusion nodes and top-strap gates) or
bottom edge (bottom-strap gates), so the row assembler needs to know nothing about the inside of a cell.

**Design rules** (`rules.py`): every value comes from gLayout's `MappedPDK` rule table; where that table lacks an
entry or disagrees with the foundry deck, `OVERRIDES` lists the value with the foundry rule identifier.  No override
relaxes a foundry rule.

**Evidence from geometry** (`evidence.py`): after drawing, the merged active, poly, contact and metal-1 shapes are
analysed again: how many active islands there are, which diffusion nodes connect terminals of different devices (and
their nets), which poly conductors tie gates of different devices.  Tables and reports use this evidence, never the
plan's own description.  `evidence_from_gds` does the same on a written GDS.

## 3. Enumerating plans (`enumeration.py`)

Six discrete axes per group give 4 x 4 x 2 x 2 x 2 x 2 = 256 tuples:

| axis | values |
|---|---|
| arrangement | `block`, `interleave`, `abba` (two devices, even finger counts), `mirror` (even finger counts) |
| orientation | `alt_SD`, `alt_DS` (alternate along the row), `seek_SD`, `seek_DS` (each finger takes the orientation whose left terminal carries the net of the previous finger's right terminal) |
| diffusion | `none` (joins only inside one device), `all_legal` (every boundary whose facing nets are equal) |
| gate | `per_device` (one strap per device), `per_net` (one strap per gate net) |
| strap_start | `bottom`, `top` (side of the first strap; a later strap takes the other side when its interval would overlap) |
| contact_end | `left`, `right` (pad end) |

Each tuple becomes a `SharingPlan`, is checked by `validate_plan`, and is identified by a canonical plan id;
tuples that build the same plan are removed.  No geometry is drawn and no measurement is used.  The **named modes** of
a group are the first plan in this fixed order that really shares the mode's kind: `diffusion_only` (at least one
cross-device join), `gate_only` (at least one strap shared by two devices), `combined` (both); `independent` is the
one-transistor-at-a-time plan.  A group without such a plan keeps its independent plan, so a named mode of a circuit
can leave some groups unshared.  The enumeration is a family, not the whole space: a plan written directly can use any
finger order and any strap partition.

## 4. From a circuit to a layout (`textbook_sharing/layout.py`, `assembly/`)

1. **Groups.**  Transistors are split by polarity and body net; within that, two transistors are joined when they
   have the same length and unit width and share a source/drain net or a gate net; groups are the connected
   components.  Each group is drawn by `build_mos_group` from its plan.
2. **Rows.**  NMOS cells in the bottom row, PMOS cells in the row above (mirrored vertically, so a strap drawn at the
   bottom of a PMOS cell faces up), resistors and capacitors in a top row.
3. **Channels.**  A routing channel lies below, between and above the rows; a channel exists only if some net needs
   it.  Every pin gets a metal-2 stub to a metal-3 trunk of its net in the adjacent channel; trunks are packed into
   tracks.
4. **Stub conflicts.**  When a channel serves both its lower and its upper row, stubs of different nets may collide.
   The assembler builds the layout twice: with one trunk per net, shifting the upper row sideways until no stubs
   collide (`shared`), and with such nets split into a lower and an upper trunk joined by a metal-2 jumper beyond the
   pins (`split`).  The smaller layout is kept; both areas are recorded.
5. **Ties and labels.**  Tap strips at both row ends and along the gate side of each MOS row (a U-shaped body tie),
   well and implant regions per row, implant bridges where two same-net implant regions would be closer than the rule,
   and port labels on the metal-3 trunks.

Everything except the group cells follows the same rule for every plan, so two layouts of one circuit differ only
because their plans differ.  The assembler still responds to a plan, through the nets each cell brings into each
channel and through the stub positions; this is where most losses come from.

## 5. Where the area goes

Let the unshared layout be W0 x H0.  Sharing removes width ΔW (shared diffusion nodes, fewer island gaps) and adds
height ΔH (strap bands, pad levels, routing tracks):

    A1 = (W0 - ΔW)(H0 + ΔH)   and the area falls iff   H0 ΔW > (W0 - ΔW) ΔH

Both terms belong to the whole layout, not to a cell.  A narrower cell helps only if its row sets the width; when a
resistor or capacitor row is the widest, transistor savings never reach the bounding box.  A strap that changes side
moves its gate pin to another channel, which can add or remove a whole routing channel.  The running example in
[RESULTS.md](RESULTS.md) shows each effect on one OTA: sharing the tail node narrows the row that sets the width;
sharing VDD in the PMOS group narrows a row that does not, and nothing changes; one strap instead of two lowers the
PMOS row; turning that strap toward the middle channel, which carries its net anyway, removes the top channel.

For every area increase the change is split exactly into five terms (`analysis/cost_decomposition.py`): the widest
row got wider; width added outside the rows by the stub-conflict rule of step 4 (a row shift or a split trunk);
taller MOS rows; taller routing channels; other height.

## 6. The cost rule (`selection/cost.py`)

The rule ranks a candidate without drawing it.  Inputs: the candidate's plans, the PDK rule table and one assembled
unshared layout per case.  Per group it evaluates the widths and heights of `build_mos_group` from formulas (island
widths, gaps, top-strap pad overhang; strap bands, pad levels, pin rows).  Per row it shifts the unshared row span and
height by the group changes; the bounding box follows from the widest row and the row heights.  Because every
diffusion node has a pin on the cell's top edge and every strap a pad on its side, the nets a candidate brings into each
channel follow from the plan, and the rule adds one track pitch per extra net in a channel (and the channel margins
when a channel appears or disappears).  Track packing, cross-row stub shifts and the split strategy are not modelled.
The channel term was added after the two development sizes and frozen with the rest of the rule before any other size
was measured.

## 7. The plan-selection study (`selection/`)

For 56 tasks (`docs/PARAMETER_SPACE.md`) a catalogue of at most 64 plans is fixed before any evaluation: the four named
modes plus a seeded stratified sample over the per-group (diffusion, gate) axis values, or every plan when the circuit
has at most 64.  Every catalogue plan is built and fully verified once; each method is then replayed on these records
(`strategies.py`), sees only what it is entitled to, and pays for it.  Budget: 1, 2, 4, 8, 16 full verifications.

| method | order in which plans are verified |
|---|---|
| unshared only | the unshared plan |
| fixed mode order | the named modes in an order frozen from the development sizes, then by share score |
| share most | most cross-device joins plus shared straps first |
| random | uniform, 10 fixed seeds |
| neighbourhood search | beam search over axis vectors from the unshared plan |
| build all, then rank | every candidate's geometry built (and paid for), verified by ascending area |
| cost rule | ascending estimate of section 6 |

Result after n verifications = the smallest passing area among the plans verified so far.  Wall time = the method's
own work (geometry builds timed one at a time in `selection/timing.py`) plus the verification time of the plans it
verified.

## 8. Order of decisions

1. Size grid, size-derivation rule and qualification rule; then every case was qualified and its specification frozen
   before any layout was built.
2. Main grid at the two development sizes (sW1_sL1, sW1_sL1.5); from these only, the fixed mode order was frozen
   (`data/frozen/fixed_order.json`) and the cost rule completed.
3. The ten held-out sizes, the selection study and the model sessions.
4. Testbench fixes (`docs/VERIFICATION.md`) were applied to every case: all cases were qualified again with the final
   testbenches and existing layouts only repeated the post-layout simulation.

## 9. Code map

| module | role |
|---|---|
| `src/glayout/sharing/spec.py`, `group.py`, `rules.py`, `evidence.py`, `enumeration.py` | plan data model, checks and construction, rule adapter, geometry evidence, enumeration |
| `circuits.py`, `netlist.py`, `nominal.py`, `overrides.py` | the 18 topologies, SPICE emitters, nominal design points and floors, disclosed changes and test auxiliaries |
| `grid.py`, `cases.py`, `build_cases.py`, `presim.py`, `qualify.py`, `testbench.py` | size derivation, case model, case building, schematic simulation, qualification, testbenches |
| `layout.py`, `assembly/` | grouping, row and channel assembly, passive cells |
| `verify/`, `matching.py`, `run_case.py` | verification pipeline, matching check, one run |
| `run_grid.py`, `selection/`, `llm/` | main grid, selection study, model sessions |
| `review/` | rendering, blinded visual review, objective resolution of flags |
| `analysis/` | every table in `results/` and the generated documents |
| `freeze.py`, `resim.py`, `redesign_search.py`, `calibrate_res.py` | freeze checkpoints, re-simulation after testbench fixes, class-AB redesign search, resistor calibration |
