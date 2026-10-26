"""Fixed flat intent for an NMOS differential gain stage with external loads."""
PORTS = ["VINP", "VINN", "OUTP", "OUTN", "IBIAS", "TAIL", "VSS"]
DEFAULT = {"input_width": 2., "input_length": .6, "bias_width": 2., "bias_length": 1., "fingers": 2}


def schematic(sizing=None):
    s = {**DEFAULT, **(sizing or {})}
    lines = ["* Independent differential stage; resistive loads are explicitly outside DUT",
             ".subckt resistive_diff " + " ".join(PORTS)]
    for index in range(s["fingers"]):
        for name, drain, gate, source, width, length in [
            ("P", "OUTP", "VINP", "TAIL", s["input_width"], s["input_length"]),
            ("N", "OUTN", "VINN", "TAIL", s["input_width"], s["input_length"]),
            ("T", "TAIL", "IBIAS", "VSS", s["bias_width"], s["bias_length"]),
            ("B", "IBIAS", "IBIAS", "VSS", s["bias_width"], s["bias_length"])]:
            lines.append(f"X{name}{index} {drain} {gate} {source} VSS sky130_fd_pr__nfet_01v8 w={width:g} l={length:g}")
    return "\n".join(lines + [".ends resistive_diff", ""])
