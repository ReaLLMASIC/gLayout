"""Circuit = block instances + how their pins connect + placement constraints.

``Circuit.graph()`` builds the near-tripartite graph of the paper (§1.4):
device (block) nodes, pin nodes and net nodes, with typed edges
``device_has_pin``, ``pin_in_net`` and constraint edges between devices
(``symmetry``). Feature vectors follow the paper's table; ``to_dict()`` gives
a JSON-ready form for an R-GCN or any other learner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from glayout.floorplan.block import Block
from glayout.util.process_table import ProcessTable

# functional-structure vocabulary for the device one-hot (the paper uses 28)
KINDS = ["DP", "CM", "CMB", "CASC", "CS", "SF", "INV", "TG", "CAP", "RES", "BIAS", "OTHER"]
SIDES = "NESW"
LAYERS = ["met1", "met2", "met3", "met4", "met5"]


@dataclass
class Instance:
    name: str
    block: Block
    nets: dict[str, str]          # block pin net -> circuit net

    def __post_init__(self):
        missing = set(self.block.nets) - set(self.nets)
        if missing:
            raise ValueError(f"instance {self.name}: unmapped block nets {sorted(missing)}")


@dataclass
class CircuitGraph:
    nodes: list[dict]
    edges: list[tuple[int, int, str]]

    def to_dict(self) -> dict:
        return {"nodes": self.nodes, "edges": [list(e) for e in self.edges],
                "edge_types": sorted({e[2] for e in self.edges})}


@dataclass
class Circuit:
    name: str
    instances: list[Instance]
    symmetric_pairs: list[tuple[str, str]] = field(default_factory=list)
    self_symmetric: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)      # external nets (top-level pins for LVS)
    power_nets: tuple[str, ...] = ("VDD", "AVDD", "VCC")
    ground_nets: tuple[str, ...] = ("VSS", "GND", "AVSS")

    def __post_init__(self):
        names = [i.name for i in self.instances]
        if len(set(names)) != len(names):
            raise ValueError("instance names must be unique")
        for a, b in self.symmetric_pairs:
            ia, ib = self[a], self[b]
            if len(ia.block.variants) != len(ib.block.variants):
                raise ValueError(f"symmetric pair {a}/{b} must have the same variants")
        for n in self.self_symmetric:
            self[n]

    def __getitem__(self, name: str) -> Instance:
        for i in self.instances:
            if i.name == name:
                return i
        raise KeyError(name)

    def net_pins(self, min_pins: int = 1) -> dict[str, list[tuple[str, str]]]:
        """circuit net -> [(instance, block net)]."""
        out: dict[str, list[tuple[str, str]]] = {}
        for inst in self.instances:
            for bnet, cnet in inst.nets.items():
                out.setdefault(cnet, []).append((inst.name, bnet))
        return {n: p for n, p in out.items() if len(p) >= min_pins}

    def net_type(self, net: str) -> str:
        if net in self.power_nets:
            return "power"
        if net in self.ground_nets:
            return "ground"
        return "signal"

    def graph(self) -> CircuitGraph:
        nodes: list[dict] = []
        edges: list[tuple[int, int, str]] = []
        net_ids: dict[str, int] = {}
        dev_ids: dict[str, int] = {}
        nets = self.net_pins()
        with ProcessTable(f"Circuit graph {self.name}") as pt:
            with pt.stage("device + pin nodes") as st:
                for inst in self.instances:
                    v = min(inst.block.variants, key=lambda v: v.area)
                    kind = inst.block.kind if inst.block.kind in KINDS else "OTHER"
                    dev_ids[inst.name] = len(nodes)
                    nodes.append({"type": "device", "name": inst.name, "features": [
                        v.area, v.width, v.height, float(len(v.pins)),
                        *[float(kind == k) for k in KINDS]]})
                    for bnet, pin in v.pins.items():
                        pid = len(nodes)
                        cnet = inst.nets[bnet]
                        nt = self.net_type(cnet)
                        nodes.append({"type": "pin", "name": f"{inst.name}.{bnet}", "features": [
                            *[float(s in pin.sides) for s in SIDES],
                            *[float(nt == t) for t in ("signal", "ground", "power")],
                            *[float(pin.layer == l) for l in LAYERS]]})
                        edges.append((dev_ids[inst.name], pid, "device_has_pin"))
                        if cnet not in net_ids:
                            net_ids[cnet] = -1   # placeholder, filled below
                        edges.append((pid, cnet, "pin_in_net"))   # resolved below
                st.detail(f"{len(dev_ids)} devices, {sum(1 for n in nodes if n['type'] == 'pin')} pins")
            with pt.stage("net nodes") as st:
                for net, pins in nets.items():
                    net_ids[net] = len(nodes)
                    nodes.append({"type": "net", "name": net, "features": [
                        float(len({i for i, _ in pins})), float(len(pins))]})
                edges = [(s, net_ids[d], t) if t == "pin_in_net" else (s, d, t) for s, d, t in edges]
                st.detail(f"{len(net_ids)} nets")
            with pt.stage("constraint edges") as st:
                for a, b in self.symmetric_pairs:
                    edges.append((dev_ids[a], dev_ids[b], "symmetry"))
                    edges.append((dev_ids[b], dev_ids[a], "symmetry"))
                for a in self.self_symmetric:
                    edges.append((dev_ids[a], dev_ids[a], "self_symmetry"))
                st.detail(f"{len(self.symmetric_pairs)} pair(s), {len(self.self_symmetric)} self-symmetric")
            pt.result("nodes", len(nodes))
            pt.result("edges", len(edges))
        return CircuitGraph(nodes, edges)
