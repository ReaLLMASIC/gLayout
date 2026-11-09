# Sharing-plan interface (what you can control)

You are choosing the physical organisation of the transistors of an analog circuit. The circuit (devices, nets,
total widths W, lengths L, finger counts nf, body connections), the process, the row skeleton and the grouping of
transistors are FIXED by the task; you cannot change them. A deterministic generator (gLayout with a shared-construction
extension) builds the layout from your plan, and independent tools (official DRC deck, LVS against the target netlist,
an extracted-width check, parasitic extraction and post-layout simulation against frozen specifications) judge it.

## Fixed skeleton
* Every MOS transistor is split into nf unit fingers of width W/nf (finger k of device "M3" is ("M3", k)).
* Transistors are pre-assigned to sharing groups (same polarity, body net, length and finger width). Each group
  becomes one row cell; NMOS groups go in the bottom row, PMOS groups in the row above, resistors/capacitors in a top
  row. Routing channels between rows, body ties, wells, metal-3 trunks and pin labels are generated automatically and
  identically for every plan.
* Objective: the smallest full bounding-box area among plans that pass every check. A plan that fails a check has no area value.

## What a plan of one group fixes
A plan lists the group's fingers left to right and decides, for each finger, which side is its source:
* `finger_order`: every unit finger of every device of the group exactly once, e.g. [("M1",0),("M2",0),("M1",1)].
* `orientations`: one entry per position, "SD" (source on the left, drain on the right) or "DS".
* `diffusion_joins`: n-1 booleans; True between positions i and i+1 means the two fingers share ONE diffusion region and
  contact column. This is legal only if the right terminal net of finger i equals the left terminal net of finger i+1
  (same device or different devices). Unjoined neighbours become separate active islands with a spacing gap.
* `gate_groups`: a partition of the positions into poly straps, `GateGroup(fingers=(positions...), side="bottom"|"top",
  pad_end="left"|"right")`. All gates of one strap must carry the same gate net. A bottom strap runs below the
  active over the span of its fingers with its contact pad at the left or right end of that span. A top strap runs above
  the active and reaches from its fingers to the left or right end of the group, where its pad sits. Two straps on the
  same side must not overlap in span (top straps: in reach); at most two top straps (one reaching left, one right).
* Each extra active island costs width (island gap); each top strap costs height (an extra strap band); straps on both
  sides of one span need an extra spacing offset; more bottom straps need a second pad level (height).

## How to write it
Answer with ONE ```python block containing exactly one statement, `plans = {group_index: plan, ...}`, with an
entry for every group. A plan is either

```python
SharingPlan(finger_order=[("M1", 0), ("M2", 0), ("M2", 1), ("M1", 1)],
            orientations=["SD", "DS", "SD", "DS"],
            diffusion_joins=[True, True, True],
            gate_groups=[GateGroup(fingers=(0, 3), side="bottom", pad_end="left"),
                         GateGroup(fingers=(1, 2), side="top", pad_end="right")])
```

or the axis shorthand (expands deterministically into a SharingPlan):

```python
axis_plan(arrangement="block"|"interleave"|"abba"|"mirror",
          orientation="alt_SD"|"alt_DS"|"seek_SD"|"seek_DS",
          diffusion="none"|"all_legal", gate="per_device"|"per_net",
          strap_start="bottom"|"top", contact_end="left"|"right")
```
* arrangement: block = devices one after another; interleave = round-robin finger by finger; abba = A B B A ... (two
  devices, even nf); mirror = first halves in order, then second halves in reverse order (even nf).
* orientation: alt_* alternate SD/DS along the row starting with SD or DS; seek_* start with SD/DS and then give each
  finger the orientation whose left net equals the previous finger's right net (otherwise alternate).
* diffusion: none = join only neighbouring fingers of the same device; all_legal = join every neighbouring pair whose
  facing nets are equal (this is where different devices share a diffusion node).
* gate: per_device = one strap per device; per_net = one strap per gate net (different devices with the same gate net
  share one poly conductor).
* strap_start: side of the first strap (by first finger); later straps take that side unless they overlap a strap
  already there, then the other side. contact_end: pad end of the straps.

Only literals, lists/tuples/dicts, list concatenation `+` and repetition `*` by an integer, `range(...)`, `list(...)`,
`tuple(...)` and calls of `SharingPlan`, `GateGroup`, `axis_plan` with keyword arguments are accepted; this is a
restricted program format, not general Python. Anything else is rejected with a reason and still counts as a proposal.

## Feedback you will get
After each proposal: either the list of reasons it was rejected before building, or the tool report (status of every
check, bounding box, row and cell sizes, how many diffusion nodes / gate conductors are shared across devices, and
failure details). Each proposal (including rejected and repeated ones) uses one unit of your proposal budget.
You may stop early by answering with the single word FINAL (your best passing proposal is kept).
