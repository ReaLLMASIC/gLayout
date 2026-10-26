"""Independent flat default FVF OTA intended circuit, development only.

Connectivity is specified directly at transistor level. Local PMOS diode nodes
connect to the two low-voltage mirror outputs, rather than to AVDD. Dimensions
and grounded/supply dummy devices follow the documented default physical cells.
This reference is fixed before comparing it with any extracted layout.
"""

PORTS = ["AVDD", "INP", "INM", "VOUT", "NBC_10U", "NB_10U", "AVSS"]


def intended_reference():
    rows = ["* Independent flat default FVF OTA intended reference",
            ".subckt fvf7 " + " ".join(PORTS)]

    def fet(name, d, g, s, b, width, length, polarity="n", parallel=1):
        model = "sky130_fd_pr__" + ("nfet" if polarity == "n" else "pfet") + "_01v8"
        # Preserve the actual parallel finger width in BSIM. A single wide
        # device has the same summed LVS width but different width-bin effects.
        multiplier = f" m={parallel}" if parallel != 1 else ""
        rows.append(f"X{name} {d} {g} {s} {b} {model} w={width/parallel:g} l={length:g}{multiplier}")

    # PMOS differential load, local common-mode feedback, and output devices.
    for side in [1, 2]:
        out = "out_n1" if side == 1 else "VOUT"
        fet(f"ptop{side}", out, f"min{side}_d", "AVDD", "AVDD", 9, 1, "p", parallel=2)
        fet(f"pbot{side}", f"min{side}_d", "lcm_gate", "AVDD", "AVDD", 9, 1, "p", parallel=2)
    fet("pblock_dummy", "AVDD", "AVDD", "AVDD", "AVDD", 18, 1, "p")

    # Eight-transistor low-voltage NMOS bias mirror, two 10 uA inputs.
    fet("bias_a", "NBC_10U", "NBC_10U", "bias_local1", "AVSS", 8.3, 2, parallel=2)
    fet("bias_b", "bias_local1", "NBC_10U", "AVSS", "AVSS", 1.42, 2)
    fet("cas_a", "NB_10U", "NBC_10U", "bias_local2", "AVSS", 8.3, 2, parallel=2)
    fet("cas_b", "bias_local2", "NB_10U", "AVSS", "AVSS", 8.3, 2, parallel=2)
    for side in [1, 2]:
        fet(f"bias_outa{side}", f"local_ref{side}", "NBC_10U", f"cas_out{side}", "AVSS", 8.3, 2, parallel=2)
        fet(f"bias_outb{side}", f"cas_out{side}", "NB_10U", "AVSS", "AVSS", 8.3, 2, parallel=2)
    fet("bias_dummy_w", "AVSS", "AVSS", "AVSS", "AVSS", 7*8.3, 2)
    fet("bias_dummy_n", "AVSS", "AVSS", "AVSS", "AVSS", 2*1.42, 2)

    # Cross-coupled source FVF input stage. INP is the noninverting input.
    for side in [1, 2]:
        inp = "INM" if side == 1 else "INP"
        cross_source = "min2_s" if side == 1 else "min1_s"
        fet(f"input{side}", f"min{side}_d", inp, f"min{side}_s", "AVSS", 4, 2)
        fet(f"fvf_a{side}", f"fvf_ib{side}", inp, cross_source, "AVSS", 8, 2, parallel=2)
        fet(f"fvf_b{side}", cross_source, f"fvf_ib{side}", "AVSS", "AVSS", 5.5, 1, parallel=2)
        fet(f"local_pdiode{side}", f"local_ref{side}", f"local_ref{side}", "AVDD", "AVDD", 3.76, 3, "p", parallel=2)
        fet(f"local_pout{side}", f"fvf_ib{side}", f"local_ref{side}", "AVDD", "AVDD", 3.76, 3, "p", parallel=2)
        fet(f"local_pdummy{side}", "AVDD", "AVDD", "AVDD", "AVDD", 3.76, 3, "p")
        fet(f"resn{side}", "lcm_gate", "AVDD", f"min{side}_d", "AVSS", .5, 4)
        fet(f"resp{side}", "lcm_gate", "AVSS", f"min{side}_d", "AVDD", 3, 4, "p")
    fet("input_fvf_dummy", "AVSS", "AVSS", "AVSS", "AVSS", 2*(8+16), 2)
    fet("shunt_dummy", "AVSS", "AVSS", "AVSS", "AVSS", 2*11, 1)
    fet("resn_dummy", "AVSS", "AVSS", "AVSS", "AVSS", 2, 4)
    fet("resp_dummy", "AVDD", "AVDD", "AVDD", "AVDD", 12, 4, "p")
    fet("output_ref", "out_n1", "out_n1", "AVSS", "AVSS", 4.5, 1, parallel=2)
    fet("output_out", "VOUT", "out_n1", "AVSS", "AVSS", 4.5, 1, parallel=2)
    fet("output_dummy", "AVSS", "AVSS", "AVSS", "AVSS", 4.5, 1)
    rows.extend([".ends fvf7", ""])
    return "\n".join(rows)
