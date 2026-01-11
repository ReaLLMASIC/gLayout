import json
from pathlib import Path

def write_netlist_json(netlist: dict, path: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(netlist, f, indent=2)

def read_netlist_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)
