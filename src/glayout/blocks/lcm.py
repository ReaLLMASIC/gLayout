from glayout.util.netlist_json import write_netlist_json


def lcm(...):
    ...

netlist_dict = {
    "block": "lcm",
    "devices": [
        {
            "name": "M1",
            "type": "nmos",
            "connections": {"D": "out", "G": "in", "S": "vss", "B": "vss"}
        }
    ]
}

write_netlist_json(
    netlist_dict,
    "netlists/lcm.json"
)

    return comp
