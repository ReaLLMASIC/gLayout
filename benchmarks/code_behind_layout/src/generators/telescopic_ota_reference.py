"""Independent intent for a cascode-mirror telescopic OTA.

There are nine signal-core transistors and one explicit tail-bias reference.
Widths below are per finger. The PMOS mirror gates sense the lower reference
collector, across the complete reference stack; they are not tied to P1's drain.
No layout module or extracted circuit is read to construct this reference.
"""
DEFAULT = {
    "input_width": 3., "input_length": 1., "input_fingers": 2,
    "ncas_width": 3., "ncas_length": .5, "ncas_fingers": 2,
    "mirror_width": 3., "mirror_length": 1., "mirror_fingers": 4,
    "pcas_width": 3., "pcas_length": .5, "pcas_fingers": 4,
    "tail_width": 3., "tail_length": 1., "tail_fingers": 4,
}
PORTS = ["VDD", "GND", "IBIAS", "VBN", "VBP", "VP", "VN", "VOUT"]


def schematic(sizing=None):
    s = {**DEFAULT, **(sizing or {})}
    lines = ["* Independent 9T telescopic core plus explicit NMOS bias reference",
        ".subckt telescopic_mirror_ota " + " ".join(PORTS)]
    # Literal transistor inventory and node roles, independent of physical
    # placement, routing controls and the PCell's generated netlist.
    intent = [
        ("N1", "nfet", "nl", "VP", "tail", "GND", "input"),
        ("N2", "nfet", "nr", "VN", "tail", "GND", "input"),
        ("N3", "nfet", "mirror", "VBN", "nl", "GND", "ncas"),
        ("N4", "nfet", "VOUT", "VBN", "nr", "GND", "ncas"),
        ("P1", "pfet", "pl", "mirror", "VDD", "VDD", "mirror"),
        ("P2", "pfet", "pr", "mirror", "VDD", "VDD", "mirror"),
        ("P3", "pfet", "mirror", "VBP", "pl", "VDD", "pcas"),
        ("P4", "pfet", "VOUT", "VBP", "pr", "VDD", "pcas"),
        ("NT", "nfet", "tail", "IBIAS", "GND", "GND", "tail"),
        ("NR", "nfet", "IBIAS", "IBIAS", "GND", "GND", "tail"),
    ]
    for name, model, d, g, source, body, category in intent:
        width, length, count = (s[category + suffix] for suffix in ["_width", "_length", "_fingers"])
        if width <= 0 or length <= 0 or not isinstance(count, int) or count <= 0:
            raise ValueError("Positive per-finger W/L and integer finger counts are required")
        for finger in range(count):
            lines.append(f"X{name}_{finger} {d} {g} {source} {body} sky130_fd_pr__{model}_01v8 w={width:g} l={length:g}")
    return "\n".join(lines + [".ends telescopic_mirror_ota", ""])
