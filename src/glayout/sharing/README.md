# glayout.sharing

Diffusion and gate sharing across the transistors of one device group, written as an explicit plan that is checked
before any geometry is drawn and measured again on the geometry afterwards.  Design notes:
[`benchmarks/textbook_sharing/docs/DESIGN.md`](../../../benchmarks/textbook_sharing/docs/DESIGN.md).

| name | what it does |
|---|---|
| `DeviceSpec` | one SPICE transistor: id, `nfet`/`pfet`, drain, gate, source, body net, total width, length, finger count |
| `SharingPlan`, `FingerRef`, `GateGroup` | finger order, orientations, diffusion joins and gate straps of one group |
| `validate_plan(rules, devices, plan)` | checks a plan without drawing; returns an `EligibilityReport` (`ok`, `errors` with `code`, `message`, `where`) |
| `build_mos_group(pdk, devices, plan=...)` | draws the group for a `MappedPDK`; returns a `GroupResult` (component, metal-2 pins, applied plan, sharing evidence, geometry stats); raises `SharingPlanRejected` for an illegal plan |
| `independent_plan(devices)` | every transistor on its own (what base gLayout builds) |
| `group_candidates(pdk, devices)`, `named_plans(pdk, devices)` | the six-axis enumeration with legality and de-duplication; the named modes `independent`, `diffusion_only`, `gate_only`, `combined` |
| `evidence_from_gds(...)` | the sharing evidence recomputed from a GDS file |
| `rules_for(pdk)`, `OVERRIDES` | design-rule values used by the builder, with the audited deviations from the generic rule table |

## Example: the PMOS mirror of a five-transistor OTA (SKY130)

```python
from glayout.pdk.sky130_mapped import sky130_mapped_pdk as pdk
from glayout.sharing import (DeviceSpec, SharingPlan, FingerRef, GateGroup, validate_plan, build_mos_group,
                             rules_for, group_candidates)

m4 = DeviceSpec("M4", "pfet", d="net22", g="net22", s="VDD", b="VDD", width_total=2.0, length=0.3, nf=4)
m5 = DeviceSpec("M5", "pfet", d="VOUT1", g="net22", s="VDD", b="VDD", width_total=2.0, length=0.3, nf=4)

# M4's four fingers, then M5's; alternating orientation, every boundary shared (the M4|M5 boundary is VDD on both
# sides), and one poly strap on top for both gates (net22) with its pad at the right end
plan = SharingPlan(finger_order=[FingerRef("M4", k) for k in range(4)] + [FingerRef("M5", k) for k in range(4)],
                   orientations=["SD", "DS"] * 4, diffusion_joins=[True] * 7,
                   gate_groups=[GateGroup(tuple(range(8)), "top", "right")])
assert validate_plan(rules_for(pdk), [m4, m5], plan).ok

res = build_mos_group(pdk, [m4, m5], plan=plan, name="pmos_mirror")
ev = res.physical_sharing_evidence           # measured on the drawn shapes, not taken from the plan
print(ev["active_islands"], ev["n_cross_device_shared_nodes"], ev["n_cross_device_gate_conductors"])   # 1 1 1

plan.orientations[4] = "DS"                  # M5 now shows its drain (VOUT1) to M4's source (VDD)
print(validate_plan(rules_for(pdk), [m4, m5], plan).errors[0]["code"])                                 # join_net_mismatch

print(group_candidates(pdk, [m4, m5])["counts"])   # {'raw': 256, 'static_illegal': 8, 'equivalent_duplicate': 147, 'unique': 101}
```

The same calls work for `gf180_mapped_pdk` and `ihp130_mapped_pdk`.  The plan never changes the netlist: widths,
lengths, finger counts and body nets come from the `DeviceSpec`s, and a plan that would need a different netlist is
rejected.
