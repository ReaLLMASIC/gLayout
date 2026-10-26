"""Independent flat intent for a biased three-NMOS common-drain buffer."""
DEFAULT = {"input_width": 6.0, "input_length": .5, "input_fingers": 2,
           "bias_width": 3.0, "bias_length": 2.0, "bias_fingers": 2}
PORTS = ["VDD", "GND", "VIN", "VOUT", "IBIAS"]


def schematic(config=None):
    z = {**DEFAULT, **(config or {})}
    return "\n".join(["* Independent common-drain buffer with diode current reference",
        ".subckt source_follower " + " ".join(PORTS),
        f"XIN VDD VIN VOUT GND sky130_fd_pr__nfet_01v8 w={z['input_width']:g} l={z['input_length']:g} m={z['input_fingers']}",
        f"XSINK VOUT IBIAS GND GND sky130_fd_pr__nfet_01v8 w={z['bias_width']:g} l={z['bias_length']:g} m={z['bias_fingers']}",
        f"XBIAS IBIAS IBIAS GND GND sky130_fd_pr__nfet_01v8 w={z['bias_width']:g} l={z['bias_length']:g} m={z['bias_fingers']}",
        ".ends source_follower", ""])
