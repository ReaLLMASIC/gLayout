"""Circuit data model and SPICE emitters (schematic target netlists per PDK)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import json, hashlib

PDK_MODELS = {
    "sky130": {"nfet": "sky130_fd_pr__nfet_01v8", "pfet": "sky130_fd_pr__pfet_01v8", "res": "sky130_fd_pr__res_high_po_0p35", "cap": "sky130_fd_pr__cap_mim_m3_1", "rsh": 319.8,
               "prefix": "X", "unit": "", "vdd": 1.8},
    "gf180": {"nfet": "nfet_03v3", "pfet": "pfet_03v3", "res": "ppolyf_u", "cap": "cap_mim_2f0fF", "rsh": 315.0, "prefix": "M", "unit": "u", "vdd": 3.3},
    "ihp130": {"nfet": "sg13_lv_nmos", "pfet": "sg13_lv_pmos", "res": "rppd", "cap": "cap_cmim", "rsh": 260.0, "prefix": "X", "unit": "u", "vdd": 1.2},
}


@dataclass
class Device:
    name: str
    kind: str                 # nfet | pfet | res | cap
    nets: list                # MOS: [d,g,s,b]; res/cap: [p,n]
    params: dict = field(default_factory=dict)   # MOS: w (total, um), l (um), nf; res: r (ohm) or w/l; cap: c (F) or w/l

    def to_json(self):
        return asdict(self)


@dataclass
class Circuit:
    circuit_id: str
    name: str
    ports: list
    devices: list                                # list[Device]
    source: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def nets(self):
        s = set()
        for d in self.devices: s.update(d.nets)
        return sorted(s)

    def to_json(self):
        return {"circuit_id": self.circuit_id, "name": self.name, "ports": self.ports, "devices": [d.to_json() for d in self.devices], "source": self.source, "notes": self.notes}

    @staticmethod
    def from_json(d):
        return Circuit(d["circuit_id"], d["name"], list(d["ports"]), [Device(x["name"], x["kind"], list(x["nets"]), dict(x.get("params", {}))) for x in d["devices"]], d.get("source", {}), d.get("notes", []))

    def sha(self):
        return hashlib.sha256(json.dumps(self.to_json(), sort_keys=True).encode()).hexdigest()


def mos_line(pdk: str, dev: Device, w: float, l: float, nf: int = 1, name=None, per_finger=False) -> list[str]:
    m = PDK_MODELS[pdk]; u = m["unit"]; nm = name or dev.name
    model = m[dev.kind]
    d, g, s, b = dev.nets
    if per_finger:
        wf = w / nf
        return [f"{m['prefix']}{nm}_f{k} {d} {g} {s} {b} {model} w={wf:g}{u} l={l:g}{u}" for k in range(nf)]
    if pdk == "ihp130":
        return [f"{m['prefix']}{nm} {d} {g} {s} {b} {model} w={w:g}{u} l={l:g}{u} ng={nf} m=1"]
    if pdk == "gf180":
        return [f"{m['prefix']}{nm} {d} {g} {s} {b} {model} w={w:g}{u} l={l:g}{u} nf={nf} m=1"]
    return [f"{m['prefix']}{nm} {d} {g} {s} {b} {model} w={w:g} l={l:g} nf={nf}"]


def emit_subckt(pdk: str, circuit: Circuit, sizing: dict, name: str, per_finger: bool = False, passives: str = "pdk", lvs: bool = False) -> str:
    """sizing: device name -> {"w":..,"l":..,"nf":..} for MOS; {"r":..,"w":..,"l":..} for res; {"c":..,"w":..,"l":..} for cap."""
    lines = [f".subckt {name} {' '.join(circuit.ports)}"]
    m = PDK_MODELS[pdk]
    for dev in circuit.devices:
        sz = sizing[dev.name]
        if dev.kind in ("nfet", "pfet"):
            lines += mos_line(pdk, dev, float(sz["w"]), float(sz["l"]), int(sz.get("nf", 1)), per_finger=per_finger)
        elif dev.kind == "res":
            p, n = dev.nets
            if passives == "ideal" or "w" not in sz:
                lines.append(f"R{dev.name} {p} {n} {sz['r']:g}")
            else:
                body = sz.get("body", "VSS")
                if pdk == "sky130": lines.append(f"XR{dev.name} {p} {n} {body} {m['res']} l={sz['l']:g} mult=1")
                elif pdk == "gf180": lines.append(f"R{dev.name} {p} {n} {body} {m['res']} L={sz['l']:g}u W={sz['w']:g}u" if lvs else f"XR{dev.name} {p} {n} {body} {m['res']} r_width={sz['w']:g}u r_length={sz['l']:g}u")
                else: lines.append(f"XR{dev.name} {p} {n} {m['res']} w={sz['w']:g}u l={sz['l']:g}u m=1")
        elif dev.kind == "cap":
            p, n = dev.nets
            if passives == "ideal" or "w" not in sz:
                lines.append(f"C{dev.name} {p} {n} {sz['c']:g}")
            else:
                from textbook_sharing.assembly.passives import mimcap_spice_line   # MIM capacitor (geometry from the sizing: w, l in um)
                lines.append(mimcap_spice_line(pdk, dev.name, p, n, sz["w"], sz["l"], lvs=lvs))
    lines.append(f".ends {name}")
    return "\n".join(lines) + "\n"
