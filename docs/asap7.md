# ASAP7 / FinFET proof of concept

Use Python 3.10 with either GLAYOUT_BACKEND=gdstk or GLAYOUT_BACKEND=gdsfactory.
Install with pip install -e . pytest. Set PDK_ROOT=/tmp if planar PDKs are absent.
The mapping uses native micrometres and ASAP7 r1p7 dimensions, rather than the
scaled APR libraries. This is a demonstration, not a signoff flow.

## Primitive boundary

    from glayout import asap7, nmos, momcap
    transistor = nmos(asap7, nfin=3, fingers=4, multipliers=2)
    transistor.write_gds('nfet.gds')

FinFET geometry is selected by pdk.finfet in the transistor finger primitive.
The existing multiplier routing, transistor arrays, interdigitized placement,
current mirror, common-centroid diffpair, FVF, and composite circuit generators
remain in use. No alternate schematic-driven circuit placer/router is used.
All circuit, placement and routing sources match the pre-ASAP7 baseline.
Potential existing endpoint/capacitor connection fixes are left for review.

nfin selects a positive integral number of fins. Otherwise width is occupied
fin-track height in micrometres, rounded UP to complete 27 nm tracks. It is not
BSIM-CMG effective perimeter width. ASAP7 gates are 20 nm long on a 54 nm lattice;
fins are 7 nm wide on a 27 nm lattice. Unsupported gate lengths are rejected.
The reference netlist uses the selected PDK model, explicit nfin, and electrical
dummy transistors matching the existing dummy connections.

Generic poly routing denotes local gate interconnect (LIG, layer 16); actual
vertical gate stripes use layer 7 on a true 1×CPP (54 nm) pitch. Electrical dummy
gates are integrated at 2×CPP from the outer active gates, sharing continuous FIN,
SELECT, threshold markers, and NWELL. Source/drain access uses SDT, LISD, multi-cut
V0 and M1. Legacy port names and M1/M2 contact access are retained. Realistic 7 nm
metal routing rules (24 nm minimum separation on M1–M5) are used alongside compact
single-track taprings (`finfet_tapring`) and FinFET-aware composite cell offsets.
Circuit CI keeps the original analog sizing with 20 nm lengths; narrow one-fin
primitives are tested separately.

Device reference translations snap to the fin/gate lattice below the circuit
hierarchy. This preserves the original placement pattern with small legalizing
translations. Ninety-degree rotations are rejected. Export validates world
coordinates and port edges, including flattened layouts, on the 0.5 nm grid.
Half-grid port midpoints are permitted when their two edges are on-grid.
The native backend also uses gdsfactory-compatible move(destination=...) semantics.

Layer 100/0 is a virtual device envelope. Layer 100/20 denotes an implicit body
contact for the existing guard-ring interface; 100/21 denotes a virtual deep well.
They are metadata, not ASAP7 fabrication masks. Existing metal body rails remain
present. The POC extraction binds their body markers to substrate/nwell. Multiple
isolated NMOS substrate biases are unsupported. Foundry body-contact integration
and a complete well/isolation flow remain outside this demonstration.

## All transistor threshold flavors

Both NMOS and PMOS support RVT, LVT, SLVT and SRAM Vt. The default remains RVT.
Select an individual device, or select a PDK copy for an existing circuit:

    from glayout import asap7, nmos, pmos
    from glayout.cells.elementary import current_mirror

    input_fet = nmos(asap7, nfin=3, fingers=2, vt="lvt")
    load_fet = pmos(asap7, nfin=3, vt="slvt")
    sram_fet = nmos(asap7, nfin=2, vt="sram")
    lvt_pdk = asap7.with_finfet_flavor("lvt")
    mirror = current_mirror(lvt_pdk, width=0.081, numcols=2)

The selector returns a copy and leaves the original PDK's model choices intact.
The nmos, pmos, finfet and multiplier entry points accept vt. Existing circuit
builders can receive the selected PDK without any placement or routing edits.
Different flavors may coexist in one layout on the same fin/gate lattice.

| vt | NMOS model | PMOS model | Physical threshold mask |
| --- | --- | --- | --- |
| rvt | nmos_rvt | pmos_rvt | none |
| lvt | nmos_lvt | pmos_lvt | LVT 98/0 |
| slvt | nmos_slvt | pmos_slvt | SLVT 97/0 |
| sram | nmos_sram | pmos_sram | SRAMVT 110/0 |

