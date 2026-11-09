"""Data model for connection-aware shared MOS construction.

A *logical device* (DeviceSpec) is one SPICE transistor with its four nets and
its electrical size (total width, length, number of unit fingers).  A
*SharingPlan* describes only the physical organisation of the unit fingers of a
group of logical devices: finger order, finger orientation, which adjacent
fingers share a diffusion node, and which gate fingers are tied together by a
poly strap.  A plan never changes the netlist: it cannot remove a device,
change a width/length or a body connection.  Illegal plans are rejected with a
structured EligibilityReport instead of silently producing an independent
layout.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal
import hashlib, json

Polarity = Literal["nfet", "pfet"]
Side = Literal["bottom", "top"]
End = Literal["left", "right"]


@dataclass(frozen=True)
class DeviceSpec:
    logical_id: str
    model_role: Polarity          # 'nfet' or 'pfet' (resolved to a PDK model name by the PDK)
    d: str
    g: str
    s: str
    b: str
    width_total: float            # um, electrical total width (sum over fingers)
    length: float                 # um
    nf: int = 1                   # number of unit fingers; unit width = width_total / nf
    m: int = 1                    # SPICE multiplier is not supported for shared groups (must be 1)

    @property
    def unit_width(self) -> float:
        return self.width_total / self.nf

    def nets(self) -> dict:
        return {"D": self.d, "G": self.g, "S": self.s, "B": self.b}


@dataclass(frozen=True)
class FingerRef:
    device: str
    index: int                    # 0..nf-1 within the device


@dataclass(frozen=True)
class GateGroup:
    fingers: tuple[int, ...]      # positions in finger_order (0..n-1)
    side: Side = "bottom"         # strap side (poly strap below or above the active)
    pad_end: End = "left"         # which end of the group hosts the contact pad(s)


@dataclass
class SharingPlan:
    finger_order: list[FingerRef]
    orientations: list[Literal["SD", "DS"]]      # per position: left terminal then right terminal
    diffusion_joins: list[bool]                  # len n-1: True -> fingers i and i+1 share one diffusion node
    gate_groups: list[GateGroup]                 # partition of positions into poly-strap groups
    gate_contact_policy: Literal["single_end", "both_ends"] = "single_end"
    access_sides: dict = field(default_factory=lambda: {"sd": "top", "gate": "strap_side"})
    dummy_policy: Literal["none"] = "none"
    mode_label: str = "custom"                   # free text: independent / diffusion_only / gate_only / combined / custom

    # ---- canonical form -------------------------------------------------
    def canonical(self) -> dict:
        return {
            "finger_order": [[f.device, f.index] for f in self.finger_order],
            "orientations": list(self.orientations),
            "diffusion_joins": [bool(x) for x in self.diffusion_joins],
            "gate_groups": sorted([[sorted(g.fingers), g.side, g.pad_end] for g in self.gate_groups]),
            "gate_contact_policy": self.gate_contact_policy,
            "access_sides": dict(sorted(self.access_sides.items())),
            "dummy_policy": self.dummy_policy,
        }

    def plan_id(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True).encode()).hexdigest()[:16]

    def to_json(self) -> dict:
        d = self.canonical(); d["mode_label"] = self.mode_label; d["plan_id"] = self.plan_id(); return d

    @staticmethod
    def from_json(d: dict) -> "SharingPlan":
        return SharingPlan(
            finger_order=[FingerRef(a, int(b)) for a, b in d["finger_order"]],
            orientations=list(d["orientations"]),
            diffusion_joins=[bool(x) for x in d["diffusion_joins"]],
            gate_groups=[GateGroup(tuple(int(i) for i in g[0]), g[1], g[2]) for g in d["gate_groups"]],
            gate_contact_policy=d.get("gate_contact_policy", "single_end"),
            access_sides=d.get("access_sides", {"sd": "top", "gate": "strap_side"}),
            dummy_policy=d.get("dummy_policy", "none"),
            mode_label=d.get("mode_label", "custom"),
        )

    # ---- derived structure ---------------------------------------------
    def n(self) -> int:
        return len(self.finger_order)

    def islands(self) -> list[tuple[int, int]]:
        """Return [(first_pos, last_pos)] of maximal runs of joined fingers."""
        out = []; start = 0
        for i in range(self.n() - 1):
            if not self.diffusion_joins[i]:
                out.append((start, i)); start = i + 1
        out.append((start, self.n() - 1))
        return out

    def summary(self) -> dict:
        n_cross = 0; n_cross_gate = 0
        for i, j in enumerate(self.diffusion_joins):
            if j and self.finger_order[i].device != self.finger_order[i + 1].device: n_cross += 1
        for g in self.gate_groups:
            if len({self.finger_order[p].device for p in g.fingers}) > 1: n_cross_gate += 1
        return {"fingers": self.n(), "islands": len(self.islands()), "cross_device_diffusion_joins": n_cross,
                "cross_device_gate_groups": n_cross_gate, "gate_groups": len(self.gate_groups)}


@dataclass
class EligibilityReport:
    ok: bool
    errors: list[dict] = field(default_factory=list)      # {"code":..., "message":..., "where":...}
    warnings: list[dict] = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def add_error(self, code: str, message: str, where=None):
        self.ok = False; self.errors.append({"code": code, "message": message, "where": where})

    def to_json(self) -> dict:
        return asdict(self)


class SharingPlanRejected(ValueError):
    """Raised by build_mos_group when a plan is illegal.  Carries the structured report."""
    def __init__(self, report: EligibilityReport):
        self.report = report
        super().__init__("; ".join(f"{e['code']}: {e['message']}" for e in report.errors))


@dataclass
class GroupResult:
    component: object                         # layout Component (gdsfactory / gdstk backend)
    ports: dict                               # terminal key "dev:T" -> list of port names (met2 pins)
    pin_nets: dict                            # port name -> net
    device_map: dict                          # logical device -> fingers/nodes/islands in the geometry
    applied_plan: dict                        # canonical plan + plan_id
    eligibility_report: dict
    physical_sharing_evidence: dict           # derived from the produced geometry, not from the plan
    geometry_stats: dict                      # bbox, widths, counts
