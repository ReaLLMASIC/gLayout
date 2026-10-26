"""Independent intended conventional two-stage Miller OTA schematic.

NMOS input pair / PMOS mirror first stage, NMOS common-source second stage,
PMOS second-stage current source, and explicit N/P diode reference transistors.
The first-stage input order accounts for the second-stage inversion.
"""
DEFAULT = {"input_width": 3.0, "input_fingers": 2, "input_length": 1.0,
           "load_width": 3.0, "load_fingers": 4, "load_length": 1.0,
           "tail_width": 3.0, "tail_fingers": 4, "tail_length": 1.0,
           "second_n_width": 3.0, "second_n_fingers": 12, "second_n_length": .5,
           "second_p_width": 3.0, "second_p_fingers": 16, "second_p_length": 1.0,
           "p_ref_width": 3.0, "p_ref_fingers": 4, "p_ref_length": 1.0,
           "cap_size": 25.0}
PORTS = ["VDD", "GND", "IBIASN", "IBIASP", "VP", "VN", "VOUT"]


def schematic(config=None):
    sizes = {**DEFAULT, **(config or {})}
    lines = ["* Independent conventional 2-stage Miller OTA with explicit diode references",
             ".subckt compact_miller_ota " + " ".join(PORTS)]
    devices = [
        ("NLEFT", "nfet", "mirror", "VN", "tail", "GND", "input"),
        ("NRIGHT", "nfet", "stage1", "VP", "tail", "GND", "input"),
        ("PLEFT", "pfet", "mirror", "mirror", "VDD", "VDD", "load"),
        ("PRIGHT", "pfet", "stage1", "mirror", "VDD", "VDD", "load"),
        ("NTAIL", "nfet", "tail", "IBIASN", "GND", "GND", "tail"),
        ("NREF", "nfet", "IBIASN", "IBIASN", "GND", "GND", "tail"),
        ("NSECOND", "nfet", "VOUT", "stage1", "GND", "GND", "second_n"),
        ("PSECOND", "pfet", "VOUT", "IBIASP", "VDD", "VDD", "second_p"),
        ("PREF", "pfet", "IBIASP", "IBIASP", "VDD", "VDD", "p_ref")]
    for name, kind, drain, gate, source, body, category in devices:
        for finger in range(sizes[category + "_fingers"]):
            lines.append(f"X{name}_{finger} {drain} {gate} {source} {body} sky130_fd_pr__{kind}_01v8"
                         f" w={sizes[category + '_width']:g} l={sizes[category + '_length']:g}")
    lines.append(f"XCC stage1 VOUT sky130_fd_pr__cap_mim_m3_1 l={sizes['cap_size']:g} w={sizes['cap_size']:g}")
    return "\n".join(lines + [".ends compact_miller_ota", ""])
