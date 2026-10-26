"""Independent FVF intent v3: retain each physical dummy's finger dimensions.

Active circuitry is the direct transistor-level intended schematic. Dummy counts
come from the fixed PCell construction, not extracted-device matching: primitive
fet.py emits one dummy per side and multiplier row; interdigitized rows have
one at each edge. Every dummy's D/G/S/B is the same intended supply rail.
The older aggregate-dummy v2 reference and its measurements remain unchanged.
"""

PORTS = ["AVDD", "INP", "INM", "VOUT", "NBC_10U", "NB_10U", "AVSS"]

# Source binding: vendor/glayout-e2-development d092211, relative to src/glayout.
# Counts are physical edge dummies, independent of active fingers per row.
DUMMY_SOURCE_RULES = {
    "pblock_dummy": {"parallel": 4, "rule": "p_block.py two interdigitized rows, two edges each, per-finger width9/2"},
    "bias_dummy_w": {"parallel": 14, "rule": "low_voltage_cmirror.py seven wide single-row devices, two sides each, width8.3/2"},
    "bias_dummy_n": {"parallel": 2, "rule": "low_voltage_cmirror.py one narrow single-row device, two sides, width1.42"},
    "local_pdummy1": {"parallel": 2, "rule": "ota.py current_mirror(numcols2,width=localW/2); one interdigitized row, two edges"},
    "local_pdummy2": {"parallel": 2, "rule": "second local current mirror, same independent two-edge rule"},
    "input_fvf_dummy": {"parallel": 12, "rule": "n_block.py two input one-row devices(4 edges) plus two FVF A devices with2 multiplier rows(8 edges), width4"},
    "shunt_dummy": {"parallel": 8, "rule": "n_block.py two FVF B devices with2 multiplier rows, two edges per row, width2.75"},
    "resn_dummy": {"parallel": 4, "rule": "ota.py two transmission-gate nMOS devices, two edges each, width.5"},
    "resp_dummy": {"parallel": 4, "rule": "ota.py two transmission-gate pMOS devices, two edges each, width3"},
    "output_dummy": {"parallel": 2, "rule": "n_block.py output current mirror numcols2 width2.25, one interdigitized row, two edges"},
}


def intended_reference(local_current_bias_params=(3.76, 3.)):
    local_width, local_length = local_current_bias_params
    rows = ["* Independent FVF intent v3; explicit per-finger active and rail-short dummy devices",
        ".subckt fvf7 "+" ".join(PORTS)]
    def fet(name, d, g, s, b, width, length, polarity="n", parallel=1):
        model = "sky130_fd_pr__"+("nfet" if polarity == "n" else "pfet")+"_01v8"
        multiplier = f" m={parallel}" if parallel != 1 else ""
        rows.append(f"X{name} {d} {g} {s} {b} {model} w={width/parallel:g} l={length:g}{multiplier}")
    for side in [1, 2]:
        out = "out_n1" if side == 1 else "VOUT"
        fet(f"ptop{side}", out, f"min{side}_d", "AVDD", "AVDD", 9, 1, "p", parallel=2)
        fet(f"pbot{side}", f"min{side}_d", "lcm_gate", "AVDD", "AVDD", 9, 1, "p", parallel=2)
    fet("pblock_dummy", "AVDD", "AVDD", "AVDD", "AVDD", 18, 1, "p", parallel=4)
    fet("bias_a", "NBC_10U", "NBC_10U", "bias_local1", "AVSS", 8.3, 2, parallel=2)
    fet("bias_b", "bias_local1", "NBC_10U", "AVSS", "AVSS", 1.42, 2)
    fet("cas_a", "NB_10U", "NBC_10U", "bias_local2", "AVSS", 8.3, 2, parallel=2)
    fet("cas_b", "bias_local2", "NB_10U", "AVSS", "AVSS", 8.3, 2, parallel=2)
    for side in [1, 2]:
        fet(f"bias_outa{side}", f"local_ref{side}", "NBC_10U", f"cas_out{side}", "AVSS", 8.3, 2, parallel=2)
        fet(f"bias_outb{side}", f"cas_out{side}", "NB_10U", "AVSS", "AVSS", 8.3, 2, parallel=2)
    fet("bias_dummy_w", "AVSS", "AVSS", "AVSS", "AVSS", 7*8.3, 2, parallel=14)
    fet("bias_dummy_n", "AVSS", "AVSS", "AVSS", "AVSS", 2*1.42, 2, parallel=2)
    for side in [1, 2]:
        inp = "INM" if side == 1 else "INP"
        cross_source = "min2_s" if side == 1 else "min1_s"
        fet(f"input{side}", f"min{side}_d", inp, f"min{side}_s", "AVSS", 4, 2)
        fet(f"fvf_a{side}", f"fvf_ib{side}", inp, cross_source, "AVSS", 8, 2, parallel=2)
        fet(f"fvf_b{side}", cross_source, f"fvf_ib{side}", "AVSS", "AVSS", 5.5, 1, parallel=2)
        fet(f"local_pdiode{side}", f"local_ref{side}", f"local_ref{side}", "AVDD", "AVDD", local_width, local_length, "p", parallel=2)
        fet(f"local_pout{side}", f"fvf_ib{side}", f"local_ref{side}", "AVDD", "AVDD", local_width, local_length, "p", parallel=2)
        fet(f"local_pdummy{side}", "AVDD", "AVDD", "AVDD", "AVDD", local_width, local_length, "p", parallel=2)
        fet(f"resn{side}", "lcm_gate", "AVDD", f"min{side}_d", "AVSS", .5, 4)
        fet(f"resp{side}", "lcm_gate", "AVSS", f"min{side}_d", "AVDD", 3, 4, "p")
    fet("input_fvf_dummy", "AVSS", "AVSS", "AVSS", "AVSS", 2*(8+16), 2, parallel=12)
    fet("shunt_dummy", "AVSS", "AVSS", "AVSS", "AVSS", 2*11, 1, parallel=8)
    fet("resn_dummy", "AVSS", "AVSS", "AVSS", "AVSS", 2, 4, parallel=4)
    fet("resp_dummy", "AVDD", "AVDD", "AVDD", "AVDD", 12, 4, "p", parallel=4)
    fet("output_ref", "out_n1", "out_n1", "AVSS", "AVSS", 4.5, 1, parallel=2)
    fet("output_out", "VOUT", "out_n1", "AVSS", "AVSS", 4.5, 1, parallel=2)
    fet("output_dummy", "AVSS", "AVSS", "AVSS", "AVSS", 4.5, 1, parallel=2)
    return "\n".join(rows+[".ends fvf7", ""])
