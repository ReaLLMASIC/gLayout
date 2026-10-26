"""Independent fixed graph for a complementary signal transmission switch."""
PORTS = ["IN", "OUT", "EN", "ENB", "VDD", "VSS"]
DEFAULT = {"n_width": 2.0, "p_width": 4.0, "length": .5, "fingers": 2}


def schematic(sizing=None):
    size = {**DEFAULT, **(sizing or {})}
    lines = ["* Independent complementary transmission switch, per-finger widths",
             ".subckt stacked_switch " + " ".join(PORTS)]
    for index in range(size["fingers"]):
        lines += [f"XN{index} OUT EN IN VSS sky130_fd_pr__nfet_01v8 w={size['n_width']:g} l={size['length']:g}",
                  f"XP{index} OUT ENB IN VDD sky130_fd_pr__pfet_01v8 w={size['p_width']:g} l={size['length']:g}"]
    return "\n".join(lines+[".ends stacked_switch", ""])