Markers cover the actual device and its electrical dummies. SRAM Vt retains
regular conservative geometry; SRAMDRC spacing relaxations are disabled.
Device info includes vt and model. Each reference netlist uses its selected
model name. The supplied ASAP7 HSPICE files 7nm_TT_160803.pm, 7nm_FF_160803.pm,
and 7nm_SS_160803.pm each define all eight models. Include the desired corner
file separately when simulating; the generated device netlists reference those
models. Structural POC LVS does not replace electrical simulation.

LVS derives flavor independently from masks in GDS: unmarked ACTIVE is RVT;
LVT, SLVT and SRAMVT select their respective device classes. A missing marker,
wrong reference model, overlapping markers or partially covered ACTIVE cannot
silently pass as the requested flavor. DRC adds threshold-mask dimensions,
ACTIVE/gate enclosure and mutual-overlap checks from DRM section 3.7.

Generate GDS, reference SPICE, extracted netlists and a JSON summary for all eight:

    python examples/asap7_devices.py --out-dir asap7_devices

The ASAP7 CI runs the flavor matrix and uploads these eight verified examples
for each geometry backend. Tests cover narrow and multi-finger/multi-row devices,
all eight flavors in a single hierarchy, unchanged current-mirror builders with
selected PDKs, and negative mask/model cases.

## Custom MOM capacitors

The capacitor primitive implements historical mim_cap_size/mim_cap_rows options
using custom interdigitated M3 MOM fingers with M2 terminal bars and V2 contacts.
Its legacy interface exports separate M5 and M4 landings. The original opamp
placement and compensation-route topology remain in use; its capacitor terminal
selection still requires review to connect the two separate MOM plates. Standalone usage:

    capacitor = momcap(asap7, size=(0.4, 0.5))

Layer 100/10 is a recognition marker. The nominal capacitance is 0.1 fF per
micrometre of facing edge at a 44 nm gap, inversely scaled with gap. This model
is uncalibrated and is not a characterized ASAP7 capacitance.

## Verification

    pytest -q tests/test_finfet.py
    python tests/drc/run_cell_drc.py --pdk asap7 --jobs 2 --out-dir asap7_results/drc
    python tests/lvs/run_cell_lvs.py --pdk asap7 --jobs 2 --inputs-dir asap7_results/drc --out-dir asap7_results/lvs

DRC implements an open KLayout rule subset, not the licensed Calibre signoff deck.
It checks manufacturing/fin/gate lattices, channel fin counts, ACTIVE track height,
selected width/spacing/area rules, local contacts, and M1-M5/V0-V4 containment.
It does not comprehensively check tip/corner spacing, pitch adjacency, enclosure,
GCUT, density, or upper-metal routing tracks. No implemented ASAP7 rule is ignored.
Overlapping legacy via landings may yield closely spaced redundant cuts. Export
coalesces collinear cuts only when both existing adjacent metals cover the entire
merged cut; it never bridges a metal gap or changes conductor connectivity.

LVS independently extracts devices and connectivity from GDS and compares external
SPICE. It quantizes schematic widths independently and retains original circuit
schematics. Top-level pins must match. Standalone CI labels in tests/asap7_pins.py
add text only, with no route/device replacement. Repeated declared body labels
represent the same external bulk connection. MOM capacitance is measured from
actual neighbouring finger edges and actual connected nets.

Negative tests cover broken contacts, shorts, wrong fin counts, missing MOM
fingers, illegal placement/rotation, and insufficient GDS precision. Regression
checks also exercise the original mirror/diffpair/FVF path through the finger leaf.

The original alternate-router validation results do not validate this corrected
architecture. Current summaries and extracted/reference netlists must be inspected
for the restored hierarchy; remaining composite failures must not be reported as
DRC/LVS-clean.

## Corrected hierarchy validation

The FinFET/flavor suites pass 78 tests on `gdsfactory` and 84 tests (including
`test_gdstk_backend.py`) on native `gdstk`.
All eight flavor examples (`examples/asap7_devices.py`) pass POC DRC and extracted
LVS on both engines.
All eleven CI circuit examples (`current_mirror_nfet`, `current_mirror_pfet`,
`diff_pair`, `diff_pair_ibias`, `differential_to_single_ended_converter`,
`flipped_voltage_follower`, `low_voltage_cmirror`, `nmos_narrow`, `opamp`,
`pmos_narrow`, and `transmission_gate`) pass both the implemented DRC subset
(11/11) and extracted LVS (11/11) on both `gdsfactory` and `gdstk` backends.
