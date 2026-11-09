# Device-placement interface (what you can control)

You are choosing the physical organisation of the transistors of an analog circuit. The circuit (devices, nets,
total widths W, lengths L, finger counts nf, body connections), the process, the row skeleton and the grouping of
transistors are FIXED by the task; you cannot change them. A deterministic generator (gLayout) builds the layout from your plan, and independent tools (official DRC deck, LVS against the target netlist,
an extracted-width check, parasitic extraction and post-layout simulation against frozen specifications) judge it.

## Fixed skeleton
* Every MOS transistor is split into nf unit fingers of width W/nf (finger k of device "M3" is ("M3", k)).
* Transistors are pre-assigned to sharing groups (same polarity, body net, length and finger width). Each group
  becomes one row cell; NMOS groups go in the bottom row, PMOS groups in the row above, resistors/capacitors in a top
  row. Routing channels between rows, body ties, wells, metal-3 trunks and pin labels are generated automatically and
  identically for every plan.
* Objective: the smallest full bounding-box area among plans that pass every check. A plan that fails a check has no area value.

## What you choose for one group
This interface offers the device-level options of base gLayout: multi-finger transistors (neighbouring fingers of the
SAME transistor share a source/drain diffusion region) and the interdigitated / common-centroid placement of the
transistors of a group in one row.  Different transistors never share a diffusion region or a gate conductor here:
every transistor has its own gate strap below the row, and fingers of different transistors are separated by an
active-island gap.

For every group write `fet_row(arrangement=..., orientation=..., contact_end=...)`:
* arrangement: "block" = transistors one after another; "interleave" = round-robin finger by finger (interdigitated);
  "abba" = A B B A ... (two transistors with an even finger count, common centroid); "mirror" = first halves in
  order, then second halves in reverse order (even finger counts).
* orientation: "alt_SD" or "alt_DS" = the fingers alternate source/drain along the row starting with source-left or
  drain-left (this is what lets neighbouring fingers of one transistor share their diffusion).
* contact_end: "left" or "right" = end of each transistor's gate strap where its contact pad sits.

## How to write it
Answer with ONE ```python block containing exactly one statement, `plans = {group_index: fet_row(...), ...}`, with an
entry for every group, e.g.

```python
plans = {0: fet_row(arrangement="interleave", orientation="alt_SD", contact_end="left"),
         1: fet_row(arrangement="block", orientation="alt_DS", contact_end="right")}
```
Only this call with keyword arguments is accepted; anything else is rejected with a reason and still counts as a proposal.

## Feedback you will get
After each proposal: either the list of reasons it was rejected before building, or the tool report (status of every
check, bounding box, row and cell sizes, how many diffusion nodes / gate conductors are shared across devices, and
failure details). Each proposal (including rejected and repeated ones) uses one unit of your proposal budget.
You may stop early by answering with the single word FINAL (your best passing proposal is kept).
