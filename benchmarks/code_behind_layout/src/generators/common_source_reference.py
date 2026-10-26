"""Flat intended graph of an independently biased common-source gain stage."""
PORTS=["VIN","OUT","PBIAS","VDD","VSS"]
DEFAULT={"n_width":2.,"p_width":4.,"length":1.,"fingers":2}


def schematic(sizing=None):
    size={**DEFAULT,**(sizing or {})}
    lines=["* Three-group common-source amplifier with separate PMOS bias reference",
           ".subckt common_source_stage "+" ".join(PORTS)]
    for i in range(size["fingers"]):
        lines += [f"XN{i} OUT VIN VSS VSS sky130_fd_pr__nfet_01v8 w={size['n_width']:g} l={size['length']:g}",
                  f"XP{i} OUT PBIAS VDD VDD sky130_fd_pr__pfet_01v8 w={size['p_width']:g} l={size['length']:g}",
                  f"XB{i} PBIAS PBIAS VDD VDD sky130_fd_pr__pfet_01v8 w={size['p_width']:g} l={size['length']:g}"]
    return "\n".join(lines+[".ends common_source_stage",""])
