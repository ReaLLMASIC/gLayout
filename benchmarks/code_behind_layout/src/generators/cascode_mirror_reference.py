"""Independent flat circuit intent for a six-NMOS cascode current mirror."""
DEFAULT = {"width": 3.0, "length": 1.0, "fingers": 2}
PORTS = ["GND", "IREF", "IOUT", "IBIAS"]


def schematic(config=None):
    z = {**DEFAULT, **(config or {})}
    devices = [
        ("RLOW", "nr", "nr", "GND"),
        ("RHIGH", "IREF", "IBIAS", "nr"),
        ("OLOW", "no", "nr", "GND"),
        ("OHIGH", "IOUT", "IBIAS", "no"),
        ("BLOW", "nb", "nb", "GND"),
        ("BHIGH", "IBIAS", "IBIAS", "nb")]
    lines = ["* Flat independent cascode mirror intent; two separate current feeds",
             ".subckt cascode_mirror " + " ".join(PORTS)]
    for name, drain, gate, source in devices:
        lines.append(f"X{name} {drain} {gate} {source} GND sky130_fd_pr__nfet_01v8 "
                     f"w={z['width']:g} l={z['length']:g} m={z['fingers']}")
    return "\n".join(lines + [".ends cascode_mirror", ""])
