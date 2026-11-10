"""Geometry-free model of a single row of transistor fingers.

A row is a left-to-right sequence of unit fingers. Each finger belongs to a
device and has an orientation: ``flipped=False`` puts the device's source on
the left and its drain on the right. Two neighbouring fingers share one
source/drain contact (one diffusion region) when the net on their common side
is the same; otherwise the row has a diffusion *break* there.

Everything here is pure Python, so the search and its metrics can be tested
without a PDK. Positions are in *finger pitches*; a break adds ``break_gap``
pitches, approximating the extra diffusion spacing the layout inserts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class DeviceSpec:
    """One logical transistor split into ``fingers`` unit fingers."""
    name: str
    source: str
    drain: str
    gate: str
    fingers: int

    def __post_init__(self):
        if self.fingers < 1:
            raise ValueError(f"device {self.name}: fingers must be >= 1")
        if self.source == self.drain:
            raise ValueError(f"device {self.name}: source and drain must be different nets")


@dataclass(frozen=True)
class Finger:
    device: str
    flipped: bool = False

    def nets(self, devices: Mapping[str, DeviceSpec]) -> tuple[str, str]:
        """(left net, right net) of this finger."""
        d = devices[self.device]
        return (d.drain, d.source) if self.flipped else (d.source, d.drain)


@dataclass
class Contact:
    """A source/drain diffusion region between (or at the end of) fingers."""
    net: str
    left: Optional[int]   # index of the finger to its left, None at a segment start
    right: Optional[int]  # index of the finger to its right, None at a segment end
    segment: int

    @property
    def shared(self) -> bool:
        return self.left is not None and self.right is not None


@dataclass
class RowMetrics:
    breaks: int
    centroids: dict[str, float]
    centroid_error: float          # max |c_k - c_j| over device pairs, in pitches
    moment2: dict[str, float]      # mean squared distance from the row centre
    moment2_error: float
    drain_per_finger: dict[str, float]
    drain_imbalance: float         # max - min of drain_per_finger
    drain_contacts: int
    max_run: int                   # longest run of one device

    def as_row(self) -> dict:
        return {
            "breaks": self.breaks,
            "centroid_err": round(self.centroid_error, 4),
            "m2_err": round(self.moment2_error, 4),
            "drain_imbalance": round(self.drain_imbalance, 4),
            "drain_contacts": self.drain_contacts,
            "max_run": self.max_run,
        }


@dataclass
class FingerSequence:
    devices: dict[str, DeviceSpec]
    fingers: tuple[Finger, ...]
    break_gap: float = 1.0

    def __post_init__(self):
        counts = {name: 0 for name in self.devices}
        for f in self.fingers:
            if f.device not in self.devices:
                raise ValueError(f"finger references unknown device {f.device!r}")
            counts[f.device] += 1
        for name, d in self.devices.items():
            if counts[name] != d.fingers:
                raise ValueError(f"device {name}: sequence has {counts[name]} fingers, spec has {d.fingers}")

    # ---- structure -------------------------------------------------------
    def contacts(self) -> list[Contact]:
        out: list[Contact] = []
        seg = 0
        for i, f in enumerate(self.fingers):
            left, right = f.nets(self.devices)
            if i == 0:
                out.append(Contact(left, None, i, seg))
            elif out[-1].net == left:
                out[-1].right = i
            else:
                seg += 1
                out.append(Contact(left, None, i, seg))
            out.append(Contact(right, i, None, seg))
        return out

    def segments(self) -> list[list[int]]:
        """Finger indices of each unbroken diffusion strip."""
        segs: list[list[int]] = [[]]
        for c in self.contacts():
            if c.segment == len(segs):
                segs.append([])
            if c.right is not None:
                segs[c.segment].append(c.right)
        return segs

    @property
    def breaks(self) -> int:
        return len(self.segments()) - 1

    def positions(self) -> list[float]:
        """Finger centre positions in pitches, including the gap at breaks."""
        pos, x, prev_seg = [], 0.0, 0
        seg_of = {}
        for s, idxs in enumerate(self.segments()):
            for i in idxs:
                seg_of[i] = s
        for i in range(len(self.fingers)):
            if seg_of[i] != prev_seg:
                x += self.break_gap
                prev_seg = seg_of[i]
            pos.append(x)
            x += 1.0
        return pos

    # ---- metrics ---------------------------------------------------------
    def metrics(self) -> RowMetrics:
        pos = self.positions()
        centre = (pos[0] + pos[-1]) / 2 if pos else 0.0
        by_dev: dict[str, list[float]] = {n: [] for n in self.devices}
        for f, x in zip(self.fingers, pos):
            by_dev[f.device].append(x)
        centroids = {n: sum(v) / len(v) for n, v in by_dev.items()}
        m2 = {n: sum((x - centre) ** 2 for x in v) / len(v) for n, v in by_dev.items()}
        drains = {n: 0 for n in self.devices}
        n_drain = 0
        for c in self.contacts():
            touching = {self.fingers[i].device for i in (c.left, c.right) if i is not None}
            hit = False
            for n in touching:
                if self.devices[n].drain == c.net:
                    drains[n] += 1
                    hit = True
            n_drain += hit
        dpf = {n: drains[n] / self.devices[n].fingers for n in self.devices}
        run = best = 0
        for i, f in enumerate(self.fingers):
            run = run + 1 if i and self.fingers[i - 1].device == f.device else 1
            best = max(best, run)
        return RowMetrics(
            breaks=self.breaks,
            centroids=centroids,
            centroid_error=_spread(centroids.values()),
            moment2=m2,
            moment2_error=_spread(m2.values()),
            drain_per_finger=dpf,
            drain_imbalance=_spread(dpf.values()),
            drain_contacts=n_drain,
            max_run=best,
        )

    # ---- text forms --------------------------------------------------------
    def labels(self) -> str:
        """Device order only, e.g. ``AABBBBAA``."""
        return "".join(f.device for f in self.fingers)

    def compact(self) -> str:
        """Device + orientation, e.g. ``A+ A- B+ B-`` (``+``: source on the left)."""
        return " ".join(f"{f.device}{'-' if f.flipped else '+'}" for f in self.fingers)

    def diagram(self) -> str:
        """Contact-level picture as in the notes: ``VSS |A| VREF |A| VSS ‖ ...``."""
        parts: list[str] = []
        for c in self.contacts():
            if c.left is None and parts:
                parts.append("‖")
            parts.append(c.net)
            if c.right is not None:
                parts.append(f"|{self.fingers[c.right].device}|")
        return " ".join(parts)

    @classmethod
    def from_compact(cls, devices: Mapping[str, DeviceSpec], text: str, break_gap: float = 1.0) -> "FingerSequence":
        """Parse ``"A+ A- B+ B-"``. A bare device name means ``+``."""
        fingers = []
        for tok in text.split():
            flipped = tok.endswith("-")
            name = tok.rstrip("+-")
            fingers.append(Finger(name, flipped))
        return cls(dict(devices), tuple(fingers), break_gap)


def _spread(values: Iterable[float]) -> float:
    values = list(values)
    return max(values) - min(values) if len(values) > 1 else 0.0


# ---- diffusion graph --------------------------------------------------------

@dataclass
class DiffusionGraph:
    """Nets are nodes; each finger is an edge between its source and drain net.

    A row with no breaks is an Euler trail through this multigraph, so the
    number of odd-degree nodes gives a lower bound on breaks that no ordering
    can beat: each connected component needs max(1, odd/2) trails.
    """
    degree: dict[str, int] = field(default_factory=dict)
    components: list[set[str]] = field(default_factory=list)

    @classmethod
    def build(cls, devices: Sequence[DeviceSpec]) -> "DiffusionGraph":
        parent: dict[str, str] = {}

        def find(a: str) -> str:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        degree: dict[str, int] = {}
        for d in devices:
            for net in (d.source, d.drain):
                parent.setdefault(net, net)
                degree[net] = degree.get(net, 0) + d.fingers
            parent[find(d.source)] = find(d.drain)
        groups: dict[str, set[str]] = {}
        for net in parent:
            groups.setdefault(find(net), set()).add(net)
        return cls(degree, list(groups.values()))

    @property
    def odd_nodes(self) -> list[str]:
        return sorted(n for n, k in self.degree.items() if k % 2)

    def trails_needed(self) -> int:
        total = 0
        for comp in self.components:
            odd = sum(1 for n in comp if self.degree[n] % 2)
            total += max(1, odd // 2)
        return total

    def min_breaks(self) -> int:
        return self.trails_needed() - 1


def check_shareable(devices: Sequence[DeviceSpec]) -> list[str]:
    """Pairs of devices that can never abut without a break (no common S/D net)."""
    out = []
    for i, a in enumerate(devices):
        for b in devices[i + 1:]:
            if not ({a.source, a.drain} & {b.source, b.drain}):
                out.append(f"{a.name}/{b.name}")
    return out
