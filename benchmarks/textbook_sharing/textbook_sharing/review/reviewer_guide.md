# Visual review protocol

The reviewer (a person or a vision model) examines rendered layouts one item at a time, without knowing which plan,
mode or method produced them and without seeing DRC, LVS or simulation results.  Each unique geometry is reviewed once;
the verdict is reused for every record with the same cell-name-independent geometry hash.

## What the reviewer receives
- `<review_id>.png`: three panels stacked vertically: (1) all layers, (2) front end (active / poly / contact / implant /
  well), (3) back end (metals / vias / pin labels).  Yellow ticks are layout coordinates in micrometres (x along the
  bottom edge, y along the left edge of each panel); a 10 um (yellow) and a 1 um (cyan) scale bar are drawn in panel 1.
- optionally `<review_id>_t<i>.png`: magnified windows of the all-layers view for wide layouts; the header states the
  x-range.
- `items.jsonl`: one line per item with its review id and image files.  Images are 128-colour palette PNGs (layer
  colours preserved).

## What a correct layout looks like
One or more horizontal device rows (NMOS rows, PMOS rows inside an n-well, passive rows with poly resistors or MIM
capacitors).  Each MOS row is a set of active islands crossed by vertical poly gates, with source/drain contacts in the
islands and gate contacts on poly pads below or above the islands; vertical tap strips at both row ends plus a
horizontal tap strip along the gate side of the row (U-shaped tie), all in the row's well and implant; metal-2 vertical
stubs from the pins up or down to horizontal metal-3 trunks in the routing channels between rows; pin text labels on the
metal-3 trunks; the whole layout is one flat cell.

Normal structures that are easy to misread:
- a gate contact pad (poly + contact + local metal) has no via on the pad itself; a metal-1 riser runs from the pad to
  the cell's pin row, where the via and the metal-2 stub to the trunk sit;
- the PMOS row is mirrored vertically: a gate strap drawn at the bottom of a PMOS cell faces up and its net is routed in
  a channel above the PMOS row, a strap drawn at the top of the cell faces the channel below the row;
- passive rows (resistors, MIM capacitors) can be much taller than MOS rows; a small resistor at the far edge of a tall
  passive row connected by long metal-2 stubs is legal.
Flag such structures only if a connection is actually missing.

## Record per item (JSON)
```
{"review_id": "...", "reviewer_type": "human" | "vision_model", "reviewer_id": "<name or exact model id>",
 "images_viewed": ["file names actually looked at"],
 "observed_findings": [">= 3 concrete observations with coordinates in um read from the ticks"],
 "issue_locations": [{"x": .., "y": .., "description": ".."}],
 "verdict": "pass" | "suspicious" | "fail"}
```

## Verdict rules
- "fail": clearly broken geometry (e.g. a gate without any island, a metal trunk ending in empty space with nothing
  attached at either end, overlapping shapes of two different pin labels, a label placed on an empty area);
- "suspicious": something that may be wrong and must be checked against the raw DRC / LVS / extraction (e.g. an
  isolated small shape far from the body, a contact that seems to sit outside active, uneven finger counts between
  apparently matched devices);
- "pass": none of the above.
Do not grade aesthetics or area.  Name the panel, the layer colour group and the coordinates.  Never give "pass" for an
item whose images could not be seen; use "suspicious" with the issue "image not viewable" instead.

## Blinding
Only the batch's `items.jsonl` and the image files it lists are given to the reviewer; file names carry only the review
id.  Plans, modes, methods, areas and tool results are never shown.

## Resolution of flags
A "suspicious" or "fail" verdict is never overwritten.  It is resolved by objective checks (official DRC, LVS,
floating conductors in the extracted netlist, connectivity of gate pads to via1 and of metal-2 to via2), and the method
and evidence are stored in the record's `visual_resolution` field with the outcome "resolved_ok" or "confirmed_issue".
