"""Intended five-transistor OTA core plus one explicit NMOS bias reference.

This schematic is written independently from the layout assembly. It uses the
standard NMOS differential-pair / PMOS mirror-load topology, not a wrapped OTA.
"""
DEFAULT = {"input_width": 3.0, "input_fingers": 2, "input_length": 1.0,
           "load_width": 3.0, "load_fingers": 4, "load_length": 1.0,
           "tail_width": 3.0, "tail_fingers": 4, "tail_length": 1.0}
PORTS = ["VDD", "GND", "IBIAS", "VP", "VN", "VOUT"]


def schematic(config=None):
    sizes = {**DEFAULT, **(config or {})}
    lines = ["* Independently specified 5T core and diode-connected bias reference",
             ".subckt five_t_ota " + " ".join(PORTS)]
    devices = [("NIP", "nfet", "mirror", "VP", "tail", "GND", "input"),
               ("NIM", "nfet", "VOUT", "VN", "tail", "GND", "input"),
               ("PLD", "pfet", "mirror", "mirror", "VDD", "VDD", "load"),
               ("POUT", "pfet", "VOUT", "mirror", "VDD", "VDD", "load"),
               ("NTAIL", "nfet", "tail", "IBIAS", "GND", "GND", "tail"),
               ("NREF", "nfet", "IBIAS", "IBIAS", "GND", "GND", "tail")]
    for name, kind, drain, gate, source, body, category in devices:
        for finger in range(sizes[category + "_fingers"]):
            lines.append(f"X{name}_{finger} {drain} {gate} {source} {body} sky130_fd_pr__{kind}_01v8"
                         f" w={sizes[category + '_width']:g} l={sizes[category + '_length']:g}")
    lines += [".ends five_t_ota", ""]
    return "\n".join(lines)
